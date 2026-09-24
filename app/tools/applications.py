"""Application indexing, launching, and process management tools for AUREX."""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.tools.base import BaseTool, ToolResult
from app.core.security import canonical_path

logger = logging.getLogger(__name__)

COMMON_APP_PATHS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "msedge.exe"
    ],
    "msedge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "msedge.exe"
    ],
    "code": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe"
    ],
    "vscode": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe"
    ],
    "notepad": [r"C:\Windows\System32\notepad.exe", "notepad.exe"],
    "calc": [r"C:\Windows\System32\calc.exe", "calc.exe"],
    "calculator": [r"C:\Windows\System32\calc.exe", "calc.exe"],
    "explorer": [r"C:\Windows\explorer.exe", "explorer.exe"],
    "file explorer": [r"C:\Windows\explorer.exe", "explorer.exe"],
    "spotify": [os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
    "discord": [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe")],
    "terminal": [r"wt.exe", r"powershell.exe", r"cmd.exe"],
    "cmd": [r"cmd.exe"],
    "powershell": [r"powershell.exe"],
    "paint": [r"C:\Windows\System32\mspaint.exe", "mspaint.exe"],
    "task manager": [r"C:\Windows\System32\Taskmgr.exe", "taskmgr.exe"],
    "taskmgr": [r"C:\Windows\System32\Taskmgr.exe", "taskmgr.exe"],
    "settings": ["ms-settings:"],
    "word": [r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE", "winword.exe"],
    "excel": [r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE", "excel.exe"],
    "powerpoint": [r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE", "powerpnt.exe"]
}


class ApplicationIndexer:
    """Scans and caches installed Windows applications."""
    _cache: Dict[str, str] = {}

    @classmethod
    def find_app_path(cls, app_name: str) -> Optional[str]:
        clean_name = app_name.lower().strip()
        # Direct common mapping
        for key, paths in COMMON_APP_PATHS.items():
            if clean_name == key or key in clean_name:
                for p in paths:
                    exp = os.path.expandvars(p)
                    if os.path.exists(exp) or not os.path.isabs(exp):
                        return exp

        # Check PATH environment variable
        for p in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(p, clean_name if clean_name.endswith(".exe") else f"{clean_name}.exe")
            if os.path.exists(candidate):
                return candidate

        return None


class OpenApplicationTool(BaseTool):
    name = "open_application"
    description = "Launch an installed Windows desktop application (e.g. Chrome, Edge, VS Code, Notepad, Spotify, Word)."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the application, e.g. Chrome, Edge, VS Code, Notepad, Spotify, Calculator"},
            "arguments": {"type": "string", "description": "Optional command-line arguments to pass"}
        },
        "required": ["name"]
    }
    is_write = False

    def execute(self, name: str, arguments: Optional[str] = None, **kwargs) -> ToolResult:
        clean = name.strip()
        lower_clean = clean.lower()

        # Handle special Windows URI protocols and shell shortcuts
        if lower_clean in ("settings", "windows settings"):
            try:
                os.startfile("ms-settings:")
                return ToolResult(success=True, message="Opening Windows Settings.")
            except Exception as e:
                return ToolResult(success=False, error=str(e))

        if lower_clean in ("task manager", "taskmgr"):
            try:
                os.startfile("taskmgr.exe")
                return ToolResult(success=True, message="Opening Task Manager.")
            except Exception as e:
                return ToolResult(success=False, error=str(e))

        if lower_clean in ("file explorer", "explorer", "my computer"):
            try:
                os.startfile("explorer.exe")
                return ToolResult(success=True, message="Opening File Explorer.")
            except Exception as e:
                return ToolResult(success=False, error=str(e))

        if lower_clean in ("downloads", "my downloads"):
            try:
                os.startfile(os.path.expanduser("~/Downloads"))
                return ToolResult(success=True, message="Opening Downloads folder.")
            except Exception as e:
                return ToolResult(success=False, error=str(e))

        if lower_clean in ("documents", "my documents"):
            try:
                os.startfile(os.path.expanduser("~/Documents"))
                return ToolResult(success=True, message="Opening Documents folder.")
            except Exception as e:
                return ToolResult(success=False, error=str(e))

        app_path = ApplicationIndexer.find_app_path(clean)
        if app_path:
            if app_path.startswith("ms-settings:"):
                try:
                    os.startfile(app_path)
                    return ToolResult(success=True, message=f"Opening {name}.")
                except Exception as e:
                    return ToolResult(success=False, error=str(e))

            cmd = [app_path]
            if arguments:
                cmd.extend(arguments.split())
            try:
                subprocess.Popen(
                    cmd,
                    creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
                    shell=False
                )
                return ToolResult(success=True, message=f"Opening {name}.")
            except Exception:
                pass

        # Try os.startfile directly (relies on Windows registered applications and extensions)
        try:
            os.startfile(clean)
            return ToolResult(success=True, message=f"Opening {name}.")
        except Exception:
            pass

        # Universal shell launcher fallback
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", f"Start-Process '{clean}'"],
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return ToolResult(success=True, message=f"Opening {name}.")
        except Exception as e:
            return ToolResult(success=False, error=f"Could not open application '{name}': {e}")


class CloseApplicationTool(BaseTool):
    name = "close_application"
    description = "Close a running application or process by name."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the process or app, e.g. chrome, edge, code, discord, notepad"}
        },
        "required": ["name"]
    }
    is_write = False

    def execute(self, name: str, **kwargs) -> ToolResult:
        import psutil
        clean = name.lower().replace(".exe", "").strip()

        alias_map = {
            "chrome": ["chrome"],
            "edge": ["msedge", "edge"],
            "msedge": ["msedge"],
            "vscode": ["code"],
            "vs code": ["code"],
            "code": ["code"],
            "calculator": ["calculatorapp", "calc"],
            "calc": ["calculatorapp", "calc"],
            "task manager": ["taskmgr"],
            "taskmgr": ["taskmgr"],
            "notepad": ["notepad"],
            "spotify": ["spotify"],
            "discord": ["discord"]
        }
        targets = alias_map.get(clean, [clean])

        closed_count = 0
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                pname = (proc.info['name'] or '').lower().replace(".exe", "")
                if any(t in pname for t in targets):
                    proc.terminate()
                    closed_count += 1
            except Exception:
                continue

        if closed_count > 0:
            return ToolResult(success=True, message=f"Closed {closed_count} instance(s) of '{name}'.")
        return ToolResult(success=False, error=f"No running application found matching '{name}'.")
