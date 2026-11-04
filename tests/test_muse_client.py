"""Focused regression tests for the optimized MuseClient (no network)."""

import json
import unittest
from unittest.mock import MagicMock

from verso.services.muse_client import (
    _is_vocal_approval,
    _parse_json_object,
    _truncate,
    MuseClient,
)


def _mock_chat_response(content, usage=None):
    resp = MagicMock()
    payload = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        payload["usage"] = usage
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class ApprovalDetectionTest(unittest.TestCase):
    def test_plain_approval(self):
        self.assertTrue(_is_vocal_approval("Yes"))
        self.assertTrue(_is_vocal_approval("Sounds good, send it"))

    def test_no_substring_false_positive(self):
        # "go" must not match inside "good".
        self.assertFalse(_is_vocal_approval("This looks good overall"))

    def test_custom_instruction_is_not_approval(self):
        self.assertFalse(_is_vocal_approval("Make it shorter and friendlier"))


class InputHandlingTest(unittest.TestCase):
    def test_truncate_bounds_input(self):
        self.assertEqual(_truncate("hello"), "hello")
        self.assertLessEqual(len(_truncate("x" * 5000)), 1501)

    def test_parse_json_tolerates_fences(self):
        self.assertEqual(_parse_json_object('{"a": 1}'), {"a": 1})
        self.assertEqual(_parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})


class MuseClientTest(unittest.TestCase):
    def test_approval_makes_zero_http_calls(self):
        session = MagicMock()
        client = MuseClient(api_key="k", endpoint="https://api.meta.ai/v1", session=session)
        self.assertEqual(client.finalize_response("incoming", "MY DRAFT", "Yes, perfect"), "MY DRAFT")
        session.post.assert_not_called()

    def test_suggestion_uses_tuned_params_and_cache(self):
        session = MagicMock()
        session.post.return_value = _mock_chat_response(
            json.dumps({
                "spoken_intro": "intro",
                "spoken_suggestion": "sugg?",
                "suggested_reply": "reply",
            }),
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        client = MuseClient(api_key="k", endpoint="https://api.meta.ai/v1", session=session)
        first = client.generate_vocal_suggestion("From Leo: hello")
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.3)
        self.assertEqual(payload["max_tokens"], 300)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(first["suggested_reply"], "reply")
        # Identical request is served from cache: still exactly one HTTP call.
        self.assertEqual(client.generate_vocal_suggestion("From Leo: hello"), first)
        self.assertEqual(session.post.call_count, 1)

    def test_api_failure_falls_back_without_raising(self):
        session = MagicMock()
        session.post.side_effect = Exception("boom")
        client = MuseClient(api_key="k", endpoint="https://api.meta.ai/v1", session=session)
        suggestion = client.generate_vocal_suggestion("From Zoe: hi")
        self.assertEqual(suggestion["sender"], "Zoe")
        self.assertIn("suggested_reply", suggestion)
        final = client.finalize_response("m", "d", "Rewrite formally please")
        self.assertIn("Rewrite formally please", final)


if __name__ == "__main__":
    unittest.main()
