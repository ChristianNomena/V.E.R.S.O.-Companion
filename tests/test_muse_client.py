"""Focused regression tests for the optimized MuseClient (no network)."""

import json
import unittest
from unittest.mock import MagicMock

from verso.services.muse_client import (
    _extract_output_text,
    _is_vocal_approval,
    _parse_json_object,
    _truncate,
    MuseClient,
)

TEST_MODEL = "muse-wonder-1.0"


def _mock_responses_body(text, usage=None):
    body = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}
        ]
    }
    if usage is not None:
        body["usage"] = usage
    resp = MagicMock()
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


def _mock_stream_response(deltas):
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/event-stream"}
    resp.raise_for_status.return_value = None
    lines = [
        "data: " + json.dumps({"type": "response.output_text.delta", "delta": d})
        for d in deltas
    ]
    lines.append("data: [DONE]")
    resp.iter_lines.return_value = lines
    return resp


def _make_client(session):
    return MuseClient(
        api_key="k",
        endpoint="https://api.meta.ai/v1",
        model_name=TEST_MODEL,
        session=session,
    )


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


class OutputExtractionTest(unittest.TestCase):
    def test_responses_shape(self):
        data = {
            "output": [
                {"type": "reasoning", "content": []},
                {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
            ]
        }
        self.assertEqual(_extract_output_text(data), "hello")

    def test_legacy_chat_shape_fallback(self):
        data = {"choices": [{"message": {"content": "legacy text"}}]}
        self.assertEqual(_extract_output_text(data), "legacy text")

    def test_empty_output_raises(self):
        with self.assertRaises(ValueError):
            _extract_output_text({"output": []})


class MuseClientTest(unittest.TestCase):
    def test_responses_endpoint_url(self):
        client = _make_client(MagicMock())
        self.assertEqual(client.responses_endpoint, "https://api.meta.ai/v1/responses")

    def test_legacy_chat_url_is_migrated(self):
        session = MagicMock()
        client = MuseClient(
            api_key="k",
            endpoint="https://api.meta.ai/v1/chat/completions",
            model_name=TEST_MODEL,
            session=session,
        )
        self.assertEqual(client.responses_endpoint, "https://api.meta.ai/v1/responses")

    def test_approval_makes_zero_http_calls(self):
        session = MagicMock()
        client = _make_client(session)
        self.assertEqual(client.finalize_response("incoming", "MY DRAFT", "Yes, perfect"), "MY DRAFT")
        session.post.assert_not_called()

    def test_suggestion_follows_official_responses_format(self):
        session = MagicMock()
        session.post.return_value = _mock_responses_body(
            json.dumps({
                "spoken_intro": "intro",
                "spoken_suggestion": "sugg?",
                "suggested_reply": "reply",
            }),
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        client = _make_client(session)
        first = client.generate_vocal_suggestion("From Leo: hello")

        # Transport assertions: official /v1/responses example shape.
        url = session.post.call_args.args[0]
        self.assertEqual(url, "https://api.meta.ai/v1/responses")
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], TEST_MODEL)
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["temperature"], 0.3)
        self.assertEqual(payload["max_output_tokens"], 800)
        self.assertNotIn("messages", payload)
        self.assertNotIn("response_format", payload)
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(
            [(item["role"], item["content"][0]["type"]) for item in payload["input"]],
            [("system", "input_text"), ("user", "input_text")],
        )
        self.assertEqual(first["suggested_reply"], "reply")
        # Identical request is served from cache: still exactly one HTTP call.
        self.assertEqual(client.generate_vocal_suggestion("From Leo: hello"), first)
        self.assertEqual(session.post.call_count, 1)

    def test_finalize_uses_capped_output_tokens(self):
        session = MagicMock()
        session.post.return_value = _mock_responses_body("  Final text  ")
        client = _make_client(session)
        self.assertEqual(client.finalize_response("incoming", "draft", "Rewrite it formally"), "Final text")
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["max_output_tokens"], 800)
        self.assertIs(payload["stream"], False)

    def test_generate_quick_replies(self):
        session = MagicMock()
        session.post.return_value = _mock_responses_body(
            '{"summary": "Leo asked about the demo", "options": ["Option 1", "Option 2", "Option 3"]}'
        )
        client = _make_client(session)
        qr = client.generate_quick_replies("Leo: Can we do the demo tomorrow?")
        self.assertEqual(qr["sender"], "Leo")
        self.assertEqual(len(qr["options"]), 3)
        self.assertEqual(qr["options"][0], "Option 1")

    def test_ask_companion_streams_deltas(self):
        session = MagicMock()
        session.post.return_value = _mock_stream_response(["Hello ", "streamed ", "world"])
        client = _make_client(session)
        collected = []
        answer = client.ask_companion(
            "[10:00] Code - app.py", "What do you think?", on_delta=collected.append
        )
        self.assertEqual(answer, "Hello streamed world")
        self.assertEqual("".join(collected), "Hello streamed world")
        payload = session.post.call_args.kwargs["json"]
        self.assertIs(payload["stream"], True)

    def test_ask_companion_stream_failure_falls_back_to_plain_request(self):
        session = MagicMock()
        session.post.side_effect = [
            Exception("stream boom"),
            _mock_responses_body("Plain answer"),
        ]
        client = _make_client(session)
        collected = []
        answer = client.ask_companion(
            "[10:00] Code - app.py", "What do you think?", on_delta=collected.append
        )
        self.assertEqual(answer, "Plain answer")
        self.assertEqual(session.post.call_count, 2)
        self.assertIs(session.post.call_args.kwargs["json"]["stream"], False)

    def test_transcribe_audio_posts_multipart_and_returns_transcript(self):
        import os
        import tempfile

        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"transcript": "  Hello transcribed world  "}
        session.post.return_value = resp
        client = _make_client(session)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"RIFFfake-wav-bytes")
            wav_path = tmp.name
        try:
            text = client.transcribe_audio(wav_path)
        finally:
            os.unlink(wav_path)

        self.assertEqual(text, "Hello transcribed world")
        url = session.post.call_args.args[0]
        self.assertEqual(url, "https://api.meta.ai/v1/asr/transcribe")
        files = session.post.call_args.kwargs["files"]
        request_part = files["request"][1]
        import json as json_module

        request_json = json_module.loads(request_part)
        self.assertEqual(request_json["model"], "muse-voice-transcribe-1.0")
        self.assertEqual(request_json["audioEncoding"], "WAV")
        self.assertIn("audio", files)

    def test_api_failure_falls_back_without_raising(self):
        session = MagicMock()
        session.post.side_effect = Exception("boom")
        client = _make_client(session)
        suggestion = client.generate_vocal_suggestion("From Zoe: hi")
        self.assertEqual(suggestion["sender"], "Zoe")
        self.assertIn("suggested_reply", suggestion)
        final = client.finalize_response("m", "d", "Rewrite formally please")
        self.assertIn("Rewrite formally please", final)


if __name__ == "__main__":
    unittest.main()
