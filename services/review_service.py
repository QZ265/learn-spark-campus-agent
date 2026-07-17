import ast
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from .profile_service import safe_json_object
from .safety_service import contains_secret


REVIEW_STATUSES = {"passed", "needs_revision", "rejected", "insufficient_evidence"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_MODULES = {"os", "subprocess", "socket", "shutil", "requests"}


def extract_code(resource: Dict[str, Any]) -> List[str]:
    content = resource.get("content") or {}
    snippets = []
    if resource.get("type") == "code_case":
        for key in ("initial_code", "tests", "reference_answer"):
            value = content.get(key)
            if value:
                snippets.append(str(value))
    if resource.get("type") == "explanation":
        examples = content.get("examples") or []
        snippets.extend(str(item) for item in examples if item)
        answer = str(content.get("answer") or "")
        snippets.extend(re.findall(r"```(?:python)?\s*(.*?)```", answer, re.S | re.I))
    return snippets


def validate_python(code: str) -> Optional[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Python 代码语法错误：第 {exc.lineno} 行 {exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name.split(".")[0] for alias in node.names]
            if any(name in FORBIDDEN_MODULES for name in names):
                return "代码包含不允许的系统或网络模块"
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name in FORBIDDEN_CALLS:
                return f"代码调用了不允许的函数：{name}"
    return None


class ReviewService:
    def __init__(self, model_call: Callable[[str, str, Dict[str, Any]], Dict[str, Any]]):
        self.model_call = model_call

    def review(
        self,
        user_id: str,
        resources: List[Dict[str, Any]],
        citations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        citation_ids = {item["id"] for item in citations}
        local_issues = []
        for resource in resources:
            used_ids = resource.get("citation_ids") or []
            unknown = [item for item in used_ids if item not in citation_ids]
            if unknown:
                local_issues.append(f"{resource.get('title')} 使用不存在的引用：{', '.join(unknown)}")
            if not used_ids:
                local_issues.append(f"{resource.get('title')} 没有绑定引用")
            serialized = json.dumps(resource.get("content", {}), ensure_ascii=False)
            if contains_secret(serialized):
                local_issues.append(f"{resource.get('title')} 疑似包含密钥")
            for code in extract_code(resource):
                code_error = validate_python(code)
                if code_error:
                    local_issues.append(f"{resource.get('title')}：{code_error}")

        if not citations:
            return {
                "status": "insufficient_evidence",
                "issues": ["知识库暂无可靠依据"],
                "claims": [],
                "mode": "local_validation",
            }
        if local_issues:
            return {
                "status": "needs_revision",
                "issues": local_issues,
                "claims": [],
                "mode": "local_validation",
            }

        results = []
        with ThreadPoolExecutor(max_workers=min(2, len(resources))) as executor:
            futures = {
                executor.submit(self._review_one, user_id, resource, citations, citation_ids): resource
                for resource in resources
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append({
                        "status": "insufficient_evidence",
                        "issues": [str(exc)],
                        "claims": [],
                        "mode": "failed",
                    })

        priority = {"passed": 0, "insufficient_evidence": 1, "needs_revision": 2, "rejected": 3}
        status = max((item["status"] for item in results), key=lambda item: priority[item])
        return {
            "status": status,
            "issues": list(dict.fromkeys(
                str(issue) for item in results for issue in item.get("issues", [])
            )),
            "claims": [claim for item in results for claim in item.get("claims", [])],
            "mode": "astron" if results and all(item.get("mode") == "astron" for item in results)
            else "spark_fallback" if any(item.get("mode") == "spark_fallback" for item in results)
            else "failed",
            "request_id": [item.get("request_id") for item in results if item.get("request_id")],
        }

    def _review_one(
        self,
        user_id: str,
        resource: Dict[str, Any],
        citations: List[Dict[str, Any]],
        citation_ids: set,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt([resource], citations)
        last_error = None
        for attempt in range(2):
            result = self.model_call("review", prompt, {
                "user_id": user_id,
                "resource": resource,
                "citations": citations,
            })
            last_error = result.get("error")
            parsed = safe_json_object(result.get("content", ""))
            if not parsed:
                prompt += "\n上次输出无法解析。请只输出合法 JSON。"
                continue
            status = parsed.get("status")
            claims = parsed.get("claims") if isinstance(parsed.get("claims"), list) else []
            issues = parsed.get("issues") if isinstance(parsed.get("issues"), list) else []
            if status not in REVIEW_STATUSES:
                continue
            invalid_claim_ids = [
                citation_id
                for claim in claims if isinstance(claim, dict)
                for citation_id in claim.get("citation_ids", [])
                if citation_id not in citation_ids
            ]
            if invalid_claim_ids:
                return {
                    "status": "needs_revision",
                    "issues": [f"{resource.get('title')} 的审核结果引用了不存在的来源"],
                    "claims": claims,
                    "mode": result.get("mode", "failed"),
                }
            return {
                "status": status,
                "issues": [f"{resource.get('title')}：{item}" for item in issues],
                "claims": claims,
                "mode": result.get("mode", "failed"),
                "request_id": result.get("request_id"),
            }
        return {
            "status": "insufficient_evidence",
            "issues": [f"{resource.get('title')}：{last_error or 'ReviewAgent 返回无法解析'}"],
            "claims": [],
            "mode": "failed",
        }

    @staticmethod
    def _build_prompt(resources: List[Dict[str, Any]], citations: List[Dict[str, Any]]) -> str:
        return f"""
你是 ReviewAgent。请审核教学资源是否被给定引用支持、是否编造事实、代码是否正确。
只输出 JSON：
{{"status":"passed|needs_revision|rejected|insufficient_evidence","issues":[],"claims":[{{"claim":"事实陈述","citation_ids":["PYDOC-ID"],"support_status":"supported|unsupported|uncertain"}}]}}
规则：
- 引用 ID 必须来自给定引用，不能新增来源。
- 有关键事实无法由引用或知识片段支持时不得 passed。
- 代码语义错误、答案与题目冲突时 needs_revision；危险或明显编造时 rejected。
- 最多列出 3 条关键 claims，每条简短明确。
资源：{json.dumps(resources, ensure_ascii=False)}
引用：{json.dumps(citations, ensure_ascii=False)}
""".strip()
