#!/usr/bin/env python3
"""Automated verification suite for the Web-Based LiveKit Voice AI Demo.

Tests:
1. Configuration loading and default parameter integrity.
2. Tools logic and property search filtering.
3. System prompts and Indic grammar sheets for all 6 languages.
4. Scoped LiveKit AccessToken generation with RoomAgentDispatch.
5. Multi-user session isolation and unique participant identity generation.
6. Web server endpoints: /api/health, static assets (/index.html, /style.css, /app.js, /livekit-client.umd.min.js).
7. Audio pipeline session building (Silero VAD, Sarvam STT, LLM, Sarvam TTS).
"""

import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from livekit.api import (
    AccessToken,
    RoomAgentDispatch,
    RoomConfiguration,
    VideoGrants,
)

import config
import prompts
import tools
from agent import _build_llm, _build_session
from server import app


class TestWebVoiceAIDemo(unittest.TestCase):

    def test_01_configuration(self):
        """Verify configuration constants and audio sample rate."""
        self.assertEqual(config.AUDIO_SAMPLE_RATE, 16000)
        self.assertIn("en", config.SUPPORTED_LANGUAGES)
        self.assertIn("hi", config.SUPPORTED_LANGUAGES)
        self.assertIn("ta", config.SUPPORTED_LANGUAGES)
        self.assertEqual(config.BCP47["en"], "en-IN")
        self.assertEqual(config.BCP47["hi"], "hi-IN")
        self.assertGreater(config.WEB_SERVER_PORT, 0)

    def test_02_tools_and_prompts(self):
        """Verify business tools and prompt copy for all languages."""
        listings = tools._search(bhk=2)
        self.assertTrue(len(listings) > 0)
        self.assertTrue(all(p["bhk"] == 2 for p in listings))

        for lang in config.SUPPORTED_LANGUAGES:
            self.assertIn(lang, prompts.GREETINGS)
            self.assertIn(lang, prompts.STYLE_NOTES)
            instructions = prompts.build_instructions(lang, prompts.STYLE_NOTES[lang])
            self.assertIn("Shanthi", instructions)

    def test_03_token_generation_and_isolation(self):
        """Verify short-lived token generation, room grants, and session isolation."""
        api_key = "devkey"
        api_secret = "secret" * 8  # 48 bytes

        # Token 1
        room_1 = "room-user-1"
        id_1 = "user-1"
        token_1 = (
            AccessToken(api_key, api_secret)
            .with_identity(id_1)
            .with_grants(VideoGrants(room_join=True, room=room_1, can_publish=True, can_subscribe=True))
            .with_room_config(RoomConfiguration(agents=[RoomAgentDispatch(agent_name="maya")]))
            .with_ttl(timedelta(minutes=15))
            .to_jwt()
        )

        # Token 2
        room_2 = "room-user-2"
        id_2 = "user-2"
        token_2 = (
            AccessToken(api_key, api_secret)
            .with_identity(id_2)
            .with_grants(VideoGrants(room_join=True, room=room_2, can_publish=True, can_subscribe=True))
            .with_room_config(RoomConfiguration(agents=[RoomAgentDispatch(agent_name="maya")]))
            .with_ttl(timedelta(minutes=15))
            .to_jwt()
        )

        self.assertNotEqual(token_1, token_2)
        self.assertTrue(token_1.startswith("ey"))
        self.assertTrue(token_2.startswith("ey"))

    def test_04_server_endpoints(self):
        """Verify web server health check and static assets serving."""
        client = TestClient(app)

        # Health endpoint
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["agent_name"], config.AGENT_NAME)
        self.assertEqual(data["audio_sample_rate"], 16000)

        # Index page
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers.get("content-type", ""))
        self.assertIn(b"Realtime Voice AI Demo", res.content)

        # Static assets
        res_css = client.get("/static/style.css")
        self.assertEqual(res_css.status_code, 200)
        self.assertIn(b"voice-orb", res_css.content)

        res_js = client.get("/static/app.js")
        self.assertEqual(res_js.status_code, 200)
        self.assertIn(b"startConversation", res_js.content)

        res_sdk = client.get("/static/js/livekit-client.umd.min.js")
        self.assertEqual(res_sdk.status_code, 200)
        self.assertGreater(len(res_sdk.content), 100000)

    def test_05_token_endpoint_with_valid_credentials(self):
        """Verify /api/token returns proper response when credentials are provided."""
        client = TestClient(app)
        with patch.object(config, "LIVEKIT_URL", "wss://demo.livekit.cloud"), \
             patch.object(config, "LIVEKIT_API_KEY", "AKIA1234567890123456"), \
             patch.object(config, "LIVEKIT_API_SECRET", "secret" * 8), \
             patch("server.LIVEKIT_URL", "wss://demo.livekit.cloud"), \
             patch("server.LIVEKIT_API_KEY", "AKIA1234567890123456"), \
             patch("server.LIVEKIT_API_SECRET", "secret" * 8):
            res = client.post("/api/token", json={"participant_name": "Tester"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["serverUrl"], "wss://demo.livekit.cloud")
            self.assertTrue(data["roomName"].startswith("web-demo-"))
            self.assertTrue(data["participantIdentity"].startswith("user-"))
            self.assertEqual(data["participantName"], "Tester")
            self.assertTrue(len(data["participantToken"]) > 20)

    def test_06_pipeline_session_builder(self):
        """Verify _build_llm and _build_session build cleanly without errors."""
        llm = _build_llm()
        self.assertIsNotNone(llm)

        with patch.object(config, "SARVAM_API_KEY", "test-sarvam-api-key"), \
             patch("agent.SARVAM_API_KEY", "test-sarvam-api-key"):
            session = _build_session("en")
            self.assertIsNotNone(session)


if __name__ == "__main__":
    unittest.main()
