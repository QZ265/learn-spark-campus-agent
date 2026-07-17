import html
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from .profile_service import safe_json_object
from .review_service import ReviewService
from .storage import AppStorage


RESOURCE_TYPES = {
    "explanation": "个性化讲解文档",
    "mindmap": "知识点思维导图",
    "quiz": "分层练习题",
    "code_case": "代码实操案例",
    "further_reading": "拓展阅读",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_citations(path: Path) -> List[Dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def citations_for_knowledge(
    knowledge: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not knowledge:
        return []
    terms = set()
    for item in knowledge:
        terms.update(str(tag).lower() for tag in item.get("tags", []))
        terms.update(token.lower() for token in re.findall(r"[A-Za-z_]+|[\u4e00-\u9fff]{2,}", item.get("title", "")))
    selected = []
    for citation in citations:
        topics = {str(topic).lower() for topic in citation.get("topics", [])}
        if terms & topics:
            selected.append(citation)
    tutorial = next((item for item in citations if item.get("id") == "PYDOC-TUTORIAL"), None)
    if tutorial and tutorial not in selected:
        selected.append(tutorial)
    enriched = []
    for citation in selected[:5]:
        topics = {str(topic).lower() for topic in citation.get("topics", [])}
        evidence = []
        for item in knowledge:
            item_tags = {str(tag).lower() for tag in item.get("tags", [])}
            if citation.get("id") == "PYDOC-TUTORIAL" or item_tags & topics:
                evidence.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "content": item.get("content"),
                })
        enriched.append({**citation, "knowledge_evidence": evidence[:3]})
    return enriched


def explanation_markdown(content: Dict[str, Any], citations: List[Dict[str, Any]]) -> str:
    examples = content.get("examples") or []
    errors = content.get("common_errors") or []
    references = "\n".join(f"- [{item['title']}]({item['url']})" for item in citations)
    example_text = "\n\n".join(f"```python\n{item}\n```" for item in examples)
    return f"""# {content.get('heading', '个性化讲解')}

## 目标
{content.get('objective', '')}

## 前置知识
{content.get('prerequisites', '')}

## 解释
{content.get('explanation', '')}

## 示例
{example_text}

## 常见错误
{chr(10).join(f'- {item}' for item in errors)}

## 总结
{content.get('summary', '')}

## 引用
{references}
""".strip()


def markdown_as_safe_html(markdown: str) -> str:
    code_blocks = []

    def protect_code(match):
        code_blocks.append(match.group(1))
        return f"@@CODE_BLOCK_{len(code_blocks) - 1}@@"

    protected = re.sub(r"```python\n(.*?)```", protect_code, markdown, flags=re.S)
    escaped = html.escape(protected)
    escaped = re.sub(r"^# (.+)$", r"<h1>\1</h1>", escaped, flags=re.M)
    escaped = re.sub(r"^## (.+)$", r"<h2>\1</h2>", escaped, flags=re.M)
    escaped = re.sub(r"^- (.+)$", r"<li>\1</li>", escaped, flags=re.M)
    escaped = escaped.replace("\n\n", "<br><br>")
    for index, code in enumerate(code_blocks):
        escaped = escaped.replace(
            f"@@CODE_BLOCK_{index}@@",
            f"<pre><code>{html.escape(code)}</code></pre>",
        )
    return escaped


class ResourceService:
    def __init__(
        self,
        storage: AppStorage,
        model_call: Callable[[str, str, Dict[str, Any]], Dict[str, Any]],
        reviewer: ReviewService,
    ):
        self.storage = storage
        self.model_call = model_call
        self.reviewer = reviewer

    def generate(
        self,
        user_id: str,
        request_text: str,
        profile_snapshot: Dict[str, Any],
        knowledge: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        course_id: str = "programming_python",
        workspace_id: str = "programming_python",
    ) -> Dict[str, Any]:
        if not knowledge or not citations:
            return {
                "resources": [],
                "review": {"status": "insufficient_evidence", "issues": ["知识库暂无可靠依据"]},
                "attempts": 0,
                "execution": {"mode": "failed", "error": "知识库暂无可靠依据"},
            }

        profile_basis = self._profile_basis(profile_snapshot)
        feedback = []
        last_execution = {"mode": "failed", "error": None}
        last_review = {"status": "insufficient_evidence", "issues": []}
        final_resources = []
        collected: Dict[str, Dict[str, Any]] = {}
        for attempt in range(3):
            requested_types = [item for item in RESOURCE_TYPES if item not in collected]
            raw_resources, last_execution, generation_issues = self._generate_round(
                user_id,
                request_text,
                profile_basis,
                knowledge[:3],
                citations[:4],
                feedback,
                requested_types,
            )
            collected.update({item["type"]: item for item in raw_resources})
            if generation_issues and len(collected) < len(RESOURCE_TYPES):
                feedback = generation_issues
                continue
            try:
                generated = self._normalize_resources(
                    list(collected.values()), profile_basis, citations, last_execution["mode"]
                )
            except ValueError as exc:
                error_text = str(exc)
                failed_types = [item for item in RESOURCE_TYPES if error_text.startswith(item)]
                if failed_types:
                    for resource_type in failed_types:
                        collected.pop(resource_type, None)
                else:
                    collected = {}
                feedback = [error_text]
                continue

            last_review = self.reviewer.review(user_id, generated, citations)
            final_resources = generated
            if last_review["status"] == "passed":
                break
            feedback = last_review.get("issues") or ["审核未通过，请修订"]
            collected = {}

        if not final_resources:
            if feedback:
                last_review = {"status": "insufficient_evidence", "issues": feedback, "claims": []}
            return {
                "resources": [],
                "review": last_review,
                "attempts": 3,
                "execution": last_execution,
            }

        for resource in final_resources:
            resource["review_status"] = last_review["status"]
            resource["claims"] = last_review.get("claims", [])
            resource["review"] = last_review
            self.storage.save_resource(resource, user_id, course_id, workspace_id)
        return {
            "resources": final_resources,
            "review": last_review,
            "attempts": min(3, attempt + 1),
            "execution": last_execution,
        }

    def _generate_round(
        self,
        user_id: str,
        request_text: str,
        profile_basis: List[Dict[str, Any]],
        knowledge: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        feedback: List[str],
        requested_types: List[str],
    ):
        if not requested_types:
            return [], {"mode": "failed", "error": None, "request_id": []}, []
        results: Dict[str, Dict[str, Any]] = {}

        def call(resource_type: str):
            if resource_type == "quiz":
                return self._generate_quiz_resource(
                    user_id, request_text, profile_basis, knowledge, citations, feedback
                )
            prompt = self._build_prompt(
                resource_type, request_text, profile_basis, knowledge, citations, feedback
            )
            return self.model_call("resource", prompt, {
                "user_id": user_id,
                "student_message": request_text,
                "profile": profile_basis,
                "knowledge": knowledge,
                "citations": citations,
                "resource_type": resource_type,
            })

        with ThreadPoolExecutor(max_workers=min(2, len(requested_types))) as executor:
            futures = {executor.submit(call, resource_type): resource_type for resource_type in requested_types}
            for future in as_completed(futures):
                resource_type = futures[future]
                try:
                    results[resource_type] = future.result()
                except Exception as exc:
                    results[resource_type] = {"content": "", "mode": "failed", "error": str(exc)}

        modes = [result.get("mode", "failed") for result in results.values()]
        errors = [str(result.get("error")) for result in results.values() if result.get("error")]
        execution = {
            "mode": "astron" if modes and all(mode == "astron" for mode in modes)
            else "spark_fallback" if any(mode == "spark_fallback" for mode in modes)
            else "failed",
            "error": "；".join(dict.fromkeys(errors)) or None,
            "request_id": [result.get("request_id") for result in results.values() if result.get("request_id")],
        }
        raw_resources = []
        issues = []
        for resource_type in requested_types:
            result = results.get(resource_type, {})
            parsed = safe_json_object(result.get("content", ""))
            raw = parsed.get("resource") if parsed else None
            if not raw and parsed and isinstance(parsed.get("resources"), list):
                raw = next((item for item in parsed["resources"] if item.get("type") == resource_type), None)
            if not isinstance(raw, dict):
                issues.append(f"{resource_type} 输出不是合法资源 JSON：{result.get('error') or '无法解析'}")
                continue
            raw["type"] = resource_type
            raw_resources.append(raw)
        return raw_resources, execution, issues

    def _generate_quiz_resource(
        self,
        user_id: str,
        request_text: str,
        profile_basis: List[Dict[str, Any]],
        knowledge: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        feedback: List[str],
    ) -> Dict[str, Any]:
        questions = []
        used_citation_ids = []
        modes = []
        errors = []
        request_ids = []
        levels = [("basic", "基础"), ("intermediate", "进阶"), ("challenge", "挑战")]
        for level_key, difficulty in levels:
            prompt = self._build_quiz_question_prompt(
                difficulty, request_text, profile_basis, knowledge, citations, feedback
            )
            result = self.model_call("resource", prompt, {
                "user_id": user_id,
                "student_message": request_text,
                "profile": profile_basis,
                "knowledge": knowledge,
                "citations": citations,
                "resource_type": f"quiz_{level_key}",
            })
            modes.append(result.get("mode", "failed"))
            if result.get("error"):
                errors.append(str(result["error"]))
            if result.get("request_id"):
                request_ids.append(result["request_id"])
            parsed = safe_json_object(result.get("content", ""))
            question = parsed.get("question") if parsed else None
            citation_ids = parsed.get("citation_ids") if parsed else None
            if not isinstance(question, dict) or not isinstance(citation_ids, list):
                return {
                    "content": "",
                    "mode": result.get("mode", "failed"),
                    "error": f"{difficulty}题输出无法解析",
                }
            question["difficulty"] = difficulty
            questions.append(question)
            used_citation_ids.extend(str(item) for item in citation_ids)
        resource = {
            "type": "quiz",
            "title": "个性化分层练习题",
            "citation_ids": list(dict.fromkeys(used_citation_ids)),
            "content": {"questions": questions},
        }
        return {
            "content": json.dumps({"resource": resource}, ensure_ascii=False),
            "mode": "astron" if modes and all(mode == "astron" for mode in modes)
            else "spark_fallback" if any(mode == "spark_fallback" for mode in modes)
            else "failed",
            "error": "；".join(dict.fromkeys(errors)) or None,
            "request_id": request_ids,
        }

    @staticmethod
    def _build_quiz_question_prompt(
        difficulty: str,
        request_text: str,
        profile_basis: List[Dict[str, Any]],
        knowledge: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        feedback: List[str],
    ) -> str:
        citation_ids = [item["id"] for item in citations]
        return f"""
你是 ResourceAgent。只生成 1 道 {difficulty} Python 练习题。
只输出合法 JSON：
{{"citation_ids":["PYDOC-ID"],"question":{{"question":"题目","answer":"答案","explanation":"解析","difficulty":"{difficulty}","knowledge_point":"知识点"}}}}
要求：题目不超过 160 个汉字，解析不超过 80 个汉字；答案必须完整；引用只能使用 {json.dumps(citation_ids, ensure_ascii=False)}。
学生请求：{request_text}
画像证据：{json.dumps(profile_basis, ensure_ascii=False)}
知识片段：{json.dumps(knowledge[:2], ensure_ascii=False)}
真实引用：{json.dumps(citations, ensure_ascii=False)}
审核意见：{json.dumps(feedback, ensure_ascii=False)}
""".strip()

    @staticmethod
    def _profile_basis(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        useful = {
            "current_course", "unmastered", "common_errors", "learning_goal",
            "daily_time", "learning_preference", "learning_state",
        }
        return [
            {
                "field": item["field"],
                "label": item.get("label", item["field"]),
                "value": item["value"],
                "evidence": item["evidence"],
            }
            for item in snapshot.get("records", [])
            if item.get("field") in useful and item.get("status") == "confirmed" and item.get("evidence")
        ]

    @staticmethod
    def _build_prompt(
        resource_type: str,
        request_text: str,
        profile_basis: List[Dict[str, Any]],
        knowledge: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        feedback: List[str],
    ) -> str:
        citation_ids = [item["id"] for item in citations]
        schemas = {
            "explanation": '{"type":"explanation","title":"...","citation_ids":["PYDOC-ID"],"content":{"heading":"...","objective":"...","prerequisites":"...","explanation":"...","examples":["合法Python代码"],"common_errors":["..."],"summary":"..."}}',
            "mindmap": '{"type":"mindmap","title":"...","citation_ids":["PYDOC-ID"],"content":{"mermaid":"mindmap\\n  root((主题))\\n    分支"}}',
            "quiz": '{"type":"quiz","title":"...","citation_ids":["PYDOC-ID"],"content":{"questions":[{"question":"...","answer":"...","explanation":"...","difficulty":"基础|进阶|挑战","knowledge_point":"..."}]}}',
            "code_case": '{"type":"code_case","title":"...","citation_ids":["PYDOC-ID"],"content":{"initial_code":"...","task":"...","tests":"合法Python断言代码","reference_answer":"合法Python代码"}}',
            "further_reading": '{"type":"further_reading","title":"...","citation_ids":["PYDOC-ID"],"content":{"items":[{"citation_id":"PYDOC-ID","reason":"为什么阅读"}]}}',
        }
        return f"""
你是 ResourceAgent。只生成一种个性化 Python 学习资源：{resource_type}。
只输出合法 JSON：{{"resource":{schemas[resource_type]}}}
规则：
- 不能生成视频、PPT 或不存在的链接。
- citation_ids 和阅读项只能使用：{json.dumps(citation_ids, ensure_ascii=False)}。
- 优先选择与当前知识点直接对应的具体章节来源，不要只引用教程目录页。
- 所有事实、题目答案和代码都必须与给定知识片段一致。
- 画像信息不足时不要编造偏好，只按当前问题生成通用难度。
- 结合画像证据调整篇幅、难度、例子和练习重点。
- quiz 只生成 3 道题，每道解析不超过 80 个汉字。
- mindmap 最多 18 个节点；Mermaid 字符串中的换行必须写成转义字符 \\n。
- explanation 不超过 800 个汉字；code_case 只做一个小任务；further_reading 最多 3 项。
学生请求：{request_text}
画像证据：{json.dumps(profile_basis, ensure_ascii=False)}
知识片段：{json.dumps(knowledge, ensure_ascii=False)}
真实引用：{json.dumps(citations, ensure_ascii=False)}
上一轮审核意见：{json.dumps(feedback, ensure_ascii=False)}
""".strip()

    @staticmethod
    def _normalize_resources(
        raw_resources: Any,
        profile_basis: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
        agent_mode: str,
    ) -> List[Dict[str, Any]]:
        if not isinstance(raw_resources, list):
            raise ValueError("resources 必须是数组")
        by_type = {item.get("type"): item for item in raw_resources if isinstance(item, dict)}
        missing = [resource_type for resource_type in RESOURCE_TYPES if resource_type not in by_type]
        if missing:
            raise ValueError("缺少资源类型：" + "、".join(missing))
        citation_map = {item["id"]: item for item in citations}
        normalized = []
        for resource_type in RESOURCE_TYPES:
            raw = by_type[resource_type]
            title = str(raw.get("title") or RESOURCE_TYPES[resource_type]).strip()
            content = raw.get("content")
            if not isinstance(content, dict):
                raise ValueError(f"{resource_type} content 不是对象")
            citation_ids = list(dict.fromkeys(str(item) for item in raw.get("citation_ids", [])))
            if not citation_ids or any(item not in citation_map for item in citation_ids):
                raise ValueError(f"{resource_type} 引用缺失或不存在")
            ResourceService._validate_content(resource_type, content, citation_map)
            used_citations = [citation_map[item] for item in citation_ids]
            if resource_type == "explanation":
                markdown = explanation_markdown(content, used_citations)
                content = {**content, "markdown": markdown, "html": markdown_as_safe_html(markdown)}
            if resource_type == "further_reading":
                content = {
                    "items": [
                        {
                            **item,
                            "title": citation_map[item["citation_id"]]["title"],
                            "url": citation_map[item["citation_id"]]["url"],
                        }
                        for item in content.get("items", [])
                    ]
                }
            normalized.append({
                "id": str(uuid.uuid4()),
                "type": resource_type,
                "title": title,
                "content": content,
                "profile_basis": profile_basis,
                "citations": used_citations,
                "citation_ids": citation_ids,
                "claims": [],
                "review_status": "insufficient_evidence",
                "review": {},
                "agent_mode": agent_mode,
                "created_at": utc_now(),
            })
        return normalized

    @staticmethod
    def _validate_content(resource_type: str, content: Dict[str, Any], citation_map: Dict[str, Any]) -> None:
        required = {
            "explanation": ["objective", "prerequisites", "explanation", "examples", "common_errors", "summary"],
            "mindmap": ["mermaid"],
            "quiz": ["questions"],
            "code_case": ["initial_code", "task", "tests", "reference_answer"],
            "further_reading": ["items"],
        }[resource_type]
        missing = [key for key in required if content.get(key) in (None, "", [])]
        if missing:
            raise ValueError(f"{resource_type} 缺少内容字段：{'、'.join(missing)}")
        if resource_type == "mindmap" and not re.match(r"^\s*(mindmap|graph|flowchart)\b", str(content["mermaid"])):
            raise ValueError("思维导图不是 Mermaid 源码")
        if resource_type == "quiz":
            for question in content["questions"]:
                if not all(question.get(key) for key in ("question", "answer", "explanation", "difficulty", "knowledge_point")):
                    raise ValueError("练习题字段不完整")
        if resource_type == "further_reading":
            if any(item.get("citation_id") not in citation_map for item in content["items"]):
                raise ValueError("拓展阅读包含未知来源")
