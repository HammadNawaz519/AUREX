"""Unified test runner using Python's standard library (unittest).

Validates all security policies, C: drive defenses, permissions,
filesystem tools, memory operations, and agent logic.
"""

import sys
import os
import unittest
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.core.security import is_path_allowed, canonical_path, PathSecurityError, check_path_security
from app.core.validator import CommandValidator
from app.core.permissions import PermissionManager, ActionLevel
from app.memory.memory_manager import MemoryManager
from app.tools.filesystem import WriteFileTool, ReadFileTool, CreateFolderTool, DeleteFileTool, ListDirectoryTool
from app.core.context import AgentContext
from app.core.agent import AurexAgent
from app.config.settings import get_settings


class TestSecurityAndCDrive(unittest.TestCase):
    def test_direct_c_drive_writes_blocked(self):
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

    def test_extended_unc_device_namespace_blocked(self):
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
        traversals = [
            r"D:\AUREX\..\..\C:\Windows",
            r"D:\AUREX\..\..\..\..\C:\Windows\System32",
        ]
        for p in traversals:
            allowed, reason = is_path_allowed(p, is_write=True)
            self.assertFalse(allowed, f"Traversal path '{p}' should have been blocked!")
            self.assertIn("AUREX is not permitted to modify the C: drive", reason)

    def test_nonexistent_c_drive_target_blocked(self):
        target = r"C:\new_folder_nonexistent_999\new_file.txt"
        allowed, reason = is_path_allowed(target, is_write=True)
        self.assertFalse(allowed)
        self.assertIn("AUREX is not permitted to modify the C: drive", reason)

        with self.assertRaises(PathSecurityError):
            check_path_security(target, is_write=True)

    def test_approved_workspace_allowed(self):
        allowed_dirs = [r"D:\AUREX", r"D:\Projects"]
        valid = [
            r"D:\AUREX\workspace\test.txt",
            r"D:\AUREX\downloads\report.pdf",
            r"D:\Projects\my_project\main.py",
        ]
        for p in valid:
            allowed, reason = is_path_allowed(p, is_write=True, allowed_dirs=allowed_dirs)
            self.assertTrue(allowed, f"Approved path '{p}' should be allowed: {reason}")

    def test_unapproved_directory_blocked(self):
        allowed_dirs = [r"D:\AUREX"]
        unapproved = r"D:\RandomUnapprovedFolder\file.txt"
        allowed, reason = is_path_allowed(unapproved, is_write=True, allowed_dirs=allowed_dirs)
        self.assertFalse(allowed)
        self.assertIn("outside approved workspace directories", reason)


