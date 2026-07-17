import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


LOGGER = logging.getLogger("pylearn.astron")


@dataclass
class AstronResult:
    ok: bool
    content: str = ""
    mode: str = "failed"
    error: Optional[str] = None
    request_id: Optional[str] = None
    progress: float = 0.0
    raw: Optional[Dict[str, Any]] = None


class AstronAgentClient:
    DEFAULT_ENDPOINT = "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        retries: Optional[int] = None,
    ):
        key = api_key if api_key is not None else os.getenv("ASTRON_API_KEY", "")
        secret = os.getenv("ASTRON_API_SECRET", "").strip()
        key = key.strip()
        if key and secret and ":" not in key:
            key = f"{key}:{secret}"
        self.api_key = key
        self.agent_id = (agent_id if agent_id is not None else os.getenv("ASTRON_AGENT_ID", "")).strip()
        self.endpoint = (endpoint or os.getenv("ASTRON_BASE_URL", self.DEFAULT_ENDPOINT)).strip()
        self.timeout_seconds = timeout_seconds or int(os.getenv("ASTRON_TIMEOUT_SECONDS", "90"))
        self.retries = retries if retries is not None else int(os.getenv("ASTRON_RETRIES", "2"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.agent_id)

    def invoke(self, task: str, user_id: str, payload: Dict[str, Any]) -> AstronResult:
        if not self.configured:
            return AstronResult(ok=False, error="讯飞星辰未配置", mode="failed")

        task_payload = {"task": task, **payload}
        parameters = {
            "AGENT_USER_INPUT": json.dumps(task_payload, ensure_ascii=False),
            "TASK": task,
            "STUDENT_MESSAGE": str(payload.get("student_message", "")),
            "PROFILE_JSON": json.dumps(payload.get("profile", {}), ensure_ascii=False),
            "KNOWLEDGE_JSON": json.dumps(payload.get("knowledge", []), ensure_ascii=False),
            "RESOURCE_JSON": json.dumps(payload.get("resource", {}), ensure_ascii=False),
            "RESOURCE_TYPE": str(payload.get("resource_type", "")),
            "CITATIONS_JSON": json.dumps(payload.get("citations", []), ensure_ascii=False),
        }
        body = {
            "flow_id": self.agent_id,
            "uid": user_id,
            "parameters": parameters,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = "星辰调用失败"
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(
                    self.endpoint,
                    headers=headers,
                    json=body,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("code") not in (None, 0):
                    last_error = f"{data.get('code')}: {data.get('message', '星辰工作流错误')}"
                    raise ValueError(last_error)
                choice = (data.get("choices") or [{}])[0]
                content = (choice.get("delta") or {}).get("content") or ""
                if not content:
                    last_error = "星辰工作流未返回内容"
                    raise ValueError(last_error)
                workflow_step = data.get("workflow_step") or {}
                LOGGER.info(
                    "Astron task=%s request_id=%s attempt=%s progress=%s",
                    task,
                    data.get("id"),
                    attempt + 1,
                    workflow_step.get("progress"),
                )
                return AstronResult(
                    ok=True,
                    content=str(content),
                    mode="astron",
                    request_id=data.get("id"),
                    progress=float(workflow_step.get("progress") or 1.0),
                    raw=data,
                )
            except Exception as exc:
                last_error = str(exc)
                LOGGER.warning("Astron task=%s attempt=%s failed: %s", task, attempt + 1, last_error)
                if attempt < self.retries:
                    time.sleep(min(0.5 * (2 ** attempt), 2.0))
        return AstronResult(ok=False, error=last_error, mode="failed")
