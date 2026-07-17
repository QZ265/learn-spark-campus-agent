import difflib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .storage import AppStorage


PROFILE_FIELDS = {
    "identity": "当前身份",
    "current_course": "当前课程/章节",
    "mastered": "已掌握内容",
    "unmastered": "未掌握内容",
    "common_errors": "常见错误",
    "learning_goal": "学习目标",
    "daily_time": "可投入时间",
    "learning_preference": "学习偏好",
    "learning_state": "当前学习状态",
}
LIST_FIELDS = {"mastered", "unmastered", "common_errors", "learning_preference"}
SOURCE_PRIORITY = {"behavior": 1, "conversation": 2, "practice": 3, "user_correction": 4}
MISSING_VALUES = {
    "current_course": "尚未确认",
    "mastered": "等待学习记录",
    "unmastered": "等待学习记录",
    "common_errors": "等待学习记录",
    "learning_state": "等待学习记录",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.I).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        cleaned = match.group(0)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        try:
            # Some model endpoints emit literal newlines inside Mermaid JSON strings.
            value = json.loads(cleaned, strict=False)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


class ProfileService:
    def __init__(
        self,
        storage: AppStorage,
        model_call: Callable[[str, str, Dict[str, Any]], Dict[str, Any]],
    ):
        self.storage = storage
        self.model_call = model_call

    def snapshot(self, user_id: str, course_id: str = "programming_python") -> Dict[str, Any]:
        stored = self.storage.get_profile_records(user_id, course_id)
        records = []
        missing_fields = []
        for field, label in PROFILE_FIELDS.items():
            if field in stored:
                record = dict(stored[field])
            else:
                missing_fields.append(field)
                record = {
                    "field": field,
                    "value": MISSING_VALUES.get(field, "暂无信息"),
                    "evidence": "",
                    "source_type": "none",
                    "confidence": 0.0,
                    "updated_at": None,
                    "status": "insufficient",
                }
            record["label"] = label
            records.append(record)
        return {
            "records": records,
            "record_map": {item["field"]: item for item in records},
            "missing_fields": missing_fields,
            "changes": self.storage.get_profile_changes(user_id, course_id=course_id),
            "course_id": course_id,
        }

    @staticmethod
    def values(snapshot: Dict[str, Any]) -> Dict[str, Any]:
        return {
            item["field"]: item["value"]
            for item in snapshot.get("records", [])
            if item.get("status") != "insufficient"
        }

    def extract_and_update(
        self, user_id: str, message: str, course_id: str = "programming_python"
    ) -> Dict[str, Any]:
        before = self.snapshot(user_id, course_id)
        prompt = self._build_prompt(message, before)
        execution = {"mode": "failed", "error": None, "request_id": None}
        parsed = None
        last_error = None
        for attempt in range(2):
            call_prompt = prompt if attempt == 0 else (
                prompt
                + "\n上一次输出无法解析或缺少直接证据。请只输出合法JSON，updates必须是数组。"
            )
            result = self.model_call("profile", call_prompt, {
                "user_id": user_id,
                "course_id": course_id,
                "student_message": message,
                "profile": before["record_map"],
            })
            execution = {
                "mode": result.get("mode", "failed"),
                "error": result.get("error"),
                "request_id": result.get("request_id"),
            }
            last_error = result.get("error")
            parsed = safe_json_object(result.get("content", ""))
            if parsed and isinstance(parsed.get("updates", []), list):
                break
        if not parsed:
            execution["error"] = last_error or "画像JSON解析失败"
            return {"profile": before, "applied": [], "rejected": [], "execution": execution}

        applied = []
        rejected = []
        for candidate in parsed.get("updates", []):
            record, error = self._normalize_candidate(candidate, message)
            if error:
                rejected.append({"candidate": candidate, "reason": error})
                continue
            old = before["record_map"].get(record["field"])
            reason = "new_evidence"
            if old and old.get("status") != "insufficient" and old.get("value") != record["value"]:
                if record["source_type"] == "user_correction":
                    reason = "user_correction"
                else:
                    record["status"] = "conflict"
                    reason = "conflicting_evidence"
            elif old and SOURCE_PRIORITY.get(old.get("source_type"), 0) > SOURCE_PRIORITY[record["source_type"]]:
                rejected.append({"candidate": candidate, "reason": "新证据优先级低于当前记录"})
                continue
            self.storage.save_profile_record(user_id, record, reason, course_id)
            applied.append(record)

        return {
            "profile": self.snapshot(user_id, course_id),
            "applied": applied,
            "rejected": rejected,
            "execution": execution,
        }

    @staticmethod
    def _build_prompt(message: str, snapshot: Dict[str, Any]) -> str:
        return f"""
你是 ProfileAgent，只从本轮学生原话中抽取有直接证据的动态学习画像。
输出严格JSON，不要Markdown：
{{"updates":[{{"field":"daily_time","value":"每天30分钟","evidence":"每天半小时","source_type":"conversation","confidence":0.95}}]}}

允许字段：{json.dumps(list(PROFILE_FIELDS.keys()), ensure_ascii=False)}
数组字段：{json.dumps(sorted(LIST_FIELDS), ensure_ascii=False)}
source_type只能是 conversation 或 user_correction。学生明确纠正旧信息时使用 user_correction。
evidence必须直接摘录本轮原话，不能推测人格、能力、主动性或认知风格。
没有证据的字段不要输出。仅询问知识点不代表学生身份、偏好、掌握程度或人格。
当前画像：{json.dumps(snapshot.get('record_map', {}), ensure_ascii=False)}
本轮原话：{message}
""".strip()

    @staticmethod
    def _normalize_candidate(candidate: Any, message: str):
        if not isinstance(candidate, dict):
            return None, "画像项不是对象"
        field = str(candidate.get("field", "")).strip()
        if field not in PROFILE_FIELDS:
            return None, "字段不在允许范围"
        evidence = str(candidate.get("evidence", "")).strip()
        if not evidence:
            return None, "缺少证据"
        normalized_evidence = re.sub(r"[\s，。！？、,.!?：:；;\"'“”‘’]", "", evidence)
        normalized_message = re.sub(r"[\s，。！？、,.!?：:；;\"'“”‘’]", "", message)
        if normalized_evidence not in normalized_message:
            ratio = difflib.SequenceMatcher(None, normalized_evidence, normalized_message).ratio()
            if ratio < 0.32:
                return None, "证据不是本轮原话"
        value = candidate.get("value")
        if field in LIST_FIELDS:
            if isinstance(value, str):
                value = [item.strip() for item in re.split(r"[、,，;；\n]+", value) if item.strip()]
            if not isinstance(value, list) or not value:
                return None, "数组字段值为空"
            value = [str(item).strip() for item in value if str(item).strip()]
        elif value in (None, "", [], {}):
            return None, "字段值为空"
        else:
            value = str(value).strip()
        source_type = str(candidate.get("source_type", "conversation")).strip()
        if source_type not in {"conversation", "user_correction"}:
            source_type = "conversation"
        try:
            confidence = max(0.0, min(1.0, float(candidate.get("confidence", 0.7))))
        except (TypeError, ValueError):
            confidence = 0.7
        return {
            "field": field,
            "value": value,
            "evidence": evidence[:200],
            "source_type": source_type,
            "confidence": confidence,
            "updated_at": utc_now(),
            "status": "confirmed",
        }, None

    def record_practice_updates(
        self, user_id: str, updates: List[Dict[str, Any]], course_id: str = "programming_python"
    ) -> Dict[str, Any]:
        current = self.storage.get_profile_records(user_id, course_id)
        for update in updates:
            field = update.get("field")
            evidence = str(update.get("evidence", "")).strip()
            if field not in PROFILE_FIELDS or not evidence:
                continue
            value = update.get("value")
            if field in LIST_FIELDS and not isinstance(value, list):
                value = [str(value)]
            if field in LIST_FIELDS and current.get(field):
                previous = current[field].get("value") or []
                if not isinstance(previous, list):
                    previous = [str(previous)]
                value = list(dict.fromkeys([*previous, *(value or [])]))[-12:]
            record = {
                "field": field,
                "value": value,
                "evidence": evidence[:200],
                "source_type": "practice",
                "confidence": max(0.0, min(1.0, float(update.get("confidence", 0.9)))),
                "updated_at": utc_now(),
                "status": "confirmed",
            }
            self.storage.save_profile_record(user_id, record, "practice_evidence", course_id)
        return self.snapshot(user_id, course_id)

    def apply_user_correction(
        self,
        user_id: str,
        field: str,
        value: Any,
        evidence: str,
        course_id: str = "programming_python",
    ) -> Dict[str, Any]:
        if field not in PROFILE_FIELDS:
            return {"ok": False, "error": "不支持的画像字段"}
        if value in (None, "", [], {}):
            return {"ok": False, "error": "画像值不能为空"}
        if field in LIST_FIELDS and not isinstance(value, list):
            value = [item.strip() for item in re.split(r"[、,，;；\n]+", str(value)) if item.strip()]
        record = {
            "field": field,
            "value": value,
            "evidence": str(evidence).strip()[:200] or "用户手动修改",
            "source_type": "user_correction",
            "confidence": 1.0,
            "updated_at": utc_now(),
            "status": "confirmed",
        }
        self.storage.save_profile_record(user_id, record, "user_correction", course_id)
        return {"ok": True, "profile": self.snapshot(user_id, course_id)}
