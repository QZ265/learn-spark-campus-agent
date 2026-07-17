import json
import tempfile
import unittest
from pathlib import Path

from services.profile_service import ProfileService, safe_json_object
from services.storage import AppStorage


class QueueModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, task, prompt, context):
        self.calls += 1
        content = self.responses.pop(0)
        return {"content": content, "mode": "spark_fallback", "error": None}


class ProfileServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = AppStorage(Path(self.temp_dir.name) / "test.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_user_a_creates_only_evidence_based_profile(self):
        message = "我是软件工程大一学生，Python刚学列表和元组，每天半小时，喜欢看例子后写代码，经常混淆列表和元组。"
        updates = {
            "updates": [
                {"field": "identity", "value": "软件工程大一学生", "evidence": "我是软件工程大一学生", "source_type": "conversation", "confidence": 0.98},
                {"field": "current_course", "value": "Python：列表和元组", "evidence": "Python刚学列表和元组", "source_type": "conversation", "confidence": 0.96},
                {"field": "daily_time", "value": "每天半小时", "evidence": "每天半小时", "source_type": "conversation", "confidence": 0.99},
                {"field": "learning_preference", "value": ["看例子后写代码"], "evidence": "喜欢看例子后写代码", "source_type": "conversation", "confidence": 0.96},
                {"field": "common_errors", "value": ["混淆列表和元组"], "evidence": "经常混淆列表和元组", "source_type": "conversation", "confidence": 0.98},
            ]
        }
        model = QueueModel([json.dumps(updates, ensure_ascii=False)])
        result = ProfileService(self.storage, model).extract_and_update("user-a", message)
        values = ProfileService.values(result["profile"])

        self.assertEqual(values["identity"], "软件工程大一学生")
        self.assertEqual(values["daily_time"], "每天半小时")
        self.assertEqual(values["common_errors"], ["混淆列表和元组"])
        self.assertNotIn("cognitive_style", values)
        self.assertEqual(len(result["applied"]), 5)

    def test_user_b_does_not_create_personality_profile(self):
        message = "讲一下Python列表。"
        model = QueueModel([
            json.dumps({
                "updates": [
                    {"field": "current_course", "value": "Python列表", "evidence": "Python列表", "source_type": "conversation", "confidence": 0.7}
                ]
            }, ensure_ascii=False)
        ])
        result = ProfileService(self.storage, model).extract_and_update("user-b", message)
        values = ProfileService.values(result["profile"])

        self.assertEqual(values, {"current_course": "Python列表"})
        self.assertEqual(len(result["profile"]["missing_fields"]), 8)

    def test_json_parse_failure_retries_once(self):
        model = QueueModel([
            "not-json",
            '{"updates":[{"field":"daily_time","value":"每天30分钟","evidence":"每天30分钟","source_type":"conversation","confidence":0.9}]}'
        ])
        service = ProfileService(self.storage, model)
        result = service.extract_and_update("retry-user", "我每天30分钟")

        self.assertEqual(model.calls, 2)
        self.assertEqual(ProfileService.values(result["profile"])["daily_time"], "每天30分钟")

    def test_json_parser_accepts_literal_newline_from_mermaid_output(self):
        parsed = safe_json_object('{"content":{"mermaid":"mindmap\n  root((列表))"}}')
        self.assertEqual(parsed["content"]["mermaid"], "mindmap\n  root((列表))")

    def test_update_without_message_evidence_is_rejected(self):
        model = QueueModel([
            '{"updates":[{"field":"learning_preference","value":["视觉化"],"evidence":"喜欢图表","source_type":"conversation","confidence":0.9}]}'
        ])
        result = ProfileService(self.storage, model).extract_and_update("no-evidence", "讲一下Python列表")

        self.assertEqual(result["applied"], [])
        self.assertEqual(result["rejected"][0]["reason"], "证据不是本轮原话")

    def test_user_correction_has_highest_priority(self):
        service = ProfileService(self.storage, QueueModel(['{"updates":[]}']))
        service.record_practice_updates("correction", [{
            "field": "daily_time", "value": "每天30分钟", "evidence": "练习记录估计每天30分钟", "confidence": 0.7
        }])
        result = service.apply_user_correction("correction", "daily_time", "每周末2小时", "用户明确修改")
        record = result["profile"]["record_map"]["daily_time"]

        self.assertEqual(record["value"], "每周末2小时")
        self.assertEqual(record["source_type"], "user_correction")
        self.assertEqual(record["confidence"], 1.0)

    def test_conflicting_conversation_evidence_is_marked(self):
        model = QueueModel([
            '{"updates":[{"field":"daily_time","value":"每天30分钟","evidence":"每天30分钟","source_type":"conversation","confidence":0.9}]}',
            '{"updates":[{"field":"daily_time","value":"每天1小时","evidence":"每天1小时","source_type":"conversation","confidence":0.9}]}'
        ])
        service = ProfileService(self.storage, model)
        service.extract_and_update("conflict", "我每天30分钟")
        result = service.extract_and_update("conflict", "最近我每天1小时")

        self.assertEqual(result["profile"]["record_map"]["daily_time"]["status"], "conflict")
        self.assertEqual(result["profile"]["changes"][0]["reason"], "conflicting_evidence")


if __name__ == "__main__":
    unittest.main()
