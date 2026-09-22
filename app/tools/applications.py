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
    "code": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe"
    ],
    "vscode": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe"
    ],
    "notepad": [r"C:\Windows\System32\notepad.exe"],
    "calc": [r"C:\Windows\System32\calc.exe"],
    "calculator": [r"C:\Windows\System32\calc.exe"],
    "explorer": [r"C:\Windows\explorer.exe"],
    "spotify": [os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
    "discord": [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe")],
    "terminal": [r"wt.exe", r"powershell.exe"]
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
    description = "Launch an installed Windows desktop application (e.g. Chrome, VS Code, Notepad, Spotify)."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the application, e.g. Chrome, VS Code, Notepad, Spotify"},
            "arguments": {"type": "string", "description": "Optional command-line arguments to pass"}
        },
        "required": ["name"]
    }
    is_write = False

    def execute(self, name: str, arguments: Optional[str] = None, **kwargs) -> ToolResult:
        app_path = ApplicationIndexer.find_app_path(name)
        cmd = []
        if app_path:
            cmd = [app_path]
        else:
            # Fallback to standard start command
            cmd = [name]

        if arguments:
            cmd.extend(arguments.split())

        try:
            # Launch detached so AUREX is never blocked or parent-coupled
            subprocess.Popen(
                cmd,
                creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
                shell=False
            )
            return ToolResult(success=True, message=f"Opening {name}.")
        except Exception as e:
            # Try shell start
            try:
                os.startfile(name)
                return ToolResult(success=True, message=f"Opening {name}.")
            except Exception as e2:
                return ToolResult(success=False, error=f"Could not open application '{name}': {e2}")


class CloseApplicationTool(BaseTool):
    name = "close_application"
    description = "Close a running application or process by name."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the process or app, e.g. chrome.exe, code, discord"}
        },
        "required": ["name"]
    }
    is_write = False

    def execute(self, name: str, **kwargs) -> ToolResult:
        import psutil
        clean = name.lower().replace(".exe", "").strip()
        closed_count = 0
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                pname = (proc.info['name'] or '').lower().replace(".exe", "")
                if clean in pname:
                    proc.terminate()
                    closed_count += 1
            except Exception:
                continue

        if closed_count > 0:
            return ToolResult(success=True, message=f"Closed {closed_count} instance(s) of '{name}'.")
        return ToolResult(success=False, error=f"No running application found matching '{name}'.")