class TestCommandValidator(unittest.TestCase):
    def test_dangerous_commands_blocked(self):
        blocked = [
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
        for cmd in blocked:
            allowed, reason, req_confirm = CommandValidator.validate(cmd)
            self.assertFalse(allowed, f"Command '{cmd}' should have been blocked!")
            self.assertIn("ACCESS DENIED", reason)

    def test_redirect_to_c_drive_blocked(self):
        redirects = [
            "echo test > C:\\Windows\\temp.txt",
            "Get-Process > C:\\out.log",
        ]
        for cmd in redirects:
            allowed, reason, _ = CommandValidator.validate(cmd)
            self.assertFalse(allowed, f"Redirect to C: '{cmd}' should have been blocked!")

    def test_safe_commands_allowed_with_confirmation(self):
        safe = [
            "Get-Process",
            "dir D:\\AUREX",
            "python --version",
        ]
        for cmd in safe:
            allowed, reason, req_confirm = CommandValidator.validate(cmd)
            self.assertTrue(allowed, f"Safe command '{cmd}' should be allowed: {reason}")
            self.assertTrue(req_confirm)


class TestPermissions(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager()

    def test_safe_classification(self):
        req = self.pm.evaluate_action("open_application", target_paths=[], is_write=False)
        self.assertEqual(req.level, ActionLevel.SAFE)

    def test_confirm_classification(self):
        req_del = self.pm.evaluate_action("delete_file", target_paths=[r"D:\AUREX\temp\file.tmp"], is_write=True)
        self.assertEqual(req_del.level, ActionLevel.CONFIRM)

        req_shell = self.pm.evaluate_action("execute_command", is_shell=True)
        self.assertEqual(req_shell.level, ActionLevel.CONFIRM)

    def test_blocked_classification(self):
        req = self.pm.evaluate_action("write_file", target_paths=[r"C:\Windows\System32\trojan.exe"], is_write=True)
        self.assertEqual(req.level, ActionLevel.BLOCKED)
        self.assertIn("AUREX is not permitted to modify the C: drive", req.reason)


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.mm = MemoryManager()

    def test_preferences(self):
        self.mm.set_preference("test_browser", "Chrome")
        self.assertEqual(self.mm.get_preference("test_browser"), "Chrome")
        self.assertTrue(self.mm.delete_preference("test_browser"))
        self.assertIsNone(self.mm.get_preference("test_browser"))

    def test_aliases(self):
        self.mm.add_alias("coding_test", "open VS Code")
        self.assertEqual(self.mm.resolve_alias("coding_test"), "open VS Code")
        self.assertEqual(self.mm.resolve_alias("CODING_TEST"), "open VS Code")
        self.mm.delete_alias("coding_test")
        self.assertIsNone(self.mm.resolve_alias("coding_test"))

    def test_history(self):
        self.mm.clear_history()
        self.mm.add_history("user", "Hello Aurex")
        self.mm.add_history("assistant", "I am ready.")
        hist = self.mm.get_recent_history(limit=5)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["content"], "Hello Aurex")
        self.assertEqual(hist[1]["content"], "I am ready.")


class TestFilesystemTools(unittest.TestCase):
    def setUp(self):
        self.settings = get_settings()
        self.writer = WriteFileTool()
        self.reader = ReadFileTool()
        self.deleter = DeleteFileTool()

    def test_workspace_file_operations(self):
        root = Path(self.settings.workspace_root)
        test_file = root / "temp" / "unittest_file.txt"

        # Write
        w_res = self.writer.execute(path=str(test_file), content="Test content for AUREX.")
        self.assertTrue(w_res.success)
        self.assertTrue(test_file.exists())

        # Read
        r_res = self.reader.execute(path=str(test_file))
        self.assertTrue(r_res.success)
        self.assertEqual(r_res.data, "Test content for AUREX.")

        # Delete
        d_res = self.deleter.execute(path=str(test_file))
        self.assertTrue(d_res.success)
        self.assertFalse(test_file.exists())

    def test_c_drive_write_rejected(self):
        res = self.writer.execute(path=r"C:\Windows\System32\malicious.txt", content="evil")
        self.assertFalse(res.success)
        self.assertIn("AUREX is not permitted to modify the C: drive", res.error)


class TestAgentContext(unittest.TestCase):
    def test_ordinal_references(self):
        ctx = AgentContext()
        ctx.last_entities = [
            r"D:\AUREX\file1.py",
            r"D:\AUREX\file2.py",
            r"D:\AUREX\file3.py"
        ]
        self.assertEqual(ctx.resolve_ordinal_reference("open the first one"), r"D:\AUREX\file1.py")
        self.assertEqual(ctx.resolve_ordinal_reference("open the second one"), r"D:\AUREX\file2.py")
        self.assertEqual(ctx.resolve_ordinal_reference("open the 3rd one"), r"D:\AUREX\file3.py")
        self.assertEqual(ctx.resolve_ordinal_reference("open the last one"), r"D:\AUREX\file3.py")


from app.learning.pattern_detector import PatternDetector
from app.learning.correction_learner import CorrectionLearner
from app.core.ai_router import AIRouter, RouteTarget
from app.memory.semantic_memory import SemanticMemory


class TestLearning(unittest.TestCase):
    def setUp(self):
        self.detector = PatternDetector()
        self.mm = MemoryManager()

    def test_confidence_calculation(self):
        conf_1 = self.detector.calculate_confidence(repetitions=1, days_span=1, recent_hits=1)
        conf_3 = self.detector.calculate_confidence(repetitions=3, days_span=1, recent_hits=2)
        conf_8 = self.detector.calculate_confidence(repetitions=8, days_span=5, recent_hits=5)

        self.assertGreater(conf_3, conf_1)
        self.assertGreater(conf_8, conf_3)
        self.assertLessEqual(conf_8, 0.98)
        self.assertGreaterEqual(conf_1, 0.10)

    def test_safety_filter_rejects_destructive_actions(self):
        safe_actions = ["open VS Code", "open Terminal", "open D:\\Projects"]
        self.assertTrue(self.detector.is_safe_sequence(safe_actions))

        delete_actions = ["open VS Code", "delete D:\\Projects\\temp.py"]
        self.assertFalse(self.detector.is_safe_sequence(delete_actions))

        format_actions = ["format D:", "clean drive"]
        self.assertFalse(self.detector.is_safe_sequence(format_actions))

        c_drive_actions = ["modify C:\\Windows\\System32", "create C:\\test.txt"]
        self.assertFalse(self.detector.is_safe_sequence(c_drive_actions))

    def test_candidate_routine_requires_approval(self):
        for _ in range(4):
            self.detector.record_action("open VS Code", category="application")
            self.detector.record_action("open Terminal", category="application")

        candidates = self.detector.detect_candidate_routines()
        for c in candidates:
            self.assertEqual(c["status"], "PROPOSED")
            self.assertGreaterEqual(c["confidence"], 0.20)


class TestCorrections(unittest.TestCase):
    def setUp(self):
        self.learner = CorrectionLearner()
        self.mm = MemoryManager()
        self.ctx = AgentContext()

    def test_path_correction(self):
        from app.core.context import get_context
        ctx = get_context()
        ctx.clear()
        ctx.add_turn(
            user_input="open my OS project",
            agent_response="Opened D:\\Projects\\General",
            tool_data="D:\\Projects\\General"
        )

        is_corr, msg = self.learner.inspect_for_correction("No, I mean D:\\OS")
        self.assertTrue(is_corr)
        self.assertIn("D:\\OS", msg)

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
        target, meta = self.router.classify_request("open Chrome")
        self.assertEqual(target, RouteTarget.LOCAL)
        self.assertEqual(meta.get("cost"), "$0.00")

        target, meta = self.router.classify_request("what is my RAM usage?")
        self.assertEqual(target, RouteTarget.LOCAL)
        self.assertEqual(meta.get("cost"), "$0.00")

        target, meta = self.router.classify_request("create folder my_test")
        self.assertEqual(target, RouteTarget.LOCAL)

        target, meta = self.router.classify_request("where is my OS project?")
        self.assertEqual(target, RouteTarget.LOCAL)

    def test_general_reasoning_to_groq(self):
        target, meta = self.router.classify_request("Explain how quantum computing differs from classical computing")
        self.assertEqual(target, RouteTarget.GROQ)

    def test_internet_search_queries(self):
        target, meta = self.router.classify_request("search the web for Python 3.14 release dates")
        self.assertEqual(target, RouteTarget.INTERNET)

    def test_privacy_mode_forces_local_zero_cloud(self):
        self.settings.set("privacy_mode", "private")
        target, meta = self.router.classify_request("Explain quantum physics")
        self.assertEqual(target, RouteTarget.LOCAL)
        self.assertIn("Private Mode", meta.get("reason", ""))

        target2, meta2 = self.router.classify_request("search the web for news")
        self.assertEqual(target2, RouteTarget.LOCAL)


class TestSemanticMemory(unittest.TestCase):
    def setUp(self):
        self.sm = SemanticMemory()
        self.mm = MemoryManager()

    def test_semantic_routine_matching(self):
        self.mm.save_routine(
            name="Morning Coding Setup",
            trigger_type="phrase",
            trigger_desc="start my daily coding session",
            action_sequence=["open VS Code", "open Terminal"],
            confidence=0.90,
            status="APPROVED"
        )

        match = self.sm.search_routines("start coding session")
        self.assertIsNotNone(match)
        self.assertEqual(match["name"], "Morning Coding Setup")
        self.assertGreater(match["match_score"], 0.3)

    def test_semantic_location_matching(self):
        self.mm.set_location_mapping(
            natural_name="Operating System Kernel Project",
            resolved_path="D:\\OS_Dev",
            confidence=0.95
        )

        path = self.sm.search_locations("where is my Operating System Kernel")
        self.assertEqual(path, "D:\\OS_Dev")


from PySide6.QtWidgets import QApplication
from app.ui.main_window import AurexMainWindow
from app.ui.voice_surface import VoiceInteractionSurface
from app.core.events import AgentState

_qt_app = QApplication.instance() or QApplication(sys.argv)


class TestPerformanceAndLifecycle(unittest.TestCase):
    def test_voice_surface_zero_cpu_idle(self):
        surface = VoiceInteractionSurface()
        self.assertEqual(surface.state, AgentState.IDLE)
        self.assertFalse(surface.anim_timer.isActive())

        surface.set_state(AgentState.LISTENING)
        self.assertTrue(surface.anim_timer.isActive())

        surface.set_state(AgentState.IDLE)
        self.assertFalse(surface.anim_timer.isActive())

    def test_lazy_view_instantiation(self):
        window = AurexMainWindow()
        self.assertIn("HOME", window.views_instances)
        self.assertNotIn("SYSTEM", window.views_instances)
        self.assertNotIn("APPLICATIONS", window.views_instances)

        window._on_navigate("SYSTEM")
        self.assertIn("SYSTEM", window.views_instances)

    def test_timer_lifecycle_on_navigation(self):
        window = AurexMainWindow()
        window.show()

        window._on_navigate("SYSTEM")
        sys_view = window.views_instances["SYSTEM"]
        self.assertTrue(sys_view.timer.isActive())

        window._on_navigate("HOME")
        self.assertFalse(sys_view.timer.isActive())


if __name__ == "__main__":
    unittest.main(verbosity=2)


