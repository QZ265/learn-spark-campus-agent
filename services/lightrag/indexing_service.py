import hashlib
import json
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional

from .client import LightRAGClient
from .course_registry import validate_workspace
from .document_parser import parse_document, render_index_text


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md", ".markdown"}
MAX_UPLOAD_BYTES = 80 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_filename(filename: str) -> str:
    name = Path(filename or "").name.replace("\x00", "").strip()
    if not name or name in {".", ".."}:
        raise ValueError("文件名无效")
    return name[:180]


class IndexingService:
    def __init__(self, storage, client: LightRAGClient, base_dir: Path):
        self.storage = storage
        self.client = client
        self.base_dir = Path(base_dir)
        self.upload_root = self.base_dir / "data" / "uploads"
        self.parsed_root = self.base_dir / "data" / "parsed"
        workers = max(1, min(2, int(__import__("os").getenv("INDEXING_WORKERS", "2"))))
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()

    def enqueue_source(
        self,
        source_path: Path,
        course_id: str,
        workspace: str,
        assistant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        copy_original: bool = True,
        force_reindex: bool = False,
        skip_duplicates: bool = True,
    ) -> dict:
        source_path = Path(source_path).resolve()
        workspace = validate_workspace(workspace)
        if not source_path.is_file():
            raise ValueError("待导入文件不存在")
        extension = source_path.suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不允许的文件类型：{extension or '无扩展名'}")
        size = source_path.stat().st_size
        if size <= 0 or size > MAX_UPLOAD_BYTES:
            raise ValueError("文件为空或超过 80MB 限制")
        digest = sha256_file(source_path)
        existing = self.storage.find_document_by_hash(workspace, digest)
        if existing and skip_duplicates and not force_reindex:
            job_id = "job_" + uuid.uuid4().hex
            job = self.storage.create_indexing_job({
                "job_id": job_id,
                "document_id": existing["document_id"],
                "assistant_id": assistant_id,
                "course_id": course_id,
                "workspace": workspace,
                "user_id": user_id,
                "status": "duplicate",
                "progress": 100,
                "stage": "sha256_duplicate_blocked",
                "error_message": f"同一 workspace 已存在相同 SHA256 文件：{existing['filename']}",
            })
            return {"document": existing, "job": job, "duplicate": True}

        scoped_digest = hashlib.sha256(f"{workspace}:{digest}".encode("utf-8")).hexdigest()
        document_id = existing["document_id"] if existing else "doc_" + scoped_digest[:20]
        filename = safe_filename(source_path.name)
        document_dir = self.upload_root / workspace / document_id
        document_dir.mkdir(parents=True, exist_ok=True)
        original_path = document_dir / filename
        if copy_original and source_path != original_path:
            shutil.copy2(source_path, original_path)
        else:
            original_path = source_path
        document = {
            "document_id": document_id,
            "course_id": course_id,
            "workspace": workspace,
            "assistant_id": assistant_id,
            "user_id": user_id,
            "filename": filename,
            "format": extension.lstrip("."),
            "size_bytes": size,
            "sha256": digest,
            "source_path": str(source_path),
            "original_path": str(original_path),
            "index_status": "queued",
            "error_message": None,
        }
        self.storage.save_knowledge_document(document)
        job_id = "job_" + uuid.uuid4().hex
        job = self.storage.create_indexing_job({
            "job_id": job_id,
            "document_id": document_id,
            "assistant_id": assistant_id,
            "course_id": course_id,
            "workspace": workspace,
            "user_id": user_id,
            "status": "queued",
            "progress": 0,
            "stage": "queued",
        })
        future = self.executor.submit(self._run_job, job_id, force_reindex)
        with self._lock:
            self._futures[job_id] = future
        return {"document": self.storage.get_knowledge_document(document_id), "job": job, "duplicate": False}

    def _run_job(self, job_id: str, force_reindex: bool = False) -> None:
        job = self.storage.get_indexing_job(job_id)
        if not job:
            return
        document = self.storage.get_knowledge_document(job["document_id"])
        if not document:
            self.storage.update_indexing_job(job_id, "failed", 0, "missing_document", "文档记录不存在")
            return
        try:
            self.storage.update_indexing_job(job_id, "running", 8, "validating", increment_attempt=True)
            source_path = Path(document["original_path"])
            if sha256_file(source_path) != document["sha256"]:
                raise ValueError("原文件 SHA256 已变化，拒绝继续索引")
            self.storage.update_indexing_job(job_id, "running", 25, "parsing")
            parsed = parse_document(source_path)
            parsed_dir = self.parsed_root / document["workspace"]
            parsed_dir.mkdir(parents=True, exist_ok=True)
            parsed_path = parsed_dir / f"{document['document_id']}.json"
            parsed_path.write_text(json.dumps(parsed.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            document.update({
                "parsed_path": str(parsed_path),
                "parser": parsed.parser,
                "parser_version": parsed.parser_version,
                "index_status": "indexing",
                "error_message": None,
            })
            self.storage.save_knowledge_document(document)
            self.storage.update_indexing_job(job_id, "running", 52, "embedding_and_indexing")
            index_text = render_index_text(parsed, document["document_id"], document["course_id"])
            track_id = self.client.insert_document(
                document["workspace"], document["document_id"], index_text,
                document["original_path"], force=force_reindex,
            )
            self.storage.update_indexing_job(job_id, "running", 88, "retrieval_self_test")
            sample = parsed.sections[0].content[:180]
            query = " ".join(sample.split()[:18]) or parsed.title
            hits = self.client.query_chunks(document["workspace"], query, top_k=3)
            if not any(hit.get("document_id") == document["document_id"] for hit in hits):
                raise RuntimeError("索引完成但检索自测未命中当前文档")
            document.update({
                "index_status": "indexed",
                "error_message": None,
                "lightrag_track_id": track_id,
                "indexed_at": self.storage.utc_now(),
            })
            self.storage.save_knowledge_document(document)
            self.storage.update_indexing_job(job_id, "completed", 100, "completed")
            if document.get("assistant_id"):
                self.storage.update_assistant_status(document["assistant_id"], "ready")
        except Exception as exc:
            document["index_status"] = "failed"
            document["error_message"] = str(exc)[:1000]
            self.storage.save_knowledge_document(document)
            self.storage.update_indexing_job(job_id, "failed", 100, "failed", str(exc)[:1000])
            if document.get("assistant_id"):
                self.storage.update_assistant_status(document["assistant_id"], "indexing_failed")

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[dict]:
        with self._lock:
            future = self._futures.get(job_id)
        if future:
            future.result(timeout=timeout)
        return self.storage.get_indexing_job(job_id)

    def resume_pending(self, retry_failed: bool = False) -> int:
        count = 0
        for job in self.storage.list_resumable_jobs(retry_failed=retry_failed):
            self.storage.update_indexing_job(job["job_id"], "queued", job.get("progress", 0), "resumed_after_restart")
            future = self.executor.submit(self._run_job, job["job_id"], False)
            with self._lock:
                self._futures[job["job_id"]] = future
            count += 1
        return count
