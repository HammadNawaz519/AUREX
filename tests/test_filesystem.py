"""Tests for filesystem tools and operations."""

import os
import unittest
from pathlib import Path
from app.tools.filesystem import (
    WriteFileTool, ReadFileTool, CreateFolderTool,
    DeleteFileTool, ListDirectoryTool
)
from app.config.settings import get_settings


class TestFilesystem(unittest.TestCase):
    def test_write_and_read_file_in_workspace(self):
        settings = get_settings()
        root = Path(settings.workspace_root)
        test_file = root / "temp" / "unittest_file.txt"

        writer = WriteFileTool()
        reader = ReadFileTool()

        # Write
        write_res = writer.execute(path=str(test_file), content="Test content for AUREX.")
        self.assertTrue(write_res.success)
        self.assertTrue(test_file.exists())

        # Read
        read_res = reader.execute(path=str(test_file))
        self.assertTrue(read_res.success)
        self.assertEqual(read_res.data, "Test content for AUREX.")

        # Delete
        deleter = DeleteFileTool()
        del_res = deleter.execute(path=str(test_file))
        self.assertTrue(del_res.success)
        self.assertFalse(test_file.exists())

    def test_c_drive_write_rejected(self):
        writer = WriteFileTool()
        res = writer.execute(path=r"C:\Windows\System32\malicious.txt", content="evil")
        self.assertFalse(res.success)
        self.assertIn("AUREX is not permitted to modify the C: drive", res.error)


if __name__ == "__main__":
    unittest.main()
