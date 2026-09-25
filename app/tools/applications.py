"""Application indexing, launching, and process management tools for AUREX."""

import os
import sys
import re
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


def get_desktop_items() -> List[Dict[str, str]]:
    """Return all applications, shortcuts, and items present on the user's desktop."""
    desktop_dirs = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/OneDrive/Desktop"),
        r"C:\Users\Public\Desktop",
    ]
    items = []
    seen = set()
    for d in desktop_dirs:
        if os.path.exists(d):
            for f in os.listdir(d):
                if f.lower() == "desktop.ini":
                    continue
                path = os.path.join(d, f)
                stem = Path(f).stem
                if stem.lower() not in seen:
                    seen.add(stem.lower())
                    items.append({"name": stem, "filename": f, "path": path})
    return items


class ApplicationIndexer:
    """Scans and caches installed Windows applications from Desktop, Start Menu, Registry, and PATH."""
    _cache: Dict[str, str] = {}

    @classmethod
    def _scan_all(cls) -> Dict[str, str]:
        index: Dict[str, str] = {}
        # 1. Desktop shortcuts
        desktop_dirs = [
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/OneDrive/Desktop"),
            r"C:\Users\Public\Desktop",
        ]
        # 2. Start Menu shortcuts
        start_dirs = [
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        ]

        for d in desktop_dirs + start_dirs:
            if os.path.exists(d):
                for root, _, files in os.walk(d):
                    for f in files:
                        if f.lower().endswith((".lnk", ".url", ".exe", ".bat", ".cmd")):
                            stem = Path(f).stem.lower().strip()
                            if stem not in index:
                                index[stem] = os.path.join(root, f)
        return index

    @classmethod
    def find_app_path(cls, app_name: str) -> Optional[str]:
        clean_name = app_name.lower().strip()

        # Remove filler words and action verbs
        clean_name = re.sub(r"^(?:open\s+|launch\s+|start\s+|run\s+|the\s+|an\s+|a\s+)+", "", clean_name).strip()
        clean_name = re.sub(r"\s+(?:on|from)\s+(?:the\s+|my\s+)?des[k]?top$", "", clean_name).strip()
        clean_name = re.sub(r"\s+app(?:lication)?$", "", clean_name).strip()

        # 1. Direct common mapping
        for key, paths in COMMON_APP_PATHS.items():
            if clean_name == key or key in clean_name or clean_name in key:
                for p in paths:
                    exp = os.path.expandvars(p)
                    if os.path.exists(exp) or not os.path.isabs(exp):
                        return exp

        # 2. Check Desktop and Start Menu dynamic index
        scanned = cls._scan_all()
        # Exact match
        if clean_name in scanned:
            return scanned[clean_name]

        # Substring match (e.g. "docker" matches "docker desktop", "packet tracer" matches "cisco packet tracer")
        for k, p in scanned.items():
            if clean_name == k or clean_name in k or k in clean_name:
                return p

        # 3. Check PATH environment variable
        for p in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(p, clean_name if clean_name.endswith(".exe") else f"{clean_name}.exe")
            if os.path.exists(candidate):
                return candidate

        # 4. Check Windows Registry App Paths
        try:
            import winreg
            for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root_key, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{clean_name}.exe") as k:
                        val, _ = winreg.QueryValueEx(k, "")
                        if val and os.path.exists(val):
                            return val
                except OSError:
                    pass
        except Exception:
            pass

        return None


class OpenApplicationTool(BaseTool):
    name = "open_application"
    description = "Launch an installed Windows desktop application (e.g. Chrome, Edge, VS Code, Notepad, Spotify, Docker, Packet Tracer)."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the application, e.g. Chrome, Edge, VS Code, Notepad, Spotify, Docker, Packet Tracer"},
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

        # Check if generic desktop request without explicit app name
        if lower_clean in ("this app on the desktop", "the app on the desktop", "this app", "the app"):
            desktop_items = get_desktop_items()
            if desktop_items:
                # Launch first desktop application shortcut
                for it in desktop_items:
                    if it["filename"].lower().endswith((".lnk", ".exe")):
                        try:
                            os.startfile(it["path"])
                            return ToolResult(success=True, message=f"Opening {it['name']} from your desktop.")
                        except Exception as e:
                            return ToolResult(success=False, error=str(e))
                return ToolResult(success=False, error="No launchable desktop applications found.")
            return ToolResult(success=False, error="Your desktop has no application shortcuts.")

        app_path = ApplicationIndexer.find_app_path(clean)
        if app_path:
            try:
                os.startfile(app_path)
                return ToolResult(success=True, message=f"Opening {name}.")
            except Exception as e:
                logger.debug(f"startfile failed for {app_path}: {e}")

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
            except Exception as e:
                return ToolResult(success=False, error=f"Failed to launch {name}: {e}")

        # Try os.startfile directly (relies on Windows registered applications)
        try:
            os.startfile(clean)
            return ToolResult(success=True, message=f"Opening {name}.")
        except Exception:
            pass

        return ToolResult(success=False, error=f"Could not find application '{name}' on your desktop or system.")


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
