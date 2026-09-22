"""Tests for AUREX AI Router and cost optimization dispatching."""

import unittest
from app.core.ai_router import AIRouter, RouteTarget
from app.config.settings import get_settings


class TestAIRouter(unittest.TestCase):
    def setUp(self):
        self.router = AIRouter()
        self.router.set_online_override(True)
        self.settings = get_settings()
        self._orig_mode = self.settings.privacy_mode
        self.settings.set("privacy_mode", "balanced")

    def tearDown(self):
        self.router.set_online_override(None)
        self.settings.set("privacy_mode", self._orig_mode)

    def test_local_app_and_system_commands(self):
        # Application control must route to LOCAL (zero cloud token cost)
        target, meta = self.router.classify_request("open Chrome")
        self.assertEqual(target, RouteTarget.LOCAL)
        self.assertEqual(meta.get("cost"), "$0.00")

        # Telemetry commands
        target, meta = self.router.classify_request("what is my RAM usage?")
        self.assertEqual(target, RouteTarget.LOCAL)
        self.assertEqual(meta.get("cost"), "$0.00")

        # Workspace commands
        target, meta = self.router.classify_request("create folder my_test")
        self.assertEqual(target, RouteTarget.LOCAL)

        # Personal memory retrieval
        target, meta = self.router.classify_request("where is my OS project?")
        self.assertEqual(target, RouteTarget.LOCAL)

    def test_general_reasoning_to_groq(self):
        target, meta = self.router.classify_request("Explain how quantum computing differs from classical computing")
        self.assertEqual(target, RouteTarget.GROQ)

    def test_internet_search_queries(self):
        target, meta = self.router.classify_request("search the web for Python 3.14 release dates")
        self.assertEqual(target, RouteTarget.INTERNET)

    def test_privacy_mode_forces_local_zero_cloud(self):
        # When in private mode, ANY query must be forced to LOCAL
        self.settings.set("privacy_mode", "private")

        target, meta = self.router.classify_request("Explain quantum physics")
        self.assertEqual(target, RouteTarget.LOCAL)
        self.assertIn("Private Mode", meta.get("reason", ""))

        target2, meta2 = self.router.classify_request("search the web for news")
        self.assertEqual(target2, RouteTarget.LOCAL)


if __name__ == "__main__":
    unittest.main()
