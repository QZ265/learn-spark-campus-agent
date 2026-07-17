#!/usr/bin/env python3
"""Recoverable, incremental course-material importer."""

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from services.lightrag.client import LightRAGClient  # noqa: E402
from services.lightrag.course_registry import get_course, list_courses  # noqa: E402
from services.lightrag.indexing_service import IndexingService  # noqa: E402
from services.storage import AppStorage  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按课程增量导入已确认的教材")
    parser.add_argument("--manifest", default=str(BASE_DIR / "data" / "course_material_manifest.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--course")
    parser.add_argument("--domain")
    parser.add_argument("--document-id")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--force-reindex", action="store_true")
    parser.add_argument("--skip-duplicates", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--sync-deletions", action="store_true", help="删除源目录中已不存在文档的 LightRAG 索引")
    return parser.parse_args()


def save_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    os.environ["INDEXING_WORKERS"] = str(max(1, min(4, args.workers)))
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print("教材清单不存在，请先运行 scripts/scan_course_materials.py", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    storage = AppStorage(Path(os.getenv("APP_DB_PATH", str(BASE_DIR / "data" / "app.db"))))
    storage.register_courses(list_courses())
    client = LightRAGClient()
    if not client.available:
        print("LightRAG 未安装，请使用 .venv-lightrag 执行本脚本", file=sys.stderr)
        return 2
    service = IndexingService(storage, client, BASE_DIR)
    if args.sync_deletions:
        deleted = 0
        for document in storage.list_knowledge_documents():
            if document.get("user_id") or document.get("index_status") != "indexed":
                continue
            if Path(document["source_path"]).exists():
                continue
            result = client.delete_document(document["workspace"], document["document_id"])
            if result.get("status") in {"success", "not_found"}:
                storage.mark_document_deleted(document["document_id"], "源教材已删除，索引已同步移除")
                deleted += 1
        print(json.dumps({"deleted_indexes": deleted}, ensure_ascii=False))
    if args.resume or args.retry_failed:
        resumed = service.resume_pending(retry_failed=args.retry_failed)
        print(json.dumps({"resumed_jobs": resumed}, ensure_ascii=False))
        if args.resume and not any((args.course, args.domain, args.document_id)):
            return 0

    candidates = []
    try:
        import ocrmac  # noqa: F401
        ocr_available = sys.platform == "darwin"
    except ImportError:
        ocr_available = False
    for item in manifest.get("documents", []):
        if args.course and item.get("course_id") != args.course:
            continue
        if args.domain and item.get("domain") != args.domain:
            continue
        if args.document_id and item.get("document_id") != args.document_id:
            continue
        if not item.get("course_id") or not get_course(item["course_id"]):
            continue
        if item.get("needs_manual_review") or not item.get("is_parseable"):
            continue
        if item.get("needs_ocr") and not ocr_available:
            continue
        if item.get("is_duplicate") and args.skip_duplicates:
            continue
        candidates.append(item)
    if args.limit > 0:
        candidates = candidates[: args.limit]
    print(json.dumps({
        "selected": len(candidates),
        "documents": [{"document_id": item["document_id"], "course_id": item["course_id"], "path": item["relative_path"]} for item in candidates],
        "dry_run": args.dry_run,
    }, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    failures = 0
    for item in candidates:
        course = get_course(item["course_id"])
        try:
            queued = service.enqueue_source(
                Path(item["absolute_path"]),
                course.course_id,
                course.workspace,
                copy_original=True,
                force_reindex=args.force_reindex,
                skip_duplicates=args.skip_duplicates,
            )
            job = queued["job"]
            if not queued["duplicate"]:
                job = service.wait(job["job_id"], timeout=3600)
            item["import_status"] = "indexed" if job["status"] == "completed" else job["status"]
            item["failure_reason"] = job.get("error_message") or ""
            print(json.dumps({"document_id": item["document_id"], "job_id": job["job_id"], "status": job["status"], "stage": job["stage"]}, ensure_ascii=False))
            if job["status"] not in {"completed", "duplicate"}:
                failures += 1
        except Exception as exc:
            failures += 1
            item["import_status"] = "failed"
            item["failure_reason"] = str(exc)[:1000]
            print(json.dumps({"document_id": item["document_id"], "status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        finally:
            save_manifest(manifest_path, manifest)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
