"""Offline tests for the local meeting UI server."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, Mock

from fastapi import HTTPException

import webapp


class WebAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_identity_query_cannot_enable_removed_module(self):
        socket=Mock(headers={'host':'127.0.0.1:8000'},query_params={'target':'zh','topic':'indoor','speakers':'true'})
        socket.accept=AsyncMock();socket.close=AsyncMock();socket.send_json=AsyncMock()
        session=Mock(run=AsyncMock())
        with patch('meeting.MeetingSession',return_value=session) as factory:
            await webapp.meeting_socket(socket)
        self.assertEqual(factory.call_args.kwargs,{'audio_mode':'room'})
        session.run.assert_awaited_once()
        self.assertFalse(Path('speakers.py').exists())

    async def test_health_and_languages(self):
        health = await webapp.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["model"], "gpt-live-transcribe → gpt-4.1-mini")
        supported = await webapp.languages()
        self.assertEqual(supported["languages"]["zh"], "中文")
        self.assertEqual(len(supported["languages"]), 13)

    async def test_unknown_language_is_rejected_before_network(self):
        with self.assertRaises(HTTPException) as raised:
            await webapp.create_session(webapp.SessionRequest(target_language="xx"))
        self.assertEqual(raised.exception.status_code, 400)

    async def test_missing_api_key_has_clear_error(self):
        with patch.object(webapp, "OPENAI_API_KEY", ""):
            with self.assertRaises(HTTPException) as raised:
                await webapp.create_session(webapp.SessionRequest(target_language="zh"))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("OPENAI_API_KEY", raised.exception.detail)

        with patch.object(webapp, "OPENAI_API_KEY", ""):
            with self.assertRaises(HTTPException) as raised:
                await webapp.create_transcription_session(
                    webapp.TranscriptionSessionRequest(source_language="en")
                )
        self.assertEqual(raised.exception.status_code, 503)

    def test_error_parser_and_pseudonymous_safety_id(self):
        self.assertEqual(
            webapp._openai_error(b'{"error":{"message":"bad request"}}', "fallback"),
            "bad request",
        )
        self.assertEqual(webapp._openai_error(b"not json", "fallback"), "fallback")
        self.assertEqual(len(webapp._safety_identifier()), 64)

    def test_client_secret_request_enables_source_transcript(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"value":"short-lived"}'

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return Response()

        with patch.object(webapp, "OPENAI_API_KEY", "test-key"), patch.object(
            webapp, "urlopen", side_effect=fake_urlopen
        ):
            response = webapp._create_client_secret("zh")

        audio = captured["body"]["session"]["audio"]
        self.assertEqual(response["value"], "short-lived")
        self.assertEqual(audio["output"]["language"], "zh")
        self.assertEqual(audio["input"]["transcription"]["model"], "gpt-realtime-whisper")
        self.assertEqual(audio["input"]["noise_reduction"]["type"], "far_field")
        self.assertEqual(captured["timeout"], 15)

    def test_dedicated_transcription_secret_uses_live_asr(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"value":"asr-secret"}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            return Response()

        with patch.object(webapp, "OPENAI_API_KEY", "test-key"), patch.object(
            webapp, "urlopen", side_effect=fake_urlopen
        ):
            response = webapp._create_transcription_client_secret("auto")

        session = captured["body"]["session"]
        audio = session["audio"]["input"]
        self.assertEqual(response["value"], "asr-secret")
        self.assertEqual(session["type"], "transcription")
        self.assertEqual(audio["transcription"]["model"], "gpt-live-transcribe")
        self.assertNotIn("languages", audio["transcription"])
        self.assertIn("Japanese and English", audio["transcription"]["prompt"])
        self.assertIsNone(audio["turn_detection"])
        self.assertTrue(audio["transcription"]["keywords"])
        self.assertTrue(captured["url"].endswith("/v1/realtime/client_secrets"))

    def test_browser_ui_keeps_source_visible_without_translation(self):
        html = Path("static/index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="sourceLanguage"', html)
        self.assertIn("日英自动识别", html)
        self.assertNotIn('class="participant', html)
        self.assertIn('/static/meeting-ui.js', html)
        self.assertIn('id="topicSelect"', html)
        self.assertIn('id="glossaryDialog"', html)


if __name__ == "__main__":
    unittest.main()
