"""Tests for local persistent SQLite memory, preferences, and aliases."""

import unittest
from app.memory.memory_manager import MemoryManager


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.mm = MemoryManager()

    def test_preferences_lifecycle(self):
        self.mm.set_preference("preferred_editor", "VS Code")
        self.assertEqual(self.mm.get_preference("preferred_editor"), "VS Code")

        # Update
        self.mm.set_preference("preferred_editor", "PyCharm")
        self.assertEqual(self.mm.get_preference("preferred_editor"), "PyCharm")

        # Delete
        self.assertTrue(self.mm.delete_preference("preferred_editor"))
        self.assertIsNone(self.mm.get_preference("preferred_editor"))

    def test_aliases_resolution(self):
        self.mm.add_alias("coding", "open VS Code and D:\\Projects")

        resolved = self.mm.resolve_alias("coding")
        self.assertEqual(resolved, "open VS Code and D:\\Projects")

        # Case insensitivity
        self.assertEqual(self.mm.resolve_alias("CODING"), "open VS Code and D:\\Projects")

        # Clean up
        self.mm.delete_alias("coding")
        self.assertIsNone(self.mm.resolve_alias("coding"))

    def test_conversation_history(self):
        self.mm.clear_history()

        self.mm.add_history("user", "Hello Aurex")
        self.mm.add_history("assistant", "Hello. How can I assist you?")

        recent = self.mm.get_recent_history(limit=5)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["content"], "Hello Aurex")
        self.assertEqual(recent[1]["content"], "Hello. How can I assist you?")


if __name__ == "__main__":
    unittest.main()
