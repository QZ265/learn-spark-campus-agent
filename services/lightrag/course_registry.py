import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CourseDefinition:
    course_id: str
    workspace: str
    domain: str
    name: str
    assistant_name: str
    is_public: bool = True


_COURSES = (
    CourseDefinition("programming_python", "programming_python", "programming", "Python 程序设计", "Python 课程助手"),
    CourseDefinition("math_calculus", "math_calculus", "math", "高等数学", "数学课程助手"),
    CourseDefinition("math_linear_algebra", "math_linear_algebra", "math", "线性代数", "数学课程助手"),
    CourseDefinition("math_probability_statistics", "math_probability_statistics", "math", "概率论与数理统计", "数学课程助手"),
    CourseDefinition("politics_maogai", "politics_maogai", "politics", "毛泽东思想和中国特色社会主义理论体系概论", "思政课程助手"),
    CourseDefinition("politics_modern_history", "politics_modern_history", "politics", "中国近现代史纲要", "思政课程助手"),
    CourseDefinition("politics_xi_thought", "politics_xi_thought", "politics", "习近平新时代中国特色社会主义思想概论", "思政课程助手"),
)

COURSE_REGISTRY: Dict[str, CourseDefinition] = {item.course_id: item for item in _COURSES}
WORKSPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{2,95}$")


def get_course(course_id: str) -> Optional[CourseDefinition]:
    return COURSE_REGISTRY.get((course_id or "").strip())


def list_courses(domain: Optional[str] = None) -> List[dict]:
    items = _COURSES
    if domain:
        items = tuple(item for item in items if item.domain == domain)
    return [asdict(item) for item in items]


def list_domain_agents() -> List[dict]:
    definitions = {
        "programming": ("编程领域助手", "面向程序设计课程，仅检索当前所选课程知识空间"),
        "math": ("数学领域助手", "面向数学课程，仅检索当前所选课程知识空间"),
        "politics": ("思政领域助手", "面向思政课程，仅检索当前所选课程知识空间"),
    }
    return [
        {
            "assistant_id": f"domain_{domain}",
            "domain": domain,
            "name": name,
            "description": description,
            "courses": list_courses(domain),
        }
        for domain, (name, description) in definitions.items()
    ]


def custom_workspace(user_id: str, assistant_id: str) -> str:
    safe_user = re.sub(r"[^a-zA-Z0-9]", "", user_id or "")[:24]
    safe_assistant = re.sub(r"[^a-zA-Z0-9]", "", assistant_id or "")[:32]
    if not safe_user or not safe_assistant:
        raise ValueError("user_id 或 assistant_id 无法生成安全 workspace")
    workspace = f"user_{safe_user}_{safe_assistant}".lower()
    if not WORKSPACE_PATTERN.fullmatch(workspace):
        raise ValueError("生成的 workspace 名称不合法")
    return workspace


def validate_workspace(workspace: str) -> str:
    value = (workspace or "").strip()
    if not WORKSPACE_PATTERN.fullmatch(value):
        raise ValueError("workspace 只允许小写字母、数字和下划线")
    return value
