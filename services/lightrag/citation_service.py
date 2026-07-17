import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .document_parser import SOURCE_MARKER, extract_source_markers


def _snippet(content: str, limit: int = 520) -> str:
    cleaned = re.sub(rf"\[{SOURCE_MARKER}\]\{{[^\n]+\}}", "", content or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:limit]


def _infer_marker(document: dict, content: str, course_id: str) -> dict:
    parsed_path = document.get("parsed_path")
    if not parsed_path or not Path(parsed_path).exists():
        return {"document_id": document["document_id"], "course_id": course_id}
    try:
        parsed = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
        needle = _snippet(content, 800)
        ngrams = {needle[index : index + 3] for index in range(max(0, len(needle) - 2))}
        best, best_score = None, -1
        for section in parsed.get("sections", []):
            text = str(section.get("content") or "")
            score = sum(1 for gram in ngrams if gram and gram in text)
            if score > best_score:
                best, best_score = section, score
        if best:
            return {
                "document_id": document["document_id"],
                "course_id": course_id,
                "chapter": best.get("chapter"),
                "page_index": best.get("page_index"),
                "source_kind": best.get("source_kind"),
            }
    except Exception:
        pass
    return {"document_id": document["document_id"], "course_id": course_id}


def build_citations(
    chunks: List[Dict[str, Any]],
    storage,
    course_id: str,
    workspace: str,
) -> List[Dict[str, Any]]:
    citations = []
    seen = set()
    for chunk in chunks:
        markers = extract_source_markers(chunk.get("content", ""))
        if not markers and chunk.get("document_id"):
            fallback_document = storage.get_knowledge_document(str(chunk["document_id"]))
            if fallback_document:
                markers = [_infer_marker(fallback_document, chunk.get("content", ""), course_id)]
        for marker in markers:
            document_id = str(marker.get("document_id") or "")
            document = storage.get_knowledge_document(document_id)
            if not document or document.get("index_status") != "indexed":
                continue
            if document.get("course_id") != course_id or document.get("workspace") != workspace:
                continue
            page_index = marker.get("page_index")
            fingerprint = f"{course_id}|{workspace}|{document_id}|{chunk.get('chunk_id')}|{page_index}"
            citation_id = "cite_" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:18]
            if citation_id in seen:
                continue
            seen.add(citation_id)
            citations.append({
                "id": citation_id,
                "citation_id": citation_id,
                "document_id": document_id,
                "course_id": course_id,
                "workspace": workspace,
                "title": document["filename"],
                "material_name": document["filename"],
                "chapter": marker.get("chapter") or "未标注章节",
                "page_index": page_index,
                "source_kind": marker.get("source_kind") or "section",
                "snippet": _snippet(chunk.get("content", "")),
                "relevance": round(float(chunk.get("relevance", 0.0)), 6),
                "chunk_id": chunk.get("chunk_id", ""),
                "url": f"/api/assistants/documents/{document_id}",
            })
    return citations


def validate_citation_scope(citations: List[dict], course_id: str, workspace: str) -> List[str]:
    issues = []
    for item in citations:
        if item.get("course_id") != course_id:
            issues.append(f"引用 {item.get('citation_id')} 不属于当前课程")
        if item.get("workspace") != workspace:
            issues.append(f"引用 {item.get('citation_id')} 发生跨 workspace 污染")
        if not item.get("snippet"):
            issues.append(f"引用 {item.get('citation_id')} 缺少原文片段")
    return issues
