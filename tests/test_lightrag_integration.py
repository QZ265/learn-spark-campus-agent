import tempfile
import unittest
from pathlib import Path

from services.lightrag.course_registry import custom_workspace, validate_workspace
from services.lightrag.indexing_service import IndexingService
from services.lightrag.retrieval_service import REFUSAL, RetrievalService
from services.storage import AppStorage


class FakeLightRAGClient:
    available = True

    def __init__(self):
        self.documents = {}

    def insert_document(self, workspace, document_id, text, file_path, force=False):
        self.documents.setdefault(workspace, {})[document_id] = {"text": text, "file_path": file_path}
        return "track-test"

    def query_chunks(self, workspace, query, top_k=6):
        return [
            {
                "chunk_id": f"chunk-{document_id}",
                "document_id": document_id,
                "content": record["text"],
                "file_path": record["file_path"],
                "relevance": 0.91,
            }
            for document_id, record in list(self.documents.get(workspace, {}).items())[:top_k]
        ]


class LowScoreClient:
    def query_chunks(self, workspace, query, top_k=6):
        return [{"chunk_id": "x", "document_id": "missing", "content": "无关", "relevance": 0.2}]


class LightRAGIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.storage = AppStorage(self.root / "app.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_same_file_is_isolated_by_workspace_and_duplicate_blocked_within_workspace(self):
        source = self.root / "lesson.txt"
        source.write_text("列表用于按顺序保存多个元素。\n元组创建后不能直接修改。", encoding="utf-8")
        client = FakeLightRAGClient()
        service = IndexingService(self.storage, client, self.root)
        first = service.enqueue_source(source, "course_a", "course_a")
        second = service.enqueue_source(source, "course_b", "course_b")
        first_job = service.wait(first["job"]["job_id"], timeout=5)
        second_job = service.wait(second["job"]["job_id"], timeout=5)
        self.assertEqual(first_job["status"], "completed")
        self.assertEqual(second_job["status"], "completed")
        self.assertNotEqual(first["document"]["document_id"], second["document"]["document_id"])
        duplicate = service.enqueue_source(source, "course_a", "course_a")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["job"]["stage"], "sha256_duplicate_blocked")

    def test_profiles_are_isolated_by_course(self):
        record = {
            "field": "learning_goal", "value": "掌握列表", "evidence": "我要掌握列表",
            "source_type": "conversation", "confidence": 0.9,
            "updated_at": "2026-01-01T00:00:00+00:00", "status": "confirmed",
        }
        self.storage.save_profile_record("u1", record, "new_evidence", "programming_python")
        self.assertIn("learning_goal", self.storage.get_profile_records("u1", "programming_python"))
        self.assertNotIn("learning_goal", self.storage.get_profile_records("u1", "math_calculus"))

    def test_low_relevance_query_refuses_without_model_call(self):
        called = []
        service = RetrievalService(self.storage, LowScoreClient(), lambda *args: called.append(args))
        result = service.answer("u1", "programming_python", "programming_python", "无关问题")
        self.assertEqual(result["answer"], REFUSAL)
        self.assertFalse(called)

    def test_custom_workspace_is_safe_and_deterministic(self):
        workspace = custom_workspace("student-01", "asst_123")
        self.assertEqual(workspace, "user_student01_asst123")
        self.assertEqual(validate_workspace(workspace), workspace)
        with self.assertRaises(ValueError):
            validate_workspace("../other")


if __name__ == "__main__":
    unittest.main()
