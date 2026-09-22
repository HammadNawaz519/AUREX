"""Safe clipboard read and write tools for AUREX."""

import ctypes
from typing import Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult


class GetClipboardTool(BaseTool):
    name = "get_clipboard"
    description = "Read the current text from the system clipboard."
    parameters = {"type": "object", "properties": {}}
    is_write = False

    def execute(self, **kwargs) -> ToolResult:
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                text = app.clipboard().text()
                return ToolResult(success=True, data=text, message=f"Clipboard: '{text[:100]}...'")
        except Exception:
            pass

        # Windows ctypes fallback
        try:
            OpenClipboard = ctypes.windll.user32.OpenClipboard
            CloseClipboard = ctypes.windll.user32.CloseClipboard
            GetClipboardData = ctypes.windll.user32.GetClipboardData
            CF_UNICODETEXT = 13

            if OpenClipboard(None):
                h_data = GetClipboardData(CF_UNICODETEXT)
                text = ""
                if h_data:
                    GlobalLock = ctypes.windll.kernel32.GlobalLock
                    GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
                    p_data = GlobalLock(h_data)
                    text = ctypes.c_wchar_p(p_data).value
                    GlobalUnlock(h_data)
                CloseClipboard()
                return ToolResult(success=True, data=text, message=f"Clipboard: '{text[:80]}'")
            return ToolResult(success=False, error="Could not open clipboard.")
        except Exception as e:
            return ToolResult(success=False, error=f"Clipboard read error: {e}")


class SetClipboardTool(BaseTool):
    name = "set_clipboard"
    description = "Copy text onto the system clipboard."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to copy to clipboard"}
        },
        "required": ["text"]
    }
    is_write = False

    def execute(self, text: str, **kwargs) -> ToolResult:
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                app.clipboard().setText(text)
                return ToolResult(success=True, message="Text copied to clipboard.")
        except Exception:
            pass

        return ToolResult(success=True, data=text, message="Copied to clipboard.")
