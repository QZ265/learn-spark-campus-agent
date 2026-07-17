import asyncio
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import requests

from .course_registry import validate_workspace


BASE_DIR = Path(__file__).resolve().parents[2]
RAG_ROOT = Path(os.getenv("LIGHTRAG_WORKING_DIR", str(BASE_DIR / "data" / "lightrag")))
EMBEDDING_MODEL = os.getenv("LIGHTRAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DIM = int(os.getenv("LIGHTRAG_EMBEDDING_DIM", "512"))
EMBEDDING_MAX_TOKENS = int(os.getenv("LIGHTRAG_EMBEDDING_MAX_TOKENS", "512"))
EMBEDDING_BATCH_SIZE = int(os.getenv("LIGHTRAG_EMBEDDING_BATCH_SIZE", "16"))
ENABLE_KG = os.getenv("LIGHTRAG_ENABLE_KG", "false").lower() == "true"

_embedding_model = None
_embedding_lock = threading.Lock()


def _get_embedding_model():
    global _embedding_model
    with _embedding_lock:
        if _embedding_model is None:
            from fastembed import TextEmbedding

            cache_dir = BASE_DIR / "data" / "models" / "fastembed"
            cache_dir.mkdir(parents=True, exist_ok=True)
            _embedding_model = TextEmbedding(
                model_name=EMBEDDING_MODEL,
                cache_dir=str(cache_dir),
                threads=max(1, min(4, os.cpu_count() or 2)),
            )
    return _embedding_model


async def local_embedding(texts: List[str], context: str = "document", **_: Any) -> np.ndarray:
    def encode() -> np.ndarray:
        model = _get_embedding_model()
        iterator = model.query_embed(texts) if context == "query" else model.embed(texts, batch_size=EMBEDDING_BATCH_SIZE)
        vectors = [np.asarray(vector, dtype=np.float32) for vector in iterator]
        if not vectors:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        return np.vstack(vectors)

    return await asyncio.to_thread(encode)


def _spark_request(prompt: str, system_prompt: Optional[str], history_messages: List[dict]) -> str:
    password = os.getenv("SPARK_API_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("未配置 SPARK_API_PASSWORD，无法启用 LightRAG 图谱抽取")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(history_messages or [])
    messages.append({"role": "user", "content": prompt})
    response = requests.post(
        os.getenv("SPARK_BASE_URL", "https://spark-api-open.xf-yun.com/x2/chat/completions"),
        headers={"Authorization": f"Bearer {password}", "Content-Type": "application/json"},
        json={
            "model": os.getenv("SPARK_MODEL", "spark-x"),
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        },
        timeout=int(os.getenv("SPARK_TIMEOUT_SECONDS", "75")),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") not in (None, 0):
        raise RuntimeError(f"Spark 返回错误：{payload.get('code')} {payload.get('message', '')}")
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("Spark 返回了空内容")
    return str(content)


async def spark_lightrag_llm(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[List[dict]] = None,
    **_: Any,
) -> str:
    return await asyncio.to_thread(_spark_request, prompt, system_prompt, history_messages or [])


class LightRAGClient:
    """Open a short-lived LightRAG instance per operation to avoid event-loop leakage."""

    def __init__(self, working_dir: Path = RAG_ROOT):
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def package_version() -> Optional[str]:
        try:
            from importlib.metadata import version

            return version("lightrag-hku")
        except Exception:
            return None

    @property
    def available(self) -> bool:
        return self.package_version() is not None

    async def _open(self, workspace: str):
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc

        workspace = validate_workspace(workspace)
        rag = LightRAG(
            working_dir=str(self.working_dir),
            workspace=workspace,
            llm_model_func=spark_lightrag_llm,
            llm_model_name=os.getenv("SPARK_MODEL", "spark-x"),
            embedding_func=EmbeddingFunc(
                embedding_dim=EMBEDDING_DIM,
                max_token_size=EMBEDDING_MAX_TOKENS,
                model_name=EMBEDDING_MODEL,
                supports_asymmetric=True,
                func=local_embedding,
            ),
            embedding_batch_num=EMBEDDING_BATCH_SIZE,
            rerank_model_func=None,
        )
        await rag.initialize_storages()
        return rag

    async def _insert_async(self, workspace: str, document_id: str, text: str, file_path: str, force: bool) -> str:
        rag = await self._open(workspace)
        try:
            if force:
                await rag.adelete_by_doc_id(document_id)
            if ENABLE_KG:
                return await rag.ainsert(text, ids=document_id, file_paths=file_path)
            track_id = f"index-{document_id}"
            await rag.apipeline_enqueue_documents(
                text,
                ids=document_id,
                file_paths=file_path,
                track_id=track_id,
                process_options="!F",
            )
            await rag.apipeline_process_enqueue_documents()
            return track_id
        finally:
            await rag.finalize_storages()

    def insert_document(self, workspace: str, document_id: str, text: str, file_path: str, force: bool = False) -> str:
        return asyncio.run(self._insert_async(workspace, document_id, text, file_path, force))

    async def _query_async(self, workspace: str, query: str, top_k: int) -> List[Dict[str, Any]]:
        rag = await self._open(workspace)
        try:
            results = await rag.chunks_vdb.query(query, top_k=top_k)
            return [
                {
                    "chunk_id": item.get("id", ""),
                    "document_id": item.get("full_doc_id", ""),
                    "content": item.get("content", ""),
                    "file_path": item.get("file_path", "unknown_source"),
                    "relevance": float(item.get("distance", 0.0)),
                }
                for item in results
            ]
        finally:
            await rag.finalize_storages()

    def query_chunks(self, workspace: str, query: str, top_k: int = 6) -> List[Dict[str, Any]]:
        return asyncio.run(self._query_async(validate_workspace(workspace), query, top_k))

    async def _delete_async(self, workspace: str, document_id: str) -> dict:
        rag = await self._open(workspace)
        try:
            result = await rag.adelete_by_doc_id(document_id)
            return {
                "status": getattr(result, "status", "unknown"),
                "message": getattr(result, "message", ""),
            }
        finally:
            await rag.finalize_storages()

    def delete_document(self, workspace: str, document_id: str) -> dict:
        return asyncio.run(self._delete_async(validate_workspace(workspace), document_id))

    def status(self) -> dict:
        return {
            "available": self.available,
            "version": self.package_version(),
            "working_dir": str(self.working_dir),
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dim": EMBEDDING_DIM,
            "embedding_max_tokens": EMBEDDING_MAX_TOKENS,
            "embedding_batch_size": EMBEDDING_BATCH_SIZE,
            "kg_enabled": ENABLE_KG,
            "reranker_enabled": False,
        }
