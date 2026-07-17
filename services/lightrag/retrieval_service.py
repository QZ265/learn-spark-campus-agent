import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from services.safety_service import check_input, contains_secret

from .citation_service import build_citations, validate_citation_scope


REFUSAL = "当前课程知识库中没有找到足够可靠的资料。"
MIN_RELEVANCE = float(os.getenv("LIGHTRAG_MIN_RELEVANCE", "0.45"))


class RetrievalService:
    def __init__(self, storage, client, model_call: Callable, reviewer=None):
        self.storage = storage
        self.client = client
        self.model_call = model_call
        self.reviewer = reviewer

    def retrieve(self, course_id: str, workspace: str, message: str, top_k: int = 6) -> dict:
        chunks = self.client.query_chunks(workspace, message, top_k=top_k)
        chunks = [item for item in chunks if float(item.get("relevance", 0.0)) >= MIN_RELEVANCE]
        chunks = [
            item for item in chunks
            if check_input(str(item.get("content") or ""))["allowed"]
            and not contains_secret(str(item.get("content") or ""))
        ]
        citations = build_citations(chunks, self.storage, course_id, workspace)
        if not citations:
            return {"answer": REFUSAL, "citations": [], "claims": [], "review": {"status": "insufficient_evidence", "issues": [REFUSAL]}, "chunks": []}
        issues = validate_citation_scope(citations, course_id, workspace)
        if issues:
            return {"answer": REFUSAL, "citations": [], "claims": [], "review": {"status": "rejected", "issues": issues}, "chunks": []}
        return {"citations": citations, "chunks": chunks}

    def answer(
        self,
        user_id: str,
        course_id: str,
        workspace: str,
        message: str,
        profile: Optional[dict] = None,
    ) -> dict:
        result = self.retrieve(course_id, workspace, message)
        citations = result.get("citations", [])
        if not citations:
            return result
        evidence = [
            {
                "citation_id": item["citation_id"],
                "title": item["material_name"],
                "chapter": item["chapter"],
                "page_index": item["page_index"],
                "text": item["snippet"],
            }
            for item in citations
        ]
        prompt = f"""
你是课程知识库助手，只能依据给定原文回答，不能使用未提供的教材、章节或页码。
若原文不足以回答，必须只回答：{REFUSAL}
每个核心事实句末必须标注支持它的引用 ID，格式为 [cite_xxx]。
不要把引用 ID 改名，不要输出不存在的引用。直接回答问题，不展示内部推理。
当前课程：{course_id}
学生画像中有证据的内容：{json.dumps(profile or {}, ensure_ascii=False)}
问题：{message}
原文证据：{json.dumps(evidence, ensure_ascii=False)}
""".strip()
        last_review = {"status": "insufficient_evidence", "issues": ["尚未审核"]}
        generated = {"mode": "failed"}
        for attempt in range(3):
            generated = self.model_call(
                "grounded_answer",
                prompt,
                {"user_id": user_id, "course_id": course_id, "workspace": workspace, "citations": citations},
            )
            answer = str(generated.get("content") or "").strip()
            if not answer:
                last_review = {"status": "insufficient_evidence", "issues": [generated.get("error") or "模型未返回回答"]}
                break
            valid_ids = {item["citation_id"] for item in citations}
            used_ids = set(re.findall(r"\[(cite_[a-f0-9]+)\]", answer))
            unknown = used_ids - valid_ids
            if unknown or (answer != REFUSAL and not used_ids):
                issues = (["回答包含不存在的引用"] if unknown else []) + (["核心回答没有绑定引用"] if not used_ids else [])
                last_review = {"status": "needs_revision", "issues": issues, "mode": "citation_scope_validation"}
            elif self.reviewer:
                last_review = self.reviewer.review(
                    user_id,
                    [{
                        "id": "rag-answer",
                        "type": "explanation",
                        "title": "课程知识库回答",
                        "content": {"answer": answer},
                        "citation_ids": sorted(used_ids),
                    }],
                    citations,
                )
            else:
                last_review = {"status": "passed", "issues": [], "mode": "citation_scope_validation"}
            if last_review.get("status") == "passed":
                claims = [
                    {"claim": sentence.strip(), "citation_ids": re.findall(r"\[(cite_[a-f0-9]+)\]", sentence), "support_status": "supported"}
                    for sentence in re.split(r"(?<=[。！？\n])", answer)
                    if sentence.strip() and re.search(r"\[cite_[a-f0-9]+\]", sentence)
                ]
                return {**result, "answer": answer, "claims": claims, "review": last_review, "mode": generated.get("mode", "failed")}
            prompt += "\n上次审核未通过：" + json.dumps(last_review.get("issues", []), ensure_ascii=False) + "。请严格依据原文修订。"
        return {
            **result,
            "answer": REFUSAL,
            "claims": [],
            "review": last_review,
            "mode": generated.get("mode", "failed"),
        }
