import unittest
from unittest.mock import Mock, patch

from services.astron_agent_client import AstronAgentClient


class AstronAgentClientTest(unittest.TestCase):
    def test_unconfigured_client_reports_failure(self):
        client = AstronAgentClient(api_key="", agent_id="")
        result = client.invoke("profile", "u1", {})
        self.assertFalse(result.ok)
        self.assertEqual(result.mode, "failed")

    @patch("services.astron_agent_client.requests.post")
    def test_official_workflow_request_and_auth(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "code": 0,
            "id": "request-1",
            "choices": [{"delta": {"content": '{"updates":[]}'}}],
            "workflow_step": {"progress": 1},
        }
        post.return_value = response
        client = AstronAgentClient(api_key="key:secret", agent_id="flow-id", retries=0)

        result = client.invoke("profile", "u1", {"student_message": "讲一下列表"})

        self.assertTrue(result.ok)
        request = post.call_args.kwargs
        self.assertEqual(request["headers"]["Authorization"], "Bearer key:secret")
        self.assertEqual(request["json"]["flow_id"], "flow-id")
        self.assertEqual(request["json"]["parameters"]["TASK"], "profile")

    @patch("services.astron_agent_client.time.sleep")
    @patch("services.astron_agent_client.requests.post")
    def test_retry_then_success(self, post, sleep):
        failed = Mock()
        failed.raise_for_status.side_effect = RuntimeError("temporary")
        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {
            "code": 0,
            "choices": [{"delta": {"content": "ok"}}],
        }
        post.side_effect = [failed, success]
        client = AstronAgentClient(api_key="key:secret", agent_id="flow-id", retries=1)

        result = client.invoke("review", "u1", {})

        self.assertTrue(result.ok)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
