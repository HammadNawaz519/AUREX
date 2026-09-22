"""Tests for natural language correction detection and preference learning."""

import unittest
from app.learning.correction_learner import CorrectionLearner
from app.memory.memory_manager import MemoryManager
from app.core.context import get_context, ConversationTurn


class TestCorrections(unittest.TestCase):
    def setUp(self):
        self.learner = CorrectionLearner()
        self.mm = MemoryManager()
        self.ctx = get_context()
        self.ctx.clear()

    def test_path_correction(self):
        # Simulate prior turn where AUREX guessed the wrong path
        self.ctx.add_turn(
            user_input="open my OS project",
            agent_response="Opened D:\\Projects\\General",
            tool_data="D:\\Projects\\General"
        )

        is_corr, msg = self.learner.inspect_for_correction("No, I mean D:\\OS")
        self.assertTrue(is_corr)
        self.assertIn("D:\\OS", msg)

        # Verify location mapping was updated in memory
        mapping = self.mm.get_location_mapping("my OS project")
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping, "D:\\OS")

    def test_browser_app_correction(self):
        is_corr, msg = self.learner.inspect_for_correction("No, use Firefox")
        self.assertTrue(is_corr)
        self.assertIn("Firefox", msg)

        pref = self.mm.get_preference("preferred_browser")
        self.assertEqual(pref, "firefox")

    def test_explicit_preference(self):
        is_corr, msg = self.learner.inspect_for_correction("I prefer VS Code")
        self.assertTrue(is_corr)
        self.assertIn("VS Code", msg)

        pref = self.mm.get_preference("user_preference")
        self.assertEqual(pref, "VS Code")


if __name__ == "__main__":
    unittest.main()
