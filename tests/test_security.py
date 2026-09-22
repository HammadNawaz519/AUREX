"""Tests for AUREX Security and strict C: drive write protection."""

import os
import unittest
from pathlib import Path
from app.core.security import is_path_allowed, canonical_path, is_c_drive, PathSecurityError, check_path_security


class TestSecurity(unittest.TestCase):
    def test_direct_c_drive_write_blocked(self):
        """Verify write operations to C: drive are strictly rejected."""
        paths = [
            r"C:\Windows\System32\cmd.exe",
            r"C:\test.txt",
            r"C:\Users\Public\file.log",
            r"c:\temp\script.bat",
            r"C:/Windows/notepad.exe",
            r"c:/folder/file.py",
        ]
        for p in paths:
            allowed, reason = is_path_allowed(p, is_write=True)
            self.assertFalse(allowed, f"Path '{p}' should have been blocked!")
            self.assertIn("AUREX is not permitted to modify the C: drive", reason)

    def test_extended_unc_device_namespace_c_blocked(self):
        """Verify Windows device prefixes (\\\\?\\C:\\, \\\\.\\C:\\) targeting C: are blocked."""
        paths = [
            r"\\?\C:\test.txt",
            r"\\.\C:\Windows\System32",
            r"//?/C:/test.txt",
            r"\\?\c:\Users\test.doc",
        ]
        for p in paths:
            allowed, reason = is_path_allowed(p, is_write=True)
            self.assertFalse(allowed, f"Device namespace path '{p}' should have been blocked!")
            self.assertIn("AUREX is not permitted to modify the C: drive", reason)

    def test_path_traversal_to_c_drive_blocked(self):
        """Verify traversal attacks like D:\\AUREX\\..\\..\\Windows resolving to C: are blocked."""
        traversal_paths = [
            r"D:\AUREX\..\..\C:\Windows",
            r"D:\AUREX\..\..\..\..\C:\Windows\System32",
        ]
        for p in traversal_paths:
            allowed, reason = is_path_allowed(p, is_write=True)
            self.assertFalse(allowed, f"Traversal path '{p}' should have been blocked!")
            self.assertIn("AUREX is not permitted to modify the C: drive", reason)

    def test_nonexistent_c_drive_file_creation_blocked(self):
        """Ensure non-existent files intended for creation on C: are blocked."""
        nonexistent = r"C:\totally_new_folder_12345\new_file.txt"
        allowed, reason = is_path_allowed(nonexistent, is_write=True)
        self.assertFalse(allowed)
        self.assertIn("AUREX is not permitted to modify the C: drive", reason)

        with self.assertRaises(PathSecurityError):
            check_path_security(nonexistent, is_write=True)

    def test_approved_workspace_write_allowed(self):
        """Ensure operations inside approved workspace (D:\\AUREX) are permitted."""
        allowed_dirs = [r"D:\AUREX", r"D:\Projects"]
        valid_paths = [
            r"D:\AUREX\workspace\test.txt",
            r"D:\AUREX\downloads\report.pdf",
            r"D:\Projects\my_project\main.py",
        ]
        for p in valid_paths:
            allowed, reason = is_path_allowed(p, is_write=True, allowed_dirs=allowed_dirs)
            self.assertTrue(allowed, f"Path '{p}' in approved directory should be allowed: {reason}")

    def test_unapproved_directory_write_blocked(self):
        """Ensure paths outside approved workspace directories are rejected."""
        allowed_dirs = [r"D:\AUREX"]
        unapproved = r"D:\RandomUnapprovedFolder\file.txt"
        allowed, reason = is_path_allowed(unapproved, is_write=True, allowed_dirs=allowed_dirs)
        self.assertFalse(allowed)
        self.assertIn("outside approved workspace directories", reason)


if __name__ == "__main__":
    unittest.main()
