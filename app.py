import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import time
import uuid
from email.utils import formatdate
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.astron_agent_client import AstronAgentClient
from services.profile_service import ProfileService
from services.resource_service import (
    ResourceService,
    citations_for_knowledge,
    load_citations,
    markdown_as_safe_html,
)
from services.review_service import ReviewService
from services.safety_service import check_input
from services.lightrag.client import LightRAGClient
from services.lightrag.course_registry import (
    custom_workspace,
    get_course,
    list_courses as registered_courses,
    list_domain_agents,
)
from services.lightrag.indexing_service import MAX_UPLOAD_BYTES, IndexingService, safe_filename
from services.lightrag.retrieval_service import RetrievalService
from services.storage import AppStorage

BASE_DIR = Path(__file__).resolve().parent
# 先读取隐藏的 .env，再读取给零基础用户准备的可见配置文件 config_keys.env。
# config_keys.env 优先级更高，方便 Windows 直接双击编辑。
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / "config_keys.env", override=True)
KB_PATH = BASE_DIR / "data" / "knowledge_base.json"
CITATION_PATH = BASE_DIR / "data" / "citations.json"
DB_PATH = Path(os.getenv("APP_DB_PATH", str(BASE_DIR / "data" / "app.db")))
SPARK_API_PASSWORD = os.getenv("SPARK_API_PASSWORD", "").strip()
SPARK_MODEL = os.getenv("SPARK_MODEL", "spark-x").strip() or "spark-x"
SPARK_BASE_URL = os.getenv(
    "SPARK_BASE_URL",
    "https://spark-api-open.xf-yun.com/x2/chat/completions",
).strip()
SPARK_TIMEOUT_SECONDS = int(os.getenv("SPARK_TIMEOUT_SECONDS", "75"))
SPARK_RETRIES = int(os.getenv("SPARK_RETRIES", "1"))
XF_ASR_APP_ID = os.getenv("XF_ASR_APP_ID", "").strip()
XF_ASR_API_KEY = os.getenv("XF_ASR_API_KEY", "").strip()
XF_ASR_API_SECRET = os.getenv("XF_ASR_API_SECRET", "").strip()
XF_ASR_ENDPOINT = os.getenv("XF_ASR_ENDPOINT", "wss://iat.xf-yun.com/v1").strip()
XF_ASR_LANGUAGE = os.getenv("XF_ASR_LANGUAGE", "zh_cn").strip() or "zh_cn"
XF_ASR_ACCENT = os.getenv("XF_ASR_ACCENT", "mandarin").strip() or "mandarin"
XF_ASR_TIMEOUT_SECONDS = int(os.getenv("XF_ASR_TIMEOUT_SECONDS", "35"))

