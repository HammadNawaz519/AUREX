"""Window management tools for AUREX on Windows."""

import ctypes
from typing import Dict, Any, List, Optional
from app.tools.base import BaseTool, ToolResult


class ListWindowsTool(BaseTool):
    name = "list_windows"
    description = "List all open, visible desktop application windows."
    parameters = {
        "type": "object",
        "properties": {}
    }
    is_write = False

    def execute(self, **kwargs) -> ToolResult:
        titles = []

        def enum_windows_proc(hwnd, lParam):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()
                    if title and title not in ("Program Manager", "Settings", "AUREX"):
                        titles.append({"hwnd": hwnd, "title": title})
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)

        return ToolResult(
            success=True,
            data=titles,
            message=f"Found {len(titles)} open application windows."
        )


class FocusWindowTool(BaseTool):
    name = "focus_window"
    description = "Bring an open application window to the foreground by its title."
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Title or partial title of the window"}
        },
        "required": ["title"]
    }
    is_write = False

    def execute(self, title: str, **kwargs) -> ToolResult:
        clean = title.lower()
        target_hwnd = None
        found_title = ""

        def enum_proc(hwnd, lParam):
            nonlocal target_hwnd, found_title
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    t = buff.value.strip()
                    if clean in t.lower():
                        target_hwnd = hwnd
                        found_title = t
                        return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

        if target_hwnd:
            ctypes.windll.user32.ShowWindow(target_hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(target_hwnd)
            return ToolResult(success=True, message=f"Switched focus to '{found_title}'.")

        return ToolResult(success=False, error=f"No window found matching '{title}'.")
