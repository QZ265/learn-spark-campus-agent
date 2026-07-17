import json
import tempfile
import threading
import unittest
from pathlib import Path

from services.resource_service import ResourceService, citations_for_knowledge, markdown_as_safe_html
from services.review_service import ReviewService, validate_python
from services.storage import AppStorage


def generated_payload(code="def add(a, b):\n    return a + b"):
    return {
        "resources": [
            {
                "type": "explanation",
                "title": "列表讲解",
                "citation_ids": ["PYDOC-DATA"],
                "content": {
                    "heading": "Python 列表",
                    "objective": "掌握列表读取",
                    "prerequisites": "变量",
                    "explanation": "列表是有序容器。",
                    "examples": ["items = [1, 2]\nprint(items[0])"],
                    "common_errors": ["下标越界"],
                    "summary": "用下标读取元素。",
                },
            },
            {
                "type": "mindmap",
                "title": "列表脑图",
                "citation_ids": ["PYDOC-DATA"],
                "content": {"mermaid": "mindmap\n  root((列表))\n    下标\n    append"},
            },
            {
                "type": "quiz",
                "title": "列表练习",
                "citation_ids": ["PYDOC-DATA"],
                "content": {"questions": [{
                    "question": "[1, 2][0] 是多少？",
                    "answer": "1",
                    "explanation": "下标从 0 开始。",
                    "difficulty": "基础",
                    "knowledge_point": "列表下标",
                }]},
            },
            {
                "type": "code_case",
                "title": "加法案例",
                "citation_ids": ["PYDOC-DATA"],
                "content": {
                    "initial_code": "def add(a, b):\n    pass",
                    "task": "完成 add 函数",
                    "tests": "assert add(1, 2) == 3",
                    "reference_answer": code,
                },
            },
            {
                "type": "further_reading",
                "title": "列表阅读",
                "citation_ids": ["PYDOC-DATA"],
                "content": {"items": [{"citation_id": "PYDOC-DATA", "reason": "查看官方列表方法"}]},
            },
        ]
    }


class ResourceModel:
    def __init__(self, unsafe_first=False):
        self.unsafe_first = unsafe_first
        self.code_calls = 0
        self.lock = threading.Lock()

    def __call__(self, task, prompt, context):
        if task == "review":
            response = {"status": "passed", "issues": [], "claims": [{
                "claim": "内容与来源一致", "citation_ids": ["PYDOC-DATA"], "support_status": "supported"
            }]}
        else:
            resource_type = context["resource_type"]
            if resource_type.startswith("quiz_"):
                question = generated_payload()["resources"][2]["content"]["questions"][0]
                response = {"citation_ids": ["PYDOC-DATA"], "question": question}
                return {"content": json.dumps(response, ensure_ascii=False), "mode": "astron", "error": None, "request_id": "req"}
            with self.lock:
                if resource_type == "code_case":
                    self.code_calls += 1
                    unsafe = self.unsafe_first and self.code_calls == 1
                else:
                    unsafe = False
            payload = generated_payload("import os\nos.system('rm -rf /')" if unsafe else "def add(a, b):\n    return a + b")
            resource = next(item for item in payload["resources"] if item["type"] == resource_type)
            response = {"resource": resource}
        return {"content": json.dumps(response, ensure_ascii=False), "mode": "astron", "error": None, "request_id": "req"}


class ResourceServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = AppStorage(Path(self.temp_dir.name) / "test.db")
        self.citations = [{
            "id": "PYDOC-DATA",
            "title": "Python 官方教程：数据结构",
            "url": "https://docs.python.org/zh-cn/3/tutorial/datastructures.html",
            "publisher": "Python Software Foundation",
            "topics": ["列表"],
        }]
        self.knowledge = [{"id": "PY-012", "title": "列表list与下标", "tags": ["列表"], "content": "列表是有序容器"}]
        self.profile = {
            "records": [{
                "field": "common_errors", "label": "常见错误", "value": ["混淆列表和元组"],
                "evidence": "经常混淆列表和元组", "status": "confirmed",
            }]
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generates_five_reviewed_persisted_resources(self):
        model = ResourceModel()
        service = ResourceService(self.storage, model, ReviewService(model))

        result = service.generate("u1", "生成列表资源", self.profile, self.knowledge, self.citations)

        self.assertEqual(len(result["resources"]), 5)
        self.assertEqual(result["review"]["status"], "passed")
        resource = result["resources"][0]
        self.assertIn("markdown", resource["content"])
        self.assertEqual(resource["profile_basis"][0]["evidence"], "经常混淆列表和元组")
        self.assertEqual(self.storage.get_resource(resource["id"])["review_status"], "passed")

    def test_review_failure_regenerates_and_does_not_execute_code(self):
        model = ResourceModel(unsafe_first=True)
        service = ResourceService(self.storage, model, ReviewService(model))

        result = service.generate("u2", "生成列表资源", self.profile, self.knowledge, self.citations)

        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["review"]["status"], "passed")
        code_resource = next(item for item in result["resources"] if item["type"] == "code_case")
        self.assertNotIn("import os", code_resource["content"]["reference_answer"])

    def test_no_knowledge_returns_insufficient_evidence(self):
        model = ResourceModel()
        service = ResourceService(self.storage, model, ReviewService(model))

        result = service.generate("u3", "未知主题", self.profile, [], [])

        self.assertEqual(result["resources"], [])
        self.assertEqual(result["review"]["status"], "insufficient_evidence")
        self.assertIn("知识库暂无可靠依据", result["review"]["issues"])

    def test_markdown_renderer_keeps_python_comments_inside_code(self):
        rendered = markdown_as_safe_html("# 示例\n\n```python\n# 注释\nprint('ok')\n```")
        self.assertIn("<h1>示例</h1>", rendered)
        self.assertIn("<pre><code># 注释", rendered)
        self.assertNotIn("<h1>注释</h1>", rendered)

    def test_citations_include_matching_knowledge_evidence(self):
        selected = citations_for_knowledge(self.knowledge, self.citations)
        self.assertEqual(selected[0]["knowledge_evidence"][0]["id"], "PY-012")

    def test_benign_file_example_is_allowed_but_system_module_is_not(self):
        self.assertIsNone(validate_python("with open('notes.txt') as file:\n    print(file.read())"))
        self.assertIn("不允许", validate_python("import os\nos.system('rm -rf /')"))


if __name__ == "__main__":
    unittest.main()
