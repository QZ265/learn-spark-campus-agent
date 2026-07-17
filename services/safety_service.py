import re
from typing import Any, Dict


INPUT_RULES = [
    (
        "prompt_injection",
        re.compile(r"(忽略|绕过|覆盖).{0,12}(系统|之前|开发者|规则|提示词)|system\s*prompt|developer\s*message", re.I),
        "检测到提示词注入请求，不能执行。",
    ),
    (
        "secret_request",
        re.compile(r"(输出|显示|泄露|读取|告诉我).{0,16}(api.?key|api.?secret|password|密钥|环境变量|config_keys)", re.I),
        "不能读取或泄露系统密钥。",
    ),
    (
        "malicious_code",
        re.compile(r"(勒索|窃取密码|盗取凭证|反向 shell|reverse shell|删除所有文件|rm\s+-rf|制作木马|恶意代码)", re.I),
        "不能协助生成破坏性或窃密代码。",
    ),
    (
        "inappropriate",
        re.compile(r"(色情内容|性剥削|仇恨攻击|自杀方法|制造炸弹)", re.I),
        "该请求不适合校园学习辅助场景。",
    ),
]

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?(?:key|secret|password)|authorization)\s*[:=]\s*[A-Za-z0-9_:/+.-]{12,}"
)


def check_input(text: str) -> Dict[str, Any]:
    for category, pattern, reason in INPUT_RULES:
        if pattern.search(text or ""):
            return {"allowed": False, "category": category, "reason": reason}
    return {"allowed": True, "category": None, "reason": None}


def contains_secret(text: str) -> bool:
    return bool(SECRET_PATTERN.search(text or ""))
