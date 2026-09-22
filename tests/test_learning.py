"""Tests for AUREX pattern detector, confidence scoring, and safety filter."""

import unittest
from app.learning.pattern_detector import PatternDetector
from app.memory.memory_manager import MemoryManager


class TestLearning(unittest.TestCase):
    def setUp(self):
        self.detector = PatternDetector()
        self.mm = MemoryManager()

    def test_confidence_calculation(self):
        # Confidence should increase with repetition count
        conf_1 = self.detector.calculate_confidence(repetitions=1, days_span=1, recent_hits=1)
        conf_3 = self.detector.calculate_confidence(repetitions=3, days_span=1, recent_hits=2)
        conf_8 = self.detector.calculate_confidence(repetitions=8, days_span=5, recent_hits=5)

        self.assertGreater(conf_3, conf_1)
        self.assertGreater(conf_8, conf_3)
        self.assertLessEqual(conf_8, 0.98)
        self.assertGreaterEqual(conf_1, 0.10)

    def test_safety_filter_rejects_destructive_actions(self):
        # Safe sequence: launch editor, open terminal
        safe_actions = ["open VS Code", "open Terminal", "open D:\\Projects"]
        self.assertTrue(self.detector.is_safe_sequence(safe_actions))

        # Destructive sequence: deletion
        delete_actions = ["open VS Code", "delete D:\\Projects\\temp.py"]
        self.assertFalse(self.detector.is_safe_sequence(delete_actions))

        # Destructive sequence: formatting or system tampering
        format_actions = ["format D:", "clean drive"]
        self.assertFalse(self.detector.is_safe_sequence(format_actions))

        # Destructive sequence: C: drive write/touch
        c_drive_actions = ["modify C:\\Windows\\System32", "create C:\\test.txt"]
        self.assertFalse(self.detector.is_safe_sequence(c_drive_actions))

    def test_candidate_routine_requires_approval(self):
        # Record repeated actions
        for _ in range(4):
            self.detector.record_action("open VS Code", category="application")
            self.detector.record_action("open Terminal", category="application")

        candidates = self.detector.detect_candidate_routines()
        # Any candidate routine produced must be PROPOSED, never automated without approval
        for c in candidates:
            self.assertEqual(c["status"], "PROPOSED")
            self.assertGreaterEqual(c["confidence"], 0.20)


if __name__ == "__main__":
    unittest.main()