app = FastAPI(title="PyLearnSpark A3 多智能体系统", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

with KB_PATH.open("r", encoding="utf-8") as f:
    KNOWLEDGE_BASE = json.load(f)
CITATIONS = load_citations(CITATION_PATH)

CHAT_HISTORY: Dict[str, List[Dict[str, str]]] = {}
STORAGE = AppStorage(DB_PATH)
STORAGE.register_courses(registered_courses())
ASTRON_CLIENT = AstronAgentClient()


class ChatRequest(BaseModel):
    user_id: str = "demo_student"
    message: str
    use_spark: bool = False
    history: Optional[List[Dict[str, str]]] = None
    course_id: str = "programming_python"
    assistant_id: Optional[str] = None


class EvaluateRequest(BaseModel):
    user_id: str = "demo_student"
    answer: str
    question: Optional[str] = None
    course_id: str = "programming_python"


class ProfileRequest(BaseModel):
    user_id: str = "demo_student"
    course_id: str = "programming_python"


class ProfileUpdateRequest(BaseModel):
    user_id: str = "demo_student"
    field: str
    value: Any
    evidence: Optional[str] = None
    course_id: str = "programming_python"


class ResourceGenerateRequest(BaseModel):
    user_id: str = "demo_student"
    request: str
    course_id: str = "programming_python"


class CustomAssistantCreateRequest(BaseModel):
    user_id: str = "demo_student"
    name: str
    course_name: str
    domain: str
    learning_goal: str = ""
    answer_preference: str = ""


class AssistantQueryRequest(BaseModel):
    user_id: str = "demo_student"
    assistant_id: str = ""
    course_id: str
    message: str
    allow_cross_course: bool = False
    course_ids: Optional[List[str]] = None


def tokenize(text: str) -> List[str]:
    text = text.lower()
    words = re.findall(r"[a-zA-Z_]+|\d+", text)
    phrases = [
        "零基础", "条件判断", "输入输出", "视频", "图文", "练习题", "学习路径",
        "变量", "数据类型", "函数", "循环", "列表", "成绩", "成绩判断", "文件", "文件操作",
        "异常", "异常处理", "字典", "项目", "类型转换", "格式化输出",
        "学习计划", "错题本", "调试", "实验报告",
    ]
    for p in phrases:
        if p in text:
            words.append(p)
    return words


def retrieve_knowledge(query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    q_tokens = tokenize(query)
    scored = []
    for item in KNOWLEDGE_BASE:
        hay = " ".join([
            item.get("title", ""),
            item.get("chapter", ""),
            item.get("content", ""),
            " ".join(item.get("tags", [])),
            " ".join(item.get("common_mistakes", [])),
        ]).lower()
        score = 0
        for tok in q_tokens:
            if tok and tok.lower() in hay:
                score += 5 if len(tok) > 1 else 1
        if "if" in query.lower() and "if" in item.get("tags", []):
            score += 40
        if "条件" in query and "条件判断" in item.get("tags", []):
            score += 35
        if "变量" in query and "变量" in item.get("tags", []):
            score += 45
        if "数据类型" in query and "数据类型" in item.get("tags", []):
            score += 35
        if any(x in query for x in ["输入", "输出", "input", "print"]) and any(x in item.get("tags", []) for x in ["输入", "输出", "input", "print"]):
            score += 35
        if "循环" in query and "循环" in item.get("tags", []):
            score += 35
        if "函数" in query and "函数" in item.get("tags", []):
            score += 35
        if "文件" in query and "文件" in item.get("tags", []):
            score += 35
        if "成绩" in query and "成绩" in item.get("tags", []):
            score += 45
        if "项目" in query and "项目" in item.get("tags", []):
            score += 25
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [item for score, item in scored if score > 0][:top_k]
    return hits


def call_spark_messages(
    messages: List[Dict[str, str]],
    temperature: float = 0.4,
    max_tokens: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    if not SPARK_API_PASSWORD:
        return None, None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SPARK_API_PASSWORD}",
    }
    payload: Dict[str, Any] = {
        "model": SPARK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    last_error = None
    for attempt in range(SPARK_RETRIES + 1):
        try:
            resp = requests.post(SPARK_BASE_URL, headers=headers, json=payload, timeout=SPARK_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") not in (None, 0):
                raise ValueError(f"{data.get('code')}: {data.get('message') or data}")
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            delta = choice.get("delta") or {}
            content = message.get("content") or delta.get("content")
            if isinstance(content, list):
                content = "".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in content)
            if not content:
                raise ValueError(f"星火返回内容为空：{data}")
            return str(content), None
        except Exception as exc:
            last_error = str(exc)
            if attempt < SPARK_RETRIES:
                time.sleep(0.5 * (attempt + 1))
    return None, last_error


def invoke_agent_task(task: str, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Call the published Xingchen workflow first, then make fallback explicit."""
    user_id = str(context.get("user_id") or "demo_student")
    astron_result = ASTRON_CLIENT.invoke(task, user_id, {**context, "prompt": prompt})
    if astron_result.ok:
        return {
            "content": astron_result.content,
            "mode": "astron",
            "error": None,
            "request_id": astron_result.request_id,
        }

    content, spark_error = call_spark_messages(
        [
            {
                "role": "system",
                "content": (
                    f"你正在执行 {task} 任务。严格遵守输出格式；"
                    "不得编造学生信息、来源、链接或审核结论。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1 if task in {"profile", "review"} else 0.35,
        max_tokens=1800 if task == "resource" else 2200,
    )
    if content:
        return {
            "content": content,
            "mode": "spark_fallback",
            "error": astron_result.error,
            "request_id": None,
        }
    errors = [error for error in (astron_result.error, spark_error) if error]
    return {
        "content": "",
        "mode": "failed",
        "error": "；".join(errors) or "星辰和 Spark 均未配置",
        "request_id": None,
    }


PROFILE_SERVICE = ProfileService(STORAGE, invoke_agent_task)
REVIEW_SERVICE = ReviewService(invoke_agent_task)
RESOURCE_SERVICE = ResourceService(STORAGE, invoke_agent_task, REVIEW_SERVICE)


def grounded_model_call(task: str, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
    content, error = call_spark_messages(
        [
            {"role": "system", "content": "你是有引用约束的课程知识库助手，不得编造来源。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.15,
        max_tokens=1600,
    )
    return {
        "content": content or "",
        "mode": "spark_grounded" if content else "failed",
        "error": error,
    }


def resolve_assistant_scope(user_id: str, course_id: str, assistant_id: str = "") -> Dict[str, Any]:
    if assistant_id and not assistant_id.startswith("domain_") and assistant_id != "public":
        assistant = STORAGE.get_custom_assistant(assistant_id, user_id)
        if not assistant:
            raise HTTPException(status_code=404, detail="课程助手不存在或不属于当前用户")
        if course_id and course_id != assistant["course_id"]:
            raise HTTPException(status_code=400, detail="assistant_id 与 course_id 不匹配")
        return {
            "course_id": assistant["course_id"],
            "workspace": assistant["workspace"],
            "assistant": assistant,
        }
    course = get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在，请先选择有效 course_id")
    return {"course_id": course.course_id, "workspace": course.workspace, "assistant": None}


def chat_history_key(user_id: str, course_id: str) -> str:
    return f"{user_id}::{course_id}"


LIGHTRAG_CLIENT = LightRAGClient()
INDEXING_SERVICE = IndexingService(STORAGE, LIGHTRAG_CLIENT, BASE_DIR)
RETRIEVAL_SERVICE = RetrievalService(
    STORAGE, LIGHTRAG_CLIENT, grounded_model_call, reviewer=REVIEW_SERVICE
)


@app.on_event("startup")
def resume_indexing_jobs() -> None:
    if LIGHTRAG_CLIENT.available:
        INDEXING_SERVICE.resume_pending(retry_failed=False)


def asr_configured() -> bool:
    return bool(XF_ASR_APP_ID and XF_ASR_API_KEY and XF_ASR_API_SECRET)


def build_xfyun_asr_url() -> str:
    parsed = urlparse(XF_ASR_ENDPOINT)
    host = parsed.netloc
    path = parsed.path or "/v1"
    date = formatdate(timeval=None, localtime=False, usegmt=True)
    signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
    signature_sha = hmac.new(
        XF_ASR_API_SECRET.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")
    authorization_origin = (
        f'api_key="{XF_ASR_API_KEY}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
    return f"{XF_ASR_ENDPOINT}?{urlencode({'authorization': authorization, 'date': date, 'host': host})}"


def build_asr_frame(audio: bytes, status: int, seq: int) -> Dict[str, Any]:
    parameter = {
        "iat": {
            "domain": "slm",
            "language": XF_ASR_LANGUAGE,
            "accent": XF_ASR_ACCENT,
            "eos": 6000,
            "result": {"encoding": "utf8", "compress": "raw", "format": "json"},
        }
    }
    ln = os.getenv("XF_ASR_LN", "").strip()
    if ln and XF_ASR_LANGUAGE == "mul_cn":
        parameter["iat"]["ln"] = ln
    frame: Dict[str, Any] = {
        "header": {"app_id": XF_ASR_APP_ID, "status": status},
        "payload": {
            "audio": {
                "encoding": "raw",
                "sample_rate": 16000,
                "channels": 1,
                "bit_depth": 16,
                "seq": seq,
                "status": status,
                "audio": base64.b64encode(audio).decode("utf-8"),
            }
        },
    }
    if status == 0:
        frame["parameter"] = parameter
    return frame


def words_from_asr_result(result: Dict[str, Any]) -> str:
    words: List[str] = []
    for segment in result.get("ws") or []:
        candidates = segment.get("cw") or []
        if candidates:
            words.append(str(candidates[0].get("w") or ""))
    return "".join(words)


def extract_asr_text(data: Dict[str, Any]) -> Tuple[Optional[int], str, bool]:
    payload = data.get("payload") or {}
    result = payload.get("result") or {}
    text64 = result.get("text")
    final = (data.get("header") or {}).get("status") == 2 or result.get("status") == 2
    if text64:
        decoded = base64.b64decode(text64).decode("utf-8")
        obj = json.loads(decoded)
        if isinstance(obj, dict):
            if obj.get("ret") not in (None, 0):
                raise ValueError(obj.get("errmsg") or f"语音识别返回异常：{obj.get('ret')}")
            return obj.get("sn"), words_from_asr_result(obj), final or bool(obj.get("ls"))

    # 兼容讯飞旧版听写接口的直接 JSON 结果格式。
    legacy_result = (data.get("data") or {}).get("result") or {}
    if legacy_result.get("ws"):
        return legacy_result.get("sn"), words_from_asr_result(legacy_result), data.get("data", {}).get("status") == 2
    return None, "", final


async def recognize_pcm_with_xfyun(pcm: bytes) -> str:
    import websockets

    ws_url = build_xfyun_asr_url()
    chunk_size = 1280
    chunks = [pcm[i : i + chunk_size] for i in range(0, len(pcm), chunk_size)] or [b""]
    results: Dict[int, str] = {}
    unnamed_results: List[str] = []

    try:
        async with websockets.connect(
            ws_url,
            open_timeout=XF_ASR_TIMEOUT_SECONDS,
            ping_interval=None,
            max_size=8_000_000,
        ) as websocket:
            for index, chunk in enumerate(chunks):
                if index == 0:
                    status = 0
                elif index == len(chunks) - 1:
                    status = 2
                else:
                    status = 1
                await websocket.send(json.dumps(build_asr_frame(chunk, status, index), ensure_ascii=False))
                await asyncio.sleep(0.04)
            if len(chunks) == 1:
                await websocket.send(json.dumps(build_asr_frame(b"", 2, 1), ensure_ascii=False))

            while True:
                raw = await asyncio.wait_for(websocket.recv(), timeout=XF_ASR_TIMEOUT_SECONDS)
                data = json.loads(raw)
                header = data.get("header") or {}
                code = header.get("code")
                if code not in (None, 0):
                    raise ValueError(header.get("message") or f"语音识别服务返回错误：{code}")
                sn, text, final = extract_asr_text(data)
                if text:
                    if isinstance(sn, int):
                        results[sn] = text
                    else:
                        unnamed_results.append(text)
                if final:
                    break
    except asyncio.TimeoutError as exc:
        raise ValueError("语音识别超时，请稍后重试。") from exc
    except Exception as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        body = ""
        if response and getattr(response, "body", None):
            body = bytes(response.body[:300]).decode("utf-8", errors="ignore")
        if status_code == 401 or "HMAC signature" in body:
            raise ValueError(
                "讯飞语音识别鉴权失败：当前 config_keys.env 中的 APIKey/APISecret 与这个语音识别服务不匹配。"
                "请在讯飞控制台进入“大模型多语种语音识别”服务页，重新复制 WebSocket 鉴权信息。"
            ) from exc
        raise

    ordered = "".join(results[key] for key in sorted(results))
    return (ordered + "".join(unnamed_results)).strip()


def infer_topic(hits: List[Dict[str, Any]]) -> str:
    return hits[0]["title"] if hits else "Python基础"


def build_learning_plan(profile: Dict[str, Any], message: str, knowledge_hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    topic = infer_topic(knowledge_hits)
    resources = [
        "专业课程讲解文档",
        "知识点思维导图",
        "分层练习题库",
        "拓展阅读材料",
        "代码实操案例/实践项目材料",
    ]
    if "学习路径" in message or "路线" in message or "怎么学" in message:
        focus = "先规划学习顺序，再推送对应资源。"
    elif any(x in message for x in ["错", "报错", "不会", "看不懂"]):
        focus = "先定位知识短板，再给补救资源和最小实操。"
    else:
        focus = "先降低理解门槛，再用代码实验和练习题巩固。"

    learning_path = [
        {
            "step": "第1步",
            "title": f"理解{topic}的核心概念",
            "resource": "专业课程讲解文档 + 知识点思维导图",
            "time": "10-15分钟",
            "check": "能用自己的话解释这个知识点",
        },
        {
            "step": "第2步",
            "title": "照着运行最小代码",
            "resource": "代码实操案例",
            "time": "10分钟",
            "check": "能成功运行并改动1个参数",
        },
        {
            "step": "第3步",
            "title": "完成基础题和进阶题",
            "resource": "分层练习题库",
            "time": "15-25分钟",
            "check": "基础题正确，进阶题能说出思路",
        },
        {
            "step": "第4步",
            "title": "用小项目串联知识",
            "resource": "实践项目材料 + 拓展阅读",
            "time": "30-45分钟",
            "check": "能独立完成一个小功能",
        },
    ]
    resource_push = [
        {
            "type": "画像依据",
            "title": "按现有证据生成",
            "reason": profile.get("learning_preference") or profile.get("daily_time") or "画像信息不足，使用通用难度",
        },
    ]
    return {
        "规划结论": focus,
        "本次资源类型": resources,
        "学习路径": learning_path,
        "资源推送": resource_push,
        "知识库依据": [f"{x['id']} {x['title']}" for x in knowledge_hits],
        "下一步建议": "完成基础练习后，把答案粘到评估区，系统会更新易错点并调整后续资源推荐。",
    }


def wants_resource_pack(message: str) -> bool:
    msg = message.lower()
    strong_keywords = [
        "学习路径", "学习计划", "资源包", "生成资源", "学习资源", "资料包",
        "完整方案", "完整资源", "多模态", "ppt", "题库",
        "思维导图", "脑图", "视频分镜", "动画分镜", "项目材料",
        "教案", "拓展阅读",
    ]
    if any(keyword in msg for keyword in strong_keywords):
        return True
    light_terms = ["练习题", "习题", "测试题", "视频", "动画", "实操案例", "项目", "资源"]
    intent_terms = ["生成", "制作", "设计", "整理", "输出", "提供一套", "来一套"]
    return any(term in msg for term in intent_terms) and sum(term in msg for term in light_terms) >= 2


def normalize_history(history: Optional[List[Dict[str, str]]], message: str) -> List[Dict[str, str]]:
    if not history:
        return []
    normalized = []
    for item in history[-10:]:
        role = item.get("role", "")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("text") or item.get("content") or "").strip()
        if content:
            normalized.append({"role": role, "content": content[:1600]})
    if normalized and normalized[-1]["role"] == "user" and normalized[-1]["content"].strip() == message.strip():
        normalized = normalized[:-1]
    return normalized[-8:]


def history_text(history: List[Dict[str, str]]) -> str:
    if not history:
        return "无"
    labels = {"user": "学生", "assistant": "助手"}
    return "\n".join(f"{labels.get(item['role'], item['role'])}：{item['content']}" for item in history[-8:])


def extract_last_code(history: List[Dict[str, str]]) -> str:
    for item in reversed(history):
        content = item.get("content", "")
        blocks = re.findall(r"```(?:python)?\s*(.*?)```", content, re.S | re.I)
        if blocks:
            return blocks[-1].strip()
    return ""


def wants_no_analogy(message: str) -> bool:
    return any(x in message for x in ["不要比喻", "别比喻", "不需要比喻", "严格定义", "准确定义", "正式定义", "学术定义"])


def asks_for_code_change(message: str) -> bool:
    return any(x in message.lower() for x in ["class", "类", "封装", "改成", "重构", "函数", "def", "面向对象"])


def build_teacher_prompt(
    message: str,
    profile: Dict[str, Any],
    plan: Dict[str, Any],
    hits: List[Dict[str, Any]],
    recent_history: List[Dict[str, str]],
) -> str:
    kb_text = json.dumps(hits, ensure_ascii=False, indent=2)
    return f"""
你是校园Python课程答疑老师。请回答“最新学生问题”，并优先遵守学生在最新问题里的限制。

最近对话：
{history_text(recent_history)}

最新学生问题：{message}
学生画像：{json.dumps(profile, ensure_ascii=False)}
原始知识库片段：{kb_text}

要求：
- 直接回答最新问题，不要输出“学习画像摘要”“本节学习目标”“知识库依据”“资源推送”“视频分镜”等固定模板。
- 如果学生要求“严格定义、正式定义、不要比喻”，必须给定义式回答，禁止比喻。
- 解释 Python 变量时，优先表述为“名称到对象的绑定/引用”，不要粗略说成“变量就是内存位置”。
- 如果学生要求修改、封装、重构上一轮代码，必须使用最近对话中的代码和需求，不要重新讲概念。
- 如果回答代码，代码块必须是能直接运行的合法 Python；注释必须使用 #。
- 如果信息不足，先说明缺少什么，再给一个可运行的最小版本。
""".strip()


def call_spark(prompt: str, recent_history: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是严谨的Python课程教学智能体。必须回答最新问题，遵守用户限制，"
                "能利用最近对话承接代码修改需求。不要输出固定教案模板。"
            ),
        }
    ]
    messages.extend(recent_history[-6:])
    messages.append({"role": "user", "content": prompt})
    return call_spark_messages(messages, temperature=0.35, max_tokens=1200)


def enrich_answer_with_spark(base_answer: str, spark_answer: Optional[str]) -> str:
    if not spark_answer:
        return base_answer
    return spark_answer.strip()


def class_refactor_answer(message: str, recent_history: List[Dict[str, str]]) -> Optional[str]:
    if not asks_for_code_change(message):
        return None
    last_code = extract_last_code(recent_history)
    if not last_code:
        return None
    if "class" in message.lower() or "类" in message or "面向对象" in message:
        if "score" in last_code or "成绩" in message:
            return """可以，基于上一轮的成绩判断代码，可以封装成一个类：

```python
class GradeJudger:
    def __init__(self, score):
        self.score = score

    def level(self):
        if self.score >= 90:
            return "优秀"
        elif self.score >= 60:
            return "及格"
        else:
            return "不及格"


if __name__ == "__main__":
    score = int(input("请输入成绩："))
    judger = GradeJudger(score)
    print(judger.level())
```

这里 `GradeJudger` 负责保存成绩并判断等级，`level()` 负责返回判断结果。"""
        indented = "\n".join(f"        {line}" if line.strip() else "" for line in last_code.splitlines())
        return f"""可以。因为上一轮代码比较通用，我先按“把原逻辑放进类方法”的方式封装：

```python
class PythonTask:
    def run(self):
{indented}


if __name__ == "__main__":
    task = PythonTask()
    task.run()
```

如果你希望类里有 `__init__`、多个方法，或者要保存状态，可以继续告诉我字段和方法名。"""
    if "函数" in message or "def" in message.lower():
        indented = "\n".join(f"    {line}" if line.strip() else "" for line in last_code.splitlines())
        return f"""可以，把上一轮代码先封装成函数：

```python
def run_task():
{indented}


if __name__ == "__main__":
    run_task()
```
"""
    return None


def strict_definition_answer(message: str, hits: List[Dict[str, Any]]) -> Optional[str]:
    if not wants_no_analogy(message):
        return None
    msg = message.lower()
    if "变量" in message:
        return """在 Python 中，变量是一个名称绑定，它把标识符绑定到某个对象。变量本身不直接保存对象的全部内容，而是作为访问该对象的名字。

更严格地说：
- 变量名必须符合 Python 标识符规则。
- 赋值语句会建立或更新“名称 -> 对象”的绑定关系。
- 对象有类型和值，例如 `int`、`str`、`list`。
- 同一个对象可以被多个变量名引用。

```python
x = 10
y = x
```

这里 `x` 和 `y` 都是变量名，它们都引用整数对象 `10`。"""
    if not hits:
        return "知识库暂无可靠依据"
    main = hits[0]
    return f"""{main.get('title', '该概念')}的定义：
{main.get('content', '暂无定义。')}

```python
{main.get('examples', [''])[0]}
```"""


def direct_teacher_answer(
    message: str,
    profile: Dict[str, Any],
    plan: Dict[str, Any],
    hits: List[Dict[str, Any]],
    recent_history: List[Dict[str, str]],
) -> str:
    if not hits:
        return "知识库暂无可靠依据"

    refactor = class_refactor_answer(message, recent_history)
    if refactor:
        return refactor

    strict = strict_definition_answer(message, hits)
    if strict:
        return strict

    main = hits[0]
    msg = message.lower()
    topic_title = main.get("title", "Python基础")
    content = main.get("content", "")
    code = main.get("examples", ["print('Hello Python')"])[0]
    exercise = (main.get("exercises") or ["把示例代码运行一遍，再改一个地方看看结果。"])[0]
    mistakes = main.get("common_mistakes", [])
    topic_markers = [
        "变量", "if", "elif", "else", "条件", "循环", "for", "while",
        "函数", "def", "return", "参数", "列表", "字典", "文件",
        "异常", "input", "print", "成绩", "项目", "类型", "f-string",
    ]
    is_python_general = ("python" in msg or "编程" in msg) and not any(x in msg for x in topic_markers)

    use_analogy = not wants_no_analogy(message)

    if is_python_general and any(x in msg for x in ["怎么用", "如何用", "怎么运行", "如何运行", "使用"]):
        intro = "Python 的用法可以理解为：你写一段指令，让电脑按顺序执行。入门时先不用想复杂项目，先学会写一小段代码、保存、运行、看结果。"
        next_step = "你可以先这样开始：新建一个 demo.py 文件，写入上面的代码，保存后运行。看到屏幕输出内容，就说明你已经完成了第一个 Python 程序。"
    elif is_python_general and any(x in msg for x in ["是什么", "什么是", "介绍", "python是啥"]):
        intro = "Python 是一门编程语言，也就是用来和电脑“下指令”的工具。它语法比较接近自然语言，适合零基础入门，可以用来写小工具、处理数据、做网站，也常用于人工智能相关开发。"
        next_step = "刚开始不用背很多概念，先会用 print 输出内容，再学变量、输入、条件判断、循环和函数。"
    elif any(x in msg for x in ["怎么用", "如何用", "怎么写", "使用"]):
        intro = f"{topic_title}可以这样用：{content}"
        next_step = "先把下面这个最小例子跑通，再改一个数字、文字或条件，看输出怎么变化。"
    else:
        prefix = "可以这样理解" if use_analogy else "定义"
        intro = f"{topic_title}{prefix}：{content}"
        next_step = f"你可以马上练一下：{exercise}"

    tip = f"\n\n注意：{mistakes[0]}" if mistakes else ""
    return f"""{intro}

最小例子：
```python
{code}
```

{next_step}{tip}"""


def offline_teacher_answer(
    message: str,
    profile: Dict[str, Any],
    plan: Dict[str, Any],
    hits: List[Dict[str, Any]],
    recent_history: List[Dict[str, str]],
) -> str:
    return direct_teacher_answer(message, profile, plan, hits, recent_history)


def review_chat_answer(
    user_id: str,
    answer: str,
    hits: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    citations = citations_for_knowledge(hits, CITATIONS)
    if not hits or not citations:
        return {
            "status": "insufficient_evidence",
            "issues": ["知识库暂无可靠依据"],
            "claims": [],
            "mode": "local_validation",
        }, []
    review = REVIEW_SERVICE.review(
        user_id,
        [{
            "id": "chat-answer",
            "type": "explanation",
            "title": "对话答疑",
            "content": {"answer": answer},
            "citation_ids": [item["id"] for item in citations],
        }],
        citations,
    )
    return review, citations


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/chat")
def chat_page():
    return FileResponse(BASE_DIR / "static" / "chat.html", headers={"Cache-Control": "no-store"})


@app.get("/profile")
def profile_page():
    return FileResponse(BASE_DIR / "static" / "profile.html", headers={"Cache-Control": "no-store"})


@app.get("/assistants")
def assistants_page():
    return FileResponse(BASE_DIR / "static" / "assistants.html", headers={"Cache-Control": "no-store"})


@app.get("/resources/{resource_id}")
def resource_page(resource_id: str):
    return FileResponse(BASE_DIR / "static" / "resource.html")


@app.get("/entry")
def entry_page():
    return FileResponse(BASE_DIR / "PROJECT_ENTRY.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "spark" if bool(SPARK_API_PASSWORD) else "offline-demo",
        "model": SPARK_MODEL,
        "base_url": SPARK_BASE_URL,
        "knowledge_count": len(KNOWLEDGE_BASE),
        "citation_count": len(CITATIONS),
        "profile_extraction": True,
        "profile_strategy": "evidence_json_agent",
        "astron_configured": ASTRON_CLIENT.configured,
        "timeout_seconds": SPARK_TIMEOUT_SECONDS,
        "spark_retries": SPARK_RETRIES,
        "asr_configured": asr_configured(),
        "asr_endpoint": XF_ASR_ENDPOINT,
        "lightrag": LIGHTRAG_CLIENT.status(),
    }


@app.get("/api/domain-agents")
def domain_agents():
    return {"agents": list_domain_agents()}


@app.get("/api/courses")
def courses(user_id: str = "demo_student"):
    return {"courses": STORAGE.list_courses(include_private=True, user_id=user_id)}


@app.post("/api/custom-assistants")
def create_custom_assistant(req: CustomAssistantCreateRequest):
    if not req.name.strip() or not req.course_name.strip():
        raise HTTPException(status_code=400, detail="助手名和课程名不能为空")
    if req.domain not in {"programming", "math", "politics", "other"}:
        raise HTTPException(status_code=400, detail="领域必须为 programming、math、politics 或 other")
    assistant_id = "asst_" + uuid.uuid4().hex[:20]
    workspace = custom_workspace(req.user_id, assistant_id)
    assistant = STORAGE.create_custom_assistant({
        "assistant_id": assistant_id,
        "user_id": req.user_id,
        "name": req.name.strip()[:80],
        "course_name": req.course_name.strip()[:120],
        "domain": req.domain,
        "learning_goal": req.learning_goal.strip()[:1000],
        "answer_preference": req.answer_preference.strip()[:1000],
        "course_id": "custom_" + assistant_id,
        "workspace": workspace,
        "status": "awaiting_documents",
    })
    return assistant


@app.get("/api/custom-assistants/{assistant_id}")
def get_custom_assistant(assistant_id: str, user_id: str = "demo_student"):
    assistant = STORAGE.get_custom_assistant(assistant_id, user_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="课程助手不存在或不属于当前用户")
    assistant["documents"] = STORAGE.list_knowledge_documents(
        assistant_id=assistant_id, user_id=user_id
    )
    return assistant


@app.post("/api/custom-assistants/{assistant_id}/documents")
def upload_assistant_document(
    assistant_id: str,
    file: UploadFile = File(...),
    user_id: str = Form("demo_student"),
):
    if not LIGHTRAG_CLIENT.available:
        raise HTTPException(status_code=503, detail="LightRAG 尚未安装，请先执行项目安装命令")
    assistant = STORAGE.get_custom_assistant(assistant_id, user_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="课程助手不存在或不属于当前用户")
    try:
        filename = safe_filename(file.filename or "")
        incoming_dir = BASE_DIR / "data" / "incoming" / uuid.uuid4().hex
        incoming_dir.mkdir(parents=True, exist_ok=True)
        incoming_path = incoming_dir / filename
        total = 0
        with incoming_path.open("wb") as handle:
            while True:
                block = file.file.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError("文件超过 80MB 限制")
                handle.write(block)
        result = INDEXING_SERVICE.enqueue_source(
            incoming_path,
            assistant["course_id"],
            assistant["workspace"],
            assistant_id=assistant_id,
            user_id=user_id,
            copy_original=True,
            skip_duplicates=True,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass
        if "incoming_dir" in locals():
            shutil.rmtree(incoming_dir, ignore_errors=True)


@app.get("/api/indexing-jobs/{job_id}")
def get_indexing_job(job_id: str, user_id: str = "demo_student"):
    job = STORAGE.get_indexing_job(job_id)
    if not job or (job.get("user_id") and job.get("user_id") != user_id):
        raise HTTPException(status_code=404, detail="索引任务不存在")
    return job


@app.get("/api/assistants/{assistant_id}/documents")
def assistant_documents(assistant_id: str, user_id: str = "demo_student"):
    assistant = STORAGE.get_custom_assistant(assistant_id, user_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="课程助手不存在或不属于当前用户")
    return {"documents": STORAGE.list_knowledge_documents(assistant_id=assistant_id, user_id=user_id)}


@app.get("/api/assistants/documents/{document_id}")
def assistant_document(document_id: str, user_id: str = "demo_student"):
    document = STORAGE.get_knowledge_document(document_id)
    if not document or (document.get("user_id") and document.get("user_id") != user_id):
        raise HTTPException(status_code=404, detail="知识文档不存在")
    return document


@app.post("/api/assistants/{assistant_id}/query")
def query_assistant(assistant_id: str, req: AssistantQueryRequest):
    if assistant_id != req.assistant_id:
        raise HTTPException(status_code=400, detail="路径与请求体中的 assistant_id 不一致")
    safety = check_input(req.message)
    if not safety["allowed"]:
        raise HTTPException(status_code=400, detail=safety["reason"])
    if req.allow_cross_course:
        if not assistant_id.startswith("domain_") and assistant_id != "public":
            raise HTTPException(status_code=400, detail="用户私有助手不允许跨 workspace 检索")
        requested = list(dict.fromkeys(req.course_ids or []))
        if len(requested) < 2 or len(requested) > 3:
            raise HTTPException(status_code=400, detail="跨课程检索必须明确提供 2 至 3 个 course_ids")
        results = []
        for cross_course_id in requested:
            cross_scope = resolve_assistant_scope(req.user_id, cross_course_id, "public")
            indexed = STORAGE.list_knowledge_documents(course_id=cross_course_id)
            if not any(item["index_status"] == "indexed" for item in indexed):
                results.append({"course_id": cross_course_id, "answer": "当前课程知识库中没有找到足够可靠的资料。", "citations": []})
                continue
            result = RETRIEVAL_SERVICE.answer(
                req.user_id, cross_course_id, cross_scope["workspace"], req.message,
                profile=PROFILE_SERVICE.snapshot(req.user_id, cross_course_id),
            )
            results.append({"course_id": cross_course_id, **result})
        return {
            "cross_course": True,
            "answer": "\n\n".join(f"## {item['course_id']}\n{item['answer']}" for item in results),
            "results": results,
            "citations": [citation for item in results for citation in item.get("citations", [])],
        }
    scope = resolve_assistant_scope(req.user_id, req.course_id, req.assistant_id)
    documents = STORAGE.list_knowledge_documents(
        course_id=scope["course_id"],
        assistant_id=req.assistant_id if scope["assistant"] else None,
        user_id=req.user_id if scope["assistant"] else None,
    )
    if not any(item["index_status"] == "indexed" for item in documents):
        raise HTTPException(status_code=409, detail="当前课程助手尚无可用索引")
    return RETRIEVAL_SERVICE.answer(
        req.user_id,
        scope["course_id"],
        scope["workspace"],
        req.message,
        profile=PROFILE_SERVICE.snapshot(req.user_id, scope["course_id"]),
    )


@app.post("/api/asr")
async def speech_to_text(request: Request):
    if not asr_configured():
        raise HTTPException(
            status_code=400,
            detail="语音识别还没有配置。请在 config_keys.env 中填写 XF_ASR_APP_ID、XF_ASR_API_KEY、XF_ASR_API_SECRET。",
        )
    pcm = await request.body()
    if not pcm:
        raise HTTPException(status_code=400, detail="没有收到录音内容。")
    if len(pcm) > 2_100_000:
        raise HTTPException(status_code=413, detail="录音过长，请控制在 60 秒以内。")
    try:
        text = await recognize_pcm_with_xfyun(pcm)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"语音识别调用失败：{exc}") from exc
    return {"text": text}


@app.post("/api/chat")
def chat(req: ChatRequest):
    safety = check_input(req.message)
    if not safety["allowed"]:
        return {
            "answer": safety["reason"],
            "profile": PROFILE_SERVICE.snapshot(req.user_id, req.course_id),
            "plan": {},
            "knowledge_used": [],
            "citations": [],
            "review": {"status": "rejected", "issues": [safety["reason"]], "claims": []},
            "mode": "blocked",
            "profile_agent": "not_called",
            "spark_error": None,
            "profile_error": None,
            "profile_updates": [],
            "profile_rejected": [],
        }
    recent_history = normalize_history(req.history, req.message)
    if not recent_history:
        recent_history = normalize_history(
            CHAT_HISTORY.get(chat_history_key(req.user_id, req.course_id), []), req.message
        )
    profile_result = PROFILE_SERVICE.extract_and_update(req.user_id, req.message, req.course_id)
    profile_snapshot = profile_result["profile"]
    profile = PROFILE_SERVICE.values(profile_snapshot)
    scope = resolve_assistant_scope(req.user_id, req.course_id, req.assistant_id or "")
    rag_documents = STORAGE.list_knowledge_documents(
        course_id=scope["course_id"],
        assistant_id=req.assistant_id if scope["assistant"] else None,
        user_id=req.user_id if scope["assistant"] else None,
    )
    if LIGHTRAG_CLIENT.available and any(item["index_status"] == "indexed" for item in rag_documents):
        rag_result = RETRIEVAL_SERVICE.answer(
            req.user_id,
            scope["course_id"],
            scope["workspace"],
            req.message,
            profile=profile_snapshot,
        )
        answer = rag_result["answer"]
        history_key = chat_history_key(req.user_id, scope["course_id"])
        CHAT_HISTORY.setdefault(history_key, []).append({"role": "user", "content": req.message})
        CHAT_HISTORY.setdefault(history_key, []).append({"role": "assistant", "content": answer[:1000]})
        return {
            "answer": answer,
            "profile": profile_snapshot,
            "plan": {},
            "knowledge_used": rag_result.get("chunks", []),
            "citations": rag_result.get("citations", []),
            "review": rag_result.get("review", {}),
            "resources": [],
            "verification": {
                "status": rag_result.get("review", {}).get("status", "insufficient_evidence"),
                "references": [item["material_name"] for item in rag_result.get("citations", [])],
                "risk_tips": rag_result.get("review", {}).get("issues", []),
            },
            "mode": "lightrag_" + rag_result.get("mode", "failed"),
            "course_id": scope["course_id"],
            "workspace": scope["workspace"],
            "profile_agent": profile_result["execution"]["mode"],
            "spark_error": None,
            "profile_error": profile_result["execution"]["error"],
            "profile_updates": profile_result["applied"],
            "profile_rejected": profile_result["rejected"],
        }
    hits = retrieve_knowledge(req.message, top_k=4)
    plan = build_learning_plan(profile, req.message, hits)
    if wants_resource_pack(req.message):
        citations = citations_for_knowledge(hits, CITATIONS)
        resource_result = RESOURCE_SERVICE.generate(
            req.user_id,
            req.message,
            profile_snapshot,
            hits,
            citations,
            course_id=scope["course_id"],
            workspace_id=scope["workspace"],
        )
        resources = resource_result["resources"]
        if resources and resource_result["review"]["status"] == "passed":
            links = "\n".join(
                f"- [{item['title']}](/resources/{item['id']}) · {item['review_status']}"
                for item in resources
            )
            answer = f"已生成并保存 {len(resources)} 类学习资源：\n\n{links}"
        elif resources:
            issues = "；".join(resource_result["review"].get("issues") or ["内容未通过审核"])
            answer = f"资源已生成但未通过审核，暂不作为正式学习材料展示。原因：{issues}"
        else:
            issues = "；".join(resource_result["review"].get("issues") or ["生成失败"])
            answer = issues
        history_key = chat_history_key(req.user_id, req.course_id)
        CHAT_HISTORY.setdefault(history_key, []).append({"role": "user", "content": req.message})
        CHAT_HISTORY.setdefault(history_key, []).append({"role": "assistant", "content": answer[:1000]})
        return {
            "answer": answer,
            "profile": profile_snapshot,
            "plan": plan,
            "knowledge_used": hits,
            "citations": citations,
            "review": resource_result["review"],
            "verification": {
                "status": resource_result["review"]["status"],
                "references": [item["title"] for item in citations],
                "risk_tips": resource_result["review"].get("issues") or [],
            },
            "resources": resources,
            "mode": resource_result["execution"]["mode"],
            "profile_agent": profile_result["execution"]["mode"],
            "spark_error": resource_result["execution"].get("error"),
            "profile_error": profile_result["execution"]["error"],
            "profile_updates": profile_result["applied"],
            "profile_rejected": profile_result["rejected"],
        }
    prompt = build_teacher_prompt(req.message, profile, plan, hits, recent_history)
    spark_answer, spark_error = call_spark(prompt, recent_history) if req.use_spark else (None, None)
    base_answer = offline_teacher_answer(req.message, profile, plan, hits, recent_history)
    answer = enrich_answer_with_spark(base_answer, spark_answer)
    review, citations = review_chat_answer(req.user_id, answer, hits)
    for _ in range(2):
        if review["status"] == "passed" or not req.use_spark or not hits:
            break
        revision_prompt = prompt + "\n审核意见：" + json.dumps(review.get("issues", []), ensure_ascii=False) + "\n请修订后重新回答。"
        revised_answer, revision_error = call_spark(revision_prompt, recent_history)
        if not revised_answer:
            spark_error = revision_error or spark_error
            break
        answer = revised_answer.strip()
        review, citations = review_chat_answer(req.user_id, answer, hits)
    if not hits:
        answer = "知识库暂无可靠依据"
    elif review["status"] in {"needs_revision", "rejected"}:
        reasons = "；".join(review.get("issues") or ["内容未通过审核"])
        answer = f"本次回答未通过内容审核，暂不展示未经核验的内容。原因：{reasons}"
    verification = {
        "status": review["status"],
        "references": [item["title"] for item in citations],
        "risk_tips": review.get("issues") or [],
    }
    history_key = chat_history_key(req.user_id, req.course_id)
    CHAT_HISTORY.setdefault(history_key, []).append({"role": "user", "content": req.message})
    CHAT_HISTORY.setdefault(history_key, []).append({"role": "assistant", "content": answer[:1000]})
    return {
        "answer": answer,
        "profile": profile_snapshot,
        "plan": plan,
        "knowledge_used": hits,
        "citations": citations,
        "review": review,
        "resources": [],
        "verification": verification,
        "mode": "spark" if spark_answer else "fast-local",
        "profile_agent": profile_result["execution"]["mode"],
        "spark_error": spark_error,
        "profile_error": profile_result["execution"]["error"],
        "profile_updates": profile_result["applied"],
        "profile_rejected": profile_result["rejected"],
    }


@app.post("/api/evaluate")
def evaluate(req: EvaluateRequest):
    hits = retrieve_knowledge(req.answer + " " + (req.question or ""), top_k=4)
    score = 60
    feedback = []
    weak_points = []
    a = req.answer.strip()
    if not a:
        score = 0
        feedback.append("你还没有填写答案。")
        weak_points.append("练习提交不完整")
    else:
        if any(x in a for x in ["if", "elif", "else"]):
            score += 10
        if ":" in a:
            score += 10
        else:
            feedback.append("如果你写的是if/elif/else、for或while，后面通常要有英文冒号。")
            weak_points.append("英文冒号")
        if "    " in a or "\n " in a or "\t" in a:
            score += 10
        else:
            feedback.append("Python非常重视缩进，条件成立后执行的代码要缩进。")
            weak_points.append("缩进")
        if "print" in a:
            score += 5
        if "input" in a and ("int(" in a or "float(" in a):
            score += 5
        elif "input" in a:
            feedback.append("input得到的是字符串，如果要比较数字，建议用int或float转换。")
            weak_points.append("类型转换")
        if any(x in a for x in ["for", "while"]):
            score += 5
    score = max(0, min(100, score))
    if score >= 90:
        level = "优秀：已经能独立写出核心结构。"
        next_step = "下一步建议：进入小项目挑战，把本知识点和输入输出、列表或函数串起来。"
        adjustment = ["推送实践项目材料", "减少基础讲解比例", "增加挑战题"]
    elif score >= 75:
        level = "良好：思路基本对，注意细节错误。"
        next_step = "下一步建议：再做1道进阶题，重点检查冒号、缩进和变量命名。"
        adjustment = ["推送进阶练习题", "保留代码实操案例"]
    elif score >= 60:
        level = "及格：概念有印象，但需要继续模仿代码。"
        next_step = "下一步建议：回到最小可运行代码，自己重新敲一遍，再改一个条件运行。"
        adjustment = ["推送图文讲解", "推送基础题", "推送代码逐行解释"]
    else:
        level = "需要补基础：建议回到图文讲解和最小代码重新跑一遍。"
        next_step = "下一步建议：先不做挑战题，只完成基础题和代码跟敲。"
        adjustment = ["降低题目难度", "推送图文讲解", "推送基础概念讲解"]
    if not feedback:
        feedback.append("没有发现明显基础错误。")
    practice_updates = [
        {
            "field": "learning_state",
            "value": f"最近练习得分 {score} 分",
            "evidence": f"练习评估结果：{score}分，{level}",
            "confidence": 1.0,
        }
    ]
    if weak_points:
        practice_updates.extend([
            {
                "field": "common_errors",
                "value": weak_points,
                "evidence": "练习代码检测到：" + "、".join(weak_points),
                "confidence": 0.9,
            },
            {
                "field": "unmastered",
                "value": weak_points,
                "evidence": "练习尚未稳定掌握：" + "、".join(weak_points),
                "confidence": 0.85,
            },
        ])
    elif score >= 90 and hits:
        practice_updates.append({
            "field": "mastered",
            "value": [hits[0]["title"]],
            "evidence": f"练习评估 {score} 分，未发现明显基础错误",
            "confidence": 0.9,
        })
    updated_profile = PROFILE_SERVICE.record_practice_updates(req.user_id, practice_updates, req.course_id)
    result = {
        "score": score,
        "level": level,
        "feedback": feedback,
        "next_step": next_step,
        "resource_adjustment": adjustment,
        "updated_profile": updated_profile,
        "knowledge_check": {
            "status": "practice_evidence_recorded",
            "references": [item["id"] for item in hits],
        },
    }
    STORAGE.save_practice_record(
        req.user_id, req.course_id, req.question, req.answer, score, result
    )
    return result


@app.post("/api/profile")
def profile(req: ProfileRequest):
    return PROFILE_SERVICE.snapshot(req.user_id, req.course_id)


@app.post("/api/profile/update")
def update_profile(req: ProfileUpdateRequest):
    result = PROFILE_SERVICE.apply_user_correction(
        req.user_id,
        req.field,
        req.value,
        req.evidence or "用户在画像页面手动修改",
        req.course_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result["profile"]


@app.post("/api/resources/generate")
def generate_resources(req: ResourceGenerateRequest):
    safety = check_input(req.request)
    if not safety["allowed"]:
        raise HTTPException(status_code=400, detail=safety["reason"])
    hits = retrieve_knowledge(req.request, top_k=5)
    citations = citations_for_knowledge(hits, CITATIONS)
    scope = resolve_assistant_scope(req.user_id, req.course_id)
    result = RESOURCE_SERVICE.generate(
        req.user_id,
        req.request,
        PROFILE_SERVICE.snapshot(req.user_id, req.course_id),
        hits,
        citations,
        course_id=scope["course_id"],
        workspace_id=scope["workspace"],
    )
    if not result["resources"]:
        status = 422 if result["review"]["status"] == "insufficient_evidence" else 502
        raise HTTPException(status_code=status, detail=result)
    return result


@app.get("/api/resources")
def list_resources(user_id: str = "demo_student", course_id: Optional[str] = None):
    return {"resources": STORAGE.list_resources(user_id, course_id=course_id)}


@app.get("/api/resources/{resource_id}")
def get_resource(resource_id: str):
    resource = STORAGE.get_resource(resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="学习资源不存在")
    if resource["type"] == "explanation" and resource["content"].get("markdown"):
        resource["content"]["html"] = markdown_as_safe_html(resource["content"]["markdown"])
    return resource
