"""Tests for command validation and dangerous syntax blocking."""

import unittest
from app.core.validator import CommandValidator


class TestValidator(unittest.TestCase):
    def test_dangerous_commands_permanently_blocked(self):
        blocked_commands = [
            "format D: /FS:NTFS",
            "diskpart /s script.txt",
            "cipher /w:C:",
            "bcdedit /set {default} bootstatuspolicy ignoreallfailures",
            "reg delete HKLM\\Software\\Policies /f",
            "del C:\\Windows\\System32\\calc.exe",
            "rmdir /s /q C:\\Users",
            "Remove-Item -Recurse C:\\Windows",
            "Set-MpPreference -DisableRealtimeMonitoring $true",
            "net stop WinDefend",
            "mimikatz",
        ]
        for cmd in blocked_commands:
            allowed, reason, req_confirm = CommandValidator.validate(cmd)
            self.assertFalse(allowed, f"Command '{cmd}' should have been BLOCKED!")
            self.assertIn("ACCESS DENIED", reason)

    def test_command_redirection_to_c_drive_blocked(self):
        blocked_redirects = [
            "echo test > C:\\Windows\\temp.txt",
            "Get-Process > C:\\out.log",
        ]
        for cmd in blocked_redirects:
            allowed, reason, _ = CommandValidator.validate(cmd)
            self.assertFalse(allowed, f"Redirect to C: '{cmd}' should have been BLOCKED!")

    def test_safe_commands_allowed_with_confirmation(self):
        safe_commands = [
            "Get-Process",
            "dir D:\\AUREX",
            "python --version",
            "git status",
        ]
        for cmd in safe_commands:
            allowed, reason, req_confirm = CommandValidator.validate(cmd)
            self.assertTrue(allowed, f"Safe command '{cmd}' should be allowed: {reason}")
            self.assertTrue(req_confirm)


if __name__ == "__main__":
    unittest.main()
