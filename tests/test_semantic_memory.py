"""Tests for AUREX local offline semantic memory and vector retrieval."""

import unittest
from app.memory.semantic_memory import SemanticMemory
from app.memory.memory_manager import MemoryManager


class TestSemanticMemory(unittest.TestCase):
    def setUp(self):
        self.sm = SemanticMemory()
        self.mm = MemoryManager()

    def test_semantic_routine_matching(self):
        # Register a routine in memory
        self.mm.save_routine(
            name="Morning Coding Setup",
            trigger_type="phrase",
            trigger_desc="start my daily coding session",
            action_sequence=["open VS Code", "open Terminal"],
            confidence=0.90,
            status="APPROVED"
        )

        # Query with varied phrasing
        match = self.sm.search_routines("start coding session")
        self.assertIsNotNone(match)
        self.assertEqual(match["name"], "Morning Coding Setup")
        self.assertGreater(match["match_score"], 0.3)

    def test_semantic_location_matching(self):
        # Register a location mapping
        self.mm.set_location_mapping(
            natural_name="Operating System Kernel Project",
            resolved_path="D:\\OS_Dev",
            confidence=0.95
        )

        # Query with natural fuzzy phrasing
        path = self.sm.search_locations("where is my Operating System Kernel")
        self.assertEqual(path, "D:\\OS_Dev")


if __name__ == "__main__":
    unittest.main()
