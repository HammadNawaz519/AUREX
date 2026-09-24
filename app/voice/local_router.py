"""AUREX Voice System — Fast Local Command Router & Context Tracker.

Features:
  - Sub-150ms local execution for common commands (app launching, window/system commands)
  - UI control actions (come front, shrink, expand, send to back)
  - Short-term conversational context tracking (resolves "it", "that", "again", "same thing")
  - Complete security conformance (never executes unrestricted shell or bypasses safety)
"""

from __future__ import annotations
import collections
import logging
import os
import re
import subprocess
import time
from typing import Callable, Dict, Any, List, Optional, Tuple

from app.tools.applications import OpenApplicationTool, CloseApplicationTool
from app.tools.screenshots import TakeScreenshotTool

logger = logging.getLogger("AurexLocalRouter")


class ConversationContext:
    """Tracks short-term conversational context (up to last 10 turns)."""

    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: collections.deque[Dict[str, Any]] = collections.deque(maxlen=max_history)
        self.last_application: Optional[str] = None
        self.last_project: Optional[str] = None
        self.last_file: Optional[str] = None
        self.last_folder: Optional[str] = None
        self.last_command: Optional[str] = None
        self.last_tool_result: Optional[str] = None

    def record_turn(self, user_text: str, reply_text: str, metadata: Optional[Dict[str, Any]] = None):
        turn = {
            "timestamp": time.time(),
            "user": user_text,
            "reply": reply_text,
            "metadata": metadata or {},
        }
        self.history.append(turn)
        self.last_command = user_text

        # Update entity references if provided
        if metadata:
            if "app" in metadata:
                self.last_application = metadata["app"]
            if "project" in metadata:
                self.last_project = metadata["project"]
            if "file" in metadata:
                self.last_file = metadata["file"]
            if "folder" in metadata:
                self.last_folder = metadata["folder"]

    def resolve_reference(self, text: str) -> str:
        """
        Resolve pronouns ("it", "that", "this", "again") using recent context.
        Example: "build it" -> "build my OS project" or "build D:\\Projects\\OS"
        """
        clean = text.strip()
        lower = clean.lower()

        # Pronoun substitution
        pronoun_match = re.search(r"\b(it|that|this|the project|the app)\b", lower)
        if pronoun_match:
            target = None
            if self.last_project and any(k in lower for k in ["build", "run", "compile", "test", "open"]):
                target = self.last_project
            elif self.last_application and any(k in lower for k in ["close", "quit", "focus", "open", "restart"]):
                target = self.last_application
            elif self.last_file:
                target = self.last_file

            if target:
                clean = re.sub(r"\b(it|that|this)\b", lambda m: target, clean, flags=re.IGNORECASE)
                logger.info(f"Context resolved pronoun in '{text}' -> '{clean}'")

        if lower in ("again", "do it again", "same thing", "repeat that"):
            if self.last_command and self.last_command.lower() not in ("again", "repeat that"):
                logger.info(f"Context resolved 'again' -> '{self.last_command}'")
                clean = self.last_command

        return clean


