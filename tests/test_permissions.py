"""Tests for action permission classification (SAFE, CONFIRM, BLOCKED)."""

import unittest
from app.core.permissions import PermissionManager, ActionLevel, ActionRequest


class TestPermissions(unittest.TestCase):
    def test_permission_evaluation_safe_actions(self):
        pm = PermissionManager()
        req = pm.evaluate_action(
            action_type="open_application",
            target_paths=[],
            is_write=False
        )
        self.assertEqual(req.level, ActionLevel.SAFE)

    def test_permission_evaluation_confirm_actions(self):
        pm = PermissionManager()

        # Deletion requires confirmation
        req_del = pm.evaluate_action(
            action_type="delete_file",
            target_paths=[r"D:\AUREX\temp\file.tmp"],
            is_write=True
        )
        self.assertEqual(req_del.level, ActionLevel.CONFIRM)

        # Shell execution requires confirmation
        req_shell = pm.evaluate_action(
            action_type="execute_command",
            is_shell=True
        )
        self.assertEqual(req_shell.level, ActionLevel.CONFIRM)

    def test_permission_evaluation_blocked_c_drive(self):
        pm = PermissionManager()
        req = pm.evaluate_action(
            action_type="write_file",
            target_paths=[r"C:\Windows\System32\payload.dll"],
            is_write=True
        )
        self.assertEqual(req.level, ActionLevel.BLOCKED)
        self.assertIn("AUREX is not permitted to modify the C: drive", req.reason)


if __name__ == "__main__":
    unittest.main()