class FastLocalRouter:
    """
    Sub-150ms deterministic command router.
    Executes standard actions locally without cloud LLM roundtrips.
    """

    def __init__(self, ui_action_handler: Optional[Callable[[str], None]] = None):
        self.ui_action_handler = ui_action_handler
        self.context = ConversationContext()
        self._open_app_tool = OpenApplicationTool()
        self._close_app_tool = CloseApplicationTool()
        self._screenshot_tool = TakeScreenshotTool()

    def set_ui_action_handler(self, handler: Callable[[str], None]):
        self.ui_action_handler = handler

    def handle(self, user_command: str) -> Tuple[bool, str]:
        """
        Attempt to resolve and execute command locally.
        
        Returns:
            (matched, response_text)
            matched=True: command handled locally
            matched=False: needs AI agent reasoning
        """
        resolved_cmd = self.context.resolve_reference(user_command)
        lower = resolved_cmd.lower().strip()
        start_time = time.perf_counter()

        # ── 1. UI Navigation & Window Geometry ─────────────────────────────────
        if any(p in lower for p in ["come up", "bring up", "come to front", "come front", "above all tabs", "front"]):
            if self.ui_action_handler:
                self.ui_action_handler("come_up")
            msg = "I am right here in front of all your tabs, Hammad."
            self._log_and_record(resolved_cmd, msg, {"action": "come_up"}, start_time)
            return True, msg

        if any(p in lower for p in ["shrink", "make small", "minimize widget", "collapse", "tiny mode", "orb mode", "round", "make it round"]):
            if self.ui_action_handler:
                self.ui_action_handler("shrink")
            msg = "Shrinking to compact mode."
            self._log_and_record(resolved_cmd, msg, {"action": "shrink"}, start_time)
            return True, msg

        if any(p in lower for p in ["expand", "grow", "full size", "restore", "make big", "open card"]):
            if self.ui_action_handler:
                self.ui_action_handler("expand")
            msg = "Restoring full interface, Hammad."
            self._log_and_record(resolved_cmd, msg, {"action": "expand"}, start_time)
            return True, msg

        if any(p in lower for p in ["go back", "send to back", "hide behind", "wallpaper"]):
            if self.ui_action_handler:
                self.ui_action_handler("go_back")
            msg = "Pinned back to your desktop wallpaper, Hammad."
            self._log_and_record(resolved_cmd, msg, {"action": "go_back"}, start_time)
            return True, msg

        # ── 2. Volume & Mute Controls ──────────────────────────────────────────
        if lower in ("mute", "mute audio", "mute sound", "silence"):
            self._send_windows_key(0xAD)  # VK_VOLUME_MUTE
            msg = "Sound muted."
            self._log_and_record(resolved_cmd, msg, {}, start_time)
            return True, msg

        if lower in ("unmute", "unmute audio", "unmute sound"):
            self._send_windows_key(0xAD)  # VK_VOLUME_MUTE toggle
            msg = "Sound unmuted."
            self._log_and_record(resolved_cmd, msg, {}, start_time)
            return True, msg

        # ── 3. Desktop Shortcuts ──────────────────────────────────────────────
        if lower in ("minimize all", "show desktop", "minimize all windows"):
            self._send_win_key("d")
            msg = "Minimizing all windows to show desktop."
            self._log_and_record(resolved_cmd, msg, {}, start_time)
            return True, msg

        if any(p in lower for p in ["take screenshot", "take a screenshot", "screenshot screen", "capture screen"]):
            res = self._screenshot_tool.execute()
            msg = "Screenshot captured successfully." if res.success else f"Screenshot failed: {res.error}"
            self._log_and_record(resolved_cmd, msg, {"screenshot": res.data}, start_time)
            return True, msg

        # ── 4. Fast Application Launches ───────────────────────────────────────
        open_match = re.match(r"^(?:open|launch|start|run)\s+(?:the\s+)?([a-zA-Z0-9\s._\-]+)$", lower)
        if open_match:
            app_target = open_match.group(1).strip()
            # Exclude complex instructions
            if not any(w in app_target for w in ["and", "then", "if", "why", "how", "what", "because"]):
                # Check for "my os project" or custom directories
                if "os project" in app_target:
                    os_path = r"D:\VS Code\OS" if os.path.exists(r"D:\VS Code\OS") else None
                    if not os_path and os.path.exists(r"D:\OS"):
                        os_path = r"D:\OS"
                    if os_path:
                        try:
                            os.startfile(os_path)
                            msg = f"Opened your OS project at {os_path}."
                            self._log_and_record(resolved_cmd, msg, {"project": os_path}, start_time)
                            return True, msg
                        except Exception as e:
                            logger.error(f"Failed to open OS project: {e}")

                res = self._open_app_tool.execute(name=app_target)
                if res.success:
                    msg = f"Opening {app_target.capitalize()}."
                    self._log_and_record(resolved_cmd, msg, {"app": app_target}, start_time)
                    return True, msg

        # ── 5. Application Termination ────────────────────────────────────────
        close_match = re.match(r"^(?:close|quit|kill|exit)\s+(?:the\s+)?([a-zA-Z0-9\s._\-]+)$", lower)
        if close_match:
            app_target = close_match.group(1).strip()
            if not any(w in app_target for w in ["and", "then", "all"]):
                res = self._close_app_tool.execute(name=app_target)
                if res.success:
                    msg = f"Closed {app_target.capitalize()}."
                    self._log_and_record(resolved_cmd, msg, {}, start_time)
                    return True, msg

        return False, ""

    def _log_and_record(self, cmd: str, reply: str, meta: Dict[str, Any], start_perf: float):
        latency_ms = (time.perf_counter() - start_perf) * 1000.0
        logger.info(f"[LocalRouter] Matched and executed locally in {latency_ms:.1f}ms: '{cmd}' -> '{reply}'")
        self.context.record_turn(cmd, reply, meta)

    @staticmethod
    def _send_windows_key(vk_code: int):
        import ctypes
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)

    @staticmethod
    def _send_win_key(key_char: str):
        import ctypes
        VK_LWIN = 0x5B
        vk_target = ord(key_char.upper())
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk_target, 0, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(vk_target, 0, 2, 0)
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 2, 0)
