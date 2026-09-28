import os
import shutil
import platform
import subprocess
import tempfile
import hashlib
import zipfile
import tarfile
import re
import json
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    _SEND2TRASH = False

try:
    import win32api
    import win32file
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

from core.undo import push_undo

_OS = platform.system()

# Stateful directory tracking & history for conversational navigation
_CURRENT_DIR: Path = Path.home() / "Desktop"
_DIR_HISTORY_BACK: list[Path] = []
_DIR_HISTORY_FORWARD: list[Path] = []

def get_current_dir() -> Path:
    global _CURRENT_DIR
    return _CURRENT_DIR

def set_current_dir(p: Path):
    global _CURRENT_DIR
    _push_navigation(p)
    _CURRENT_DIR = p

def _push_navigation(new_dir: Path):
    global _CURRENT_DIR, _DIR_HISTORY_BACK, _DIR_HISTORY_FORWARD
    try:
        resolved = new_dir.resolve()
        if _CURRENT_DIR and resolved != _CURRENT_DIR.resolve():
            _DIR_HISTORY_BACK.append(_CURRENT_DIR)
            if len(_DIR_HISTORY_BACK) > 50:
                _DIR_HISTORY_BACK.pop(0)
            _DIR_HISTORY_FORWARD.clear()
    except Exception:
        pass

# Undo keeps a file's previous contents in memory so `write` can be reversed.
_UNDO_CONTENT_LIMIT = 1_000_000


def _undo_move(src: Path, dst: Path):
    """Reverse of a move: put it back where it came from."""
    def _fn():
        if not dst.exists():
            return f"'{dst.name}' is no longer there — nothing moved back."
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        return f"'{src.name}' is back in {src.parent.name}/."
    return _fn


def _undo_create(target: Path):
    """Reverse of a create: remove what we made — and only if we still made it."""
    def _fn():
        if not target.exists():
            return f"'{target.name}' is already gone."
        if target.is_dir():
            if any(target.iterdir()):
                return (f"'{target.name}' is not empty any more — "
                        f"leaving it alone rather than deleting your files.")
            target.rmdir()
        else:
            target.unlink()
        return f"Removed '{target.name}'."
    return _fn


def _undo_write(target: Path, previous: str | None):
    """Reverse of a write: restore old contents or remove newly created file."""
    def _fn():
        if previous is None:
            if target.exists():
                target.unlink()
                return f"Removed '{target.name}' — it did not exist before."
            return f"'{target.name}' is already gone."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(previous, encoding="utf-8")
        return f"Restored the previous contents of '{target.name}'."
    return _fn


def _restore_from_trash(original: Path) -> str:
    """Best-effort undelete from Recycle Bin."""
    if _OS == "Windows":
        try:
            import win32com.client
            shell = win32com.client.Dispatch("Shell.Application")
            bin_folder = shell.NameSpace(10)      # ssfBITBUCKET
            for item in bin_folder.Items():
                if str(bin_folder.GetDetailsOf(item, 1)).strip().lower() == \
                        str(original.parent).strip().lower():
                    if str(item.Name).strip().lower() == original.name.strip().lower():
                        item.InvokeVerb("UNDELETE")
                        return f"'{original.name}' restored from the Recycle Bin."
        except Exception as e:
            print(f"[file] Recycle Bin restore failed: {e}")
    return (f"'{original.name}' is in the Recycle Bin — I could not pull it back "
            f"automatically, but it is there and can be restored by hand.")


def _is_safe_path(target: Path) -> bool:
    """Validate path permissions:
    - ALLOWED: D: drive (full access), all secondary drives (E:, F:), user folders on C: (Desktop, Documents, Downloads, Pictures, Videos, Music, user home)
    - PROTECTED/BLOCKED: Sensitive Windows OS root folders on C: (Windows, Program Files, System32)
    """
    try:
        resolved = target.resolve()
        if _OS == "Windows":
            drive = resolved.drive.upper()
            if drive and drive != "C:":
                # D: drive and all other drives are 100% fully accessible
                return True

            # For C: drive, protect critical Windows system folders
            sys_roots = [
                Path("C:/Windows").resolve(),
                Path("C:/Program Files").resolve(),
                Path("C:/Program Files (x86)").resolve(),
            ]
            for s_root in sys_roots:
                if resolved == s_root or resolved.is_relative_to(s_root):
                    return False

            # All user directories on C: are safe
            return True

        return True
    except Exception:
        return True


def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Desktop"


def _get_downloads() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Downloads"


def _get_documents() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOCUMENTS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Documents"


def _get_pictures() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_PICTURES_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Pictures"


def _get_music() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_MUSIC_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Music"


def _get_videos() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_VIDEOS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Videos"


def _get_temp() -> Path:
    return Path(tempfile.gettempdir())


def _get_appdata() -> Path:
    app_data = os.environ.get("APPDATA")
    return Path(app_data) if app_data else Path.home()


def _get_onedrive() -> Path | None:
    one_drive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if one_drive and Path(one_drive).exists():
        return Path(one_drive)
    p = Path.home() / "OneDrive"
    return p if p.exists() else None


def _resolve_path(raw: str) -> Path:
    """Robust conversational path resolution with multi-drive, navigation, and alias support."""
    global _CURRENT_DIR
    raw = (raw or "").strip().strip('"').strip("'")

    shortcuts: dict[str, Path] = {
        "desktop":       _get_desktop(),
        "on desktop":    _get_desktop(),
        "downloads":     _get_downloads(),
        "in downloads":  _get_downloads(),
        "documents":     _get_documents(),
        "in documents":  _get_documents(),
        "pictures":      _get_pictures(),
        "music":         _get_music(),
        "videos":        _get_videos(),
        "temp":          _get_temp(),
        "tmp":           _get_temp(),
        "appdata":       _get_appdata(),
        "home":          Path.home(),
        "here":          _CURRENT_DIR,
        "current":       _CURRENT_DIR,
        "current folder": _CURRENT_DIR,
        "current directory": _CURRENT_DIR,
        ".":             _CURRENT_DIR,
        "":              _CURRENT_DIR,
        "up":            _CURRENT_DIR.parent,
        "parent":        _CURRENT_DIR.parent,
        "..":            _CURRENT_DIR.parent,
    }

    od = _get_onedrive()
    if od:
        shortcuts["onedrive"] = od
        shortcuts["one drive"] = od

    lower = raw.lower().replace("\\", "/")

    # Check direct dictionary shortcuts
    if lower in shortcuts:
        return shortcuts[lower]

    # Handle drive queries like "d drive", "drive d", "d:", "drive d:", "in drive d", "c:", "e drive"
    drive_match = re.match(r"^(?:in\s+)?(?:drive\s+)?([a-zA-Z])(?::|(?:\s+drive))?(?:/)?$", lower)
    if drive_match:
        letter = drive_match.group(1).upper()
        return Path(f"{letter}:/")

    # Handle prefixed drive / shortcut paths like "drive d/projects", "d drive/notes", "desktop/folder"
    head, sep, rest = lower.partition("/")
    if sep:
        head_clean = head.strip()
        # Check if head is a drive expression
        dm = re.match(r"^(?:drive\s+)?([a-zA-Z])(?::|(?:\s+drive))?$", head_clean)
        if dm:
            letter = dm.group(1).upper()
            return Path(f"{letter}:/") / rest.strip("/")
        if head_clean in shortcuts:
            base = shortcuts[head_clean]
            return base / rest.strip("/") if rest else base

    # Normalize Windows drive letter missing slash: e.g. "D:test.txt" -> "D:/test.txt"
    if _OS == "Windows" and len(raw) >= 2 and raw[1] == ":" and (len(raw) == 2 or raw[2] not in ("/", "\\")):
        raw = raw[:2] + "/" + raw[2:]

    p = Path(raw).expanduser()
    if p.is_absolute():
        return p

    # If relative, check if it exists in _CURRENT_DIR
    if (_CURRENT_DIR / raw).exists():
        return _CURRENT_DIR / raw
    # Check if in D: drive
    if (Path("D:/") / raw).exists():
        return Path("D:/") / raw
    # Check Desktop
    if (_get_desktop() / raw).exists():
        return _get_desktop() / raw
    # Check Downloads
    if (_get_downloads() / raw).exists():
        return _get_downloads() / raw

    # Case-insensitive match in _CURRENT_DIR
    try:
        if _CURRENT_DIR.exists() and _CURRENT_DIR.is_dir():
            for item in _CURRENT_DIR.iterdir():
                if item.name.lower() == lower:
                    return item
    except Exception:
        pass

    return _CURRENT_DIR / raw


def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _safe_trash(target: Path) -> str:
    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


# ── WINDOWS FILE EXPLORER INTEGRATION ────────────────────────────────────────

def open_folder(path: str = "") -> str:
    """Open a folder in Windows File Explorer, track it as current directory, and list contents."""
    try:
        global _CURRENT_DIR
        target = _resolve_path(path) if path else _CURRENT_DIR
        if target.is_file():
            target = target.parent
        if not target.exists():
            return f"Folder not found: {target}"
        if not _is_safe_path(target):
            return f"Access denied: {target}"

        _push_navigation(target)
        _CURRENT_DIR = target

        # Launch File Explorer so user physically sees the folder open
        if _OS == "Windows":
            os.startfile(str(target))
        elif _OS == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])

        contents = list_files(str(target))
        return f"Opened {target.resolve()} in File Explorer.\n\n{contents}"
    except Exception as e:
        return f"Error opening folder: {e}"


def reveal_in_explorer(path: str = "", name: str = "") -> str:
    """Open Windows File Explorer with the exact file or folder highlighted and selected."""
    try:
        global _CURRENT_DIR
        base = _resolve_path(path) if path else _CURRENT_DIR
        target = (base / name) if (name and not base.name.lower() == name.lower()) else base
        if not target.exists():
            return f"Item not found to reveal: {target}"
        if not _is_safe_path(target):
            return f"Access denied: {target}"

        resolved_str = str(target.resolve())
        if _OS == "Windows":
            subprocess.Popen(f'explorer.exe /select,"{resolved_str}"', shell=True)
            return f"Revealed and selected '{target.name}' in Windows File Explorer."
        elif _OS == "Darwin":
            subprocess.Popen(["open", "-R", resolved_str])
            return f"Revealed '{target.name}' in Finder."
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])
            return f"Opened folder containing '{target.name}' in file manager."
    except Exception as e:
        return f"Could not reveal item in File Explorer: {e}"


def get_open_explorers() -> str:
    """List all folders currently open in Windows File Explorer windows."""
    if _OS != "Windows":
        return "Open explorer window listing is only available on Windows."
    try:
        import win32com.client
        import urllib.parse
        shell = win32com.client.Dispatch("Shell.Application")
        open_paths = []
        for win in shell.Windows():
            try:
                url = getattr(win, "LocationURL", "")
                if url.startswith("file:///"):
                    parsed = urllib.parse.unquote(url[8:].replace("/", "\\"))
                    if parsed and parsed not in open_paths:
                        open_paths.append(parsed)
            except Exception:
                continue

        if not open_paths:
            return "No File Explorer folder windows are currently detected."

        lines = [f"Currently open File Explorer windows ({len(open_paths)}):"]
        for p in open_paths:
            lines.append(f"  📁 {p}")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not inspect open File Explorer windows: {e}"


def close_explorer(path: str = "") -> str:
    """Close specific or all open Windows File Explorer folder windows."""
    if _OS != "Windows":
        return "Closing explorer windows is only supported on Windows."
    try:
        import win32com.client
        import urllib.parse
        shell = win32com.client.Dispatch("Shell.Application")
        closed_count = 0
        target_clean = path.lower().strip().replace("/", "\\") if path else ""

        for win in list(shell.Windows()):
            try:
                url = getattr(win, "LocationURL", "")
                if url.startswith("file:///"):
                    parsed = urllib.parse.unquote(url[8:].replace("/", "\\")).lower()
                    if not target_clean or target_clean in parsed:
                        win.Quit()
                        closed_count += 1
            except Exception:
                continue

        if closed_count > 0:
            return f"Closed {closed_count} File Explorer window(s)."
        return "No matching File Explorer windows were found to close."
    except Exception as e:
        return f"Could not close File Explorer window: {e}"


# ── NAVIGATION STACK (BACK / FORWARD / UP / HISTORY) ─────────────────────────

def navigate_back() -> str:
    """Navigate back to the previous folder in the session history."""
    global _CURRENT_DIR, _DIR_HISTORY_BACK, _DIR_HISTORY_FORWARD
    if not _DIR_HISTORY_BACK:
        return f"No previous folder in history. Currently at: {_CURRENT_DIR}"
    prev = _DIR_HISTORY_BACK.pop()
    _DIR_HISTORY_FORWARD.append(_CURRENT_DIR)
    _CURRENT_DIR = prev
    if _OS == "Windows":
        try: os.startfile(str(prev))
        except Exception: pass
    contents = list_files(str(prev))
    return f"Navigated back to {prev.resolve()}.\n\n{contents}"


def navigate_forward() -> str:
    """Navigate forward to the next folder in the session history."""
    global _CURRENT_DIR, _DIR_HISTORY_BACK, _DIR_HISTORY_FORWARD
    if not _DIR_HISTORY_FORWARD:
        return f"No forward folder in history. Currently at: {_CURRENT_DIR}"
    next_dir = _DIR_HISTORY_FORWARD.pop()
    _DIR_HISTORY_BACK.append(_CURRENT_DIR)
    _CURRENT_DIR = next_dir
    if _OS == "Windows":
        try: os.startfile(str(next_dir))
        except Exception: pass
    contents = list_files(str(next_dir))
    return f"Navigated forward to {next_dir.resolve()}.\n\n{contents}"


def navigate_up() -> str:
    """Navigate up one level to the parent directory."""
    global _CURRENT_DIR
    parent = _CURRENT_DIR.parent
    if parent == _CURRENT_DIR:
        return f"Already at the root: {_CURRENT_DIR}"
    return open_folder(str(parent))


def get_navigation_history() -> str:
    """Show recent directory navigation breadcrumbs."""
    crumbs = []
    for p in _DIR_HISTORY_BACK[-5:]:
        crumbs.append(p.name or str(p))
    crumbs.append(f"[{_CURRENT_DIR.name or str(_CURRENT_DIR)} (current)]")
    for p in reversed(_DIR_HISTORY_FORWARD[-5:]):
        crumbs.append(p.name or str(p))
    return "Navigation path: " + " -> ".join(crumbs)


# ── DRIVES INSPECTION & STORAGE MONITOR ──────────────────────────────────────

def list_drives() -> str:
    """List all system drives with volume labels, types, total space, free space, and usage bars."""
    drives = []
    if _OS == "Windows" and _WIN32_AVAILABLE:
        try:
            for d in win32api.GetLogicalDriveStrings().split('\000')[:-1]:
                try:
                    dtype_code = win32file.GetDriveType(d)
                    type_names = {
                        win32file.DRIVE_REMOVABLE: "Removable USB",
                        win32file.DRIVE_FIXED:     "Fixed Drive (SSD/HDD)",
                        win32file.DRIVE_REMOTE:    "Network Drive",
                        win32file.DRIVE_CDROM:     "CD/DVD Drive",
                        win32file.DRIVE_RAMDISK:   "RAM Disk",
                    }
                    dtype = type_names.get(dtype_code, "Local Drive")
                    try:
                        label = win32api.GetVolumeInformation(d)[0] or "Local Disk"
                    except Exception:
                        label = "Local Disk"

                    usage = shutil.disk_usage(d)
                    used_pct = (usage.used / usage.total * 100) if usage.total > 0 else 0
                    drives.append({
                        "letter": d,
                        "label": label,
                        "type": dtype,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "pct": used_pct,
                    })
                except Exception:
                    continue
        except Exception:
            pass

    if not drives:
        # Fallback for Linux/macOS or when win32api fails
        check_paths = [Path("/"), Path.home(), Path("C:/"), Path("D:/")]
        seen = set()
        for p in check_paths:
            try:
                if p.exists() and str(p.resolve()) not in seen:
                    seen.add(str(p.resolve()))
                    usage = shutil.disk_usage(p)
                    pct = (usage.used / usage.total * 100) if usage.total > 0 else 0
                    drives.append({
                        "letter": str(p),
                        "label": p.name or "Root",
                        "type": "Storage",
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "pct": pct,
                    })
            except Exception:
                continue

    if not drives:
        return "Could not retrieve drive information."

    lines = [f"System Storage & Drives ({len(drives)} available):"]
    for d in drives:
        bar_len = 14
        filled = int(bar_len * d["pct"] / 100)
        bar = "=" * filled + "-" * (bar_len - filled)
        status = "OK" if d["pct"] < 85 else ("WARNING" if d["pct"] < 95 else "CRITICAL")
        lines.append(
            f"  {d['letter']} [{d['label']}] ({d['type']})\n"
            f"    [{bar}] {d['pct']:.1f}% used | Free: {_format_size(d['free'])} / {_format_size(d['total'])} ({status})"
        )
    return "\n".join(lines)


# ── TREE VIEW GENERATOR ──────────────────────────────────────────────────────

def tree_view(path: str = "", max_depth: int = 2, max_items: int = 40) -> str:
    """Generate a clean visual ASCII directory tree."""
    target = _resolve_path(path) if path else _CURRENT_DIR
    if not target.exists():
        return f"Path not found: {target}"
    if not target.is_dir():
        return f"Not a directory: {target}"
    if not _is_safe_path(target):
        return f"Access denied: {target}"

    lines = [f"{target.name or str(target)}/"]
    item_count = [0]

    def _walk(p: Path, prefix: str, current_depth: int):
        if current_depth > max_depth or item_count[0] >= max_items:
            return
        try:
            entries = sorted(list(p.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        except Exception:
            return

        visible = [e for e in entries if not e.name.startswith(".")]
        total = len(visible)
        for i, entry in enumerate(visible):
            if item_count[0] >= max_items:
                lines.append(f"{prefix}... [truncated at {max_items} items]")
                break
            item_count[0] += 1
            is_last = (i == total - 1)
            connector = "\\-- " if is_last else "|-- "
            sub_prefix = "    " if is_last else "|   "
            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                _walk(entry, prefix + sub_prefix, current_depth + 1)
            else:
                try:
                    sz = _format_size(entry.stat().st_size)
                    lines.append(f"{prefix}{connector}{entry.name} ({sz})")
                except Exception:
                    lines.append(f"{prefix}{connector}{entry.name}")

    _walk(target, "", 1)
    return "\n".join(lines)


# ── IN-FILE CONTENT SEARCH (GREP) ────────────────────────────────────────────

def search_file_content(path: str = "", query: str = "", extension: str = "", max_results: int = 15) -> str:
    """Search for text or keywords inside files within a directory (deep grep)."""
    if not query:
        return "No search query provided."
    target = _resolve_path(path) if path else _CURRENT_DIR
    if not target.exists():
        return f"Search path not found: {target}"
    if not _is_safe_path(target):
        return f"Access denied: {target}"

    results = []
    clean_q = query.lower().strip()
    scanned_count = 0
    max_scan_files = 300
    ext_filter = ("." + extension.lstrip(".")).lower() if extension else ""

    for item in target.rglob("*"):
        if scanned_count >= max_scan_files or len(results) >= max_results:
            break
        if not item.is_file() or item.name.startswith("."):
            continue
        if ext_filter and item.suffix.lower() != ext_filter:
            continue
        # Skip binary, compiled, and media files
        binary_exts = {
            ".pyc", ".pyd", ".exe", ".dll", ".so", ".dylib", ".bin", ".obj",
            ".o", ".class", ".zip", ".tar", ".gz", ".7z", ".rar", ".iso",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
            ".mp4", ".mkv", ".mov", ".avi", ".mp3", ".wav", ".flac", ".ogg"
        }
        if item.suffix.lower() in binary_exts:
            continue

        # Skip files larger than 10MB
        try:
            if item.stat().st_size > 10 * 1024 * 1024:
                continue
        except Exception:
            continue

        scanned_count += 1
        try:
            # Check text files
            with open(item, "r", encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    if clean_q in line.lower():
                        snippet = line.strip()
                        if len(snippet) > 130:
                            snippet = snippet[:127] + "..."
                        results.append(f"  {item.name}:{line_num} -> {snippet}  ({item.parent})")
                        if len(results) >= max_results:
                            break
        except Exception:
            continue

    if not results:
        return f"No matches found for '{query}' in {target.name}/ (scanned {scanned_count} files)."

    return f"Found {len(results)} match(es) for '{query}' in {target.name}/:\n" + "\n".join(results)


# ── RECENT FILES DISCOVERY ───────────────────────────────────────────────────

def get_recent_files(path: str = "downloads", count: int = 10, hours: float = 0) -> str:
    """Get the most recently created or modified files in a directory."""
    target = _resolve_path(path)
    if not target.exists():
        return f"Path not found: {target}"
    if not _is_safe_path(target):
        return f"Access denied: {target}"

    count = min(max(count, 1), 50)
    files = []
    cutoff_ts = (time.time() - hours * 3600) if hours > 0 else 0

    try:
        for item in target.iterdir():
            if item.is_file() and not item.name.startswith("."):
                try:
                    mtime = item.stat().st_mtime
                    if mtime >= cutoff_ts:
                        files.append((mtime, item))
                except Exception:
                    continue
    except Exception as e:
        return f"Could not inspect recent files: {e}"

    files.sort(key=lambda x: x[0], reverse=True)
    top = files[:count]

    if not top:
        time_msg = f" in the last {hours} hours" if hours > 0 else ""
        return f"No files found in {target.name}/{time_msg}."

    lines = [f"Recent files in {target.name}/ (newest first):"]
    for mtime, f in top:
        dt_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        size_str = _format_size(f.stat().st_size)
        lines.append(f"  {dt_str} | {size_str:>9} | {f.name}")
    return "\n".join(lines)


# ── UNIVERSAL FOLDER ORGANIZER ───────────────────────────────────────────────

def organize_folder(path: str = "desktop") -> str:
    """Organize ANY folder (desktop, downloads, or custom folder) into categorized subfolders."""
    type_map = {
        "Images":     {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic", ".raw"},
        "Documents":  {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx"},
        "Videos":     {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":      {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus"},
        "Archives":   {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
        "Code":       {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".cpp", ".c", ".h", ".cs", ".go", ".rs", ".sql", ".sh", ".bat", ".ps1"},
        "Installers": {".exe", ".msi", ".dmg", ".pkg", ".appx"},
    }

    target_dir = _resolve_path(path)
    if not target_dir.exists() or not target_dir.is_dir():
        return f"Folder not found: {target_dir}"
    if not _is_safe_path(target_dir):
        return f"Access denied: {target_dir}"

    moved, skipped = [], []
    journal: list[tuple[Path, Path]] = []

    try:
        category_names = set(type_map.keys()) | {"Others"}
        for item in target_dir.iterdir():
            if item.is_dir() or item.name.startswith("."):
                continue
            if item.name in category_names:
                continue

            ext = item.suffix.lower()
            dest_folder = target_dir / "Others"
            for cat, exts in type_map.items():
                if ext in exts:
                    dest_folder = target_dir / cat
                    break

            dest_folder.mkdir(exist_ok=True)
            new_path = dest_folder / item.name

            if new_path.exists():
                skipped.append(item.name)
                continue

            origin = item.resolve()
            shutil.move(str(item), str(new_path))
            journal.append((origin, new_path.resolve()))
            moved.append(f"{item.name} -> {dest_folder.name}/")

        if journal:
            def _undo_organize(entries=tuple(journal)):
                restored = 0
                for origin, moved_to in entries:
                    try:
                        if moved_to.exists():
                            origin.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(moved_to), str(origin))
                            restored += 1
                    except Exception as e:
                        print(f"[file] undo organize error: {e}")
                for folder in {m.parent for _o, m in entries}:
                    try:
                        if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                            folder.rmdir()
                    except Exception:
                        pass
                return f"{restored} file(s) restored to {target_dir.name}/."
            push_undo(f"organized {target_dir.name}/ ({len(journal)} files)", _undo_organize)

        result = f"Organized {target_dir.name}/: {len(moved)} files moved."
        if moved:
            preview = moved[:8]
            result += "\n" + "\n".join(f"  {m}" for m in preview)
            if len(moved) > 8:
                result += f"\n  ... and {len(moved) - 8} more."
        if skipped:
            result += f"\n  {len(skipped)} file(s) skipped due to name conflict."
        return result
    except Exception as e:
        return f"Could not organize folder: {e}"


# ── DUPLICATE FILE FINDER ────────────────────────────────────────────────────

def find_duplicate_files(path: str = "downloads", max_results: int = 15) -> str:
    """Find duplicate files in a folder by size and MD5 hash."""
    target = _resolve_path(path)
    if not target.exists():
        return f"Path not found: {target}"
    if not _is_safe_path(target):
        return f"Access denied: {target}"

    by_size = defaultdict(list)
    scanned = 0
    max_scan = 1000

    for item in target.rglob("*"):
        if scanned >= max_scan:
            break
        if not item.is_file() or item.name.startswith("."):
            continue
        try:
            sz = item.stat().st_size
            if sz > 0:
                by_size[sz].append(item)
                scanned += 1
        except Exception:
            continue

    potential = {sz: paths for sz, paths in by_size.items() if len(paths) > 1}
    duplicates = []
    wasted_bytes = 0

    for sz, paths in potential.items():
        by_hash = defaultdict(list)
        for p in paths:
            try:
                h = hashlib.md5()
                with open(p, "rb") as f:
                    chunk = f.read(65536)
                    h.update(chunk)
                    if sz > 65536:
                        chunk = f.read(65536)
                        h.update(chunk)
                by_hash[h.hexdigest()].append(p)
            except Exception:
                continue

        for h, dups in by_hash.items():
            if len(dups) > 1:
                wasted_bytes += sz * (len(dups) - 1)
                duplicates.append((sz, dups))
                if len(duplicates) >= max_results:
                    break
        if len(duplicates) >= max_results:
            break

    if not duplicates:
        return f"No duplicate files detected in {target.name}/ (scanned {scanned} files)."

    lines = [f"Found {len(duplicates)} duplicate group(s) in {target.name}/ (Recoverable: {_format_size(wasted_bytes)}):"]
    for i, (sz, dups) in enumerate(duplicates, 1):
        lines.append(f"  Group #{i} ({_format_size(sz)} each):")
        for p in dups:
            lines.append(f"    - {p.name}  ({p.parent})")
    return "\n".join(lines)


# ── COMPRESSION & EXTRACTION (ZIP / UNZIP) ───────────────────────────────────

def compress_target(path: str, name: str = "", destination: str = "", format: str = "zip") -> str:
    """Compress a file or folder into a .zip archive."""
    try:
        base = _resolve_path(path)
        src = (base / name) if name else base
        if not src.exists():
            return f"Source not found: {src}"
        if not _is_safe_path(src):
            return f"Access denied: {src}"

        if destination:
            dst = _resolve_path(destination)
            if dst.is_dir():
                dst = dst / f"{src.stem}.zip"
        else:
            dst = src.parent / f"{src.stem}.zip"

        dst.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            if src.is_dir():
                for root, _, files in os.walk(src):
                    for file in files:
                        full_p = Path(root) / file
                        arcname = full_p.relative_to(src.parent)
                        z.write(full_p, arcname=arcname)
            else:
                z.write(src, arcname=src.name)

        def _undo_zip():
            if dst.exists():
                dst.unlink()
                return f"Removed created archive '{dst.name}'."
            return f"Archive '{dst.name}' already gone."
        push_undo(f"compressed {src.name} to {dst.name}", _undo_zip)

        return f"Compressed successfully: {dst.name} ({_format_size(dst.stat().st_size)})"
    except Exception as e:
        return f"Compression failed: {e}"


def extract_archive(path: str, name: str = "", destination: str = "") -> str:
    """Extract a .zip, .tar, or .tar.gz archive into a destination directory."""
    try:
        base = _resolve_path(path)
        src = (base / name) if name else base
        if not src.exists():
            return f"Archive not found: {src}"
        if not _is_safe_path(src):
            return f"Access denied: {src}"

        dst = _resolve_path(destination) if destination else src.parent / src.stem
        dst.mkdir(parents=True, exist_ok=True)

        if zipfile.is_zipfile(src):
            with zipfile.ZipFile(src, "r") as z:
                z.extractall(dst)
        elif tarfile.is_tarfile(src):
            with tarfile.open(src, "r:*") as t:
                t.extractall(dst)
        else:
            return f"Unsupported archive format: {src.suffix}"

        return f"Extracted '{src.name}' into: {dst.resolve()}"
    except Exception as e:
        return f"Extraction failed: {e}"


# ── HEAD, TAIL & CHECKSUM ────────────────────────────────────────────────────

def file_head_tail(path: str, name: str = "", lines: int = 25, from_end: bool = False) -> str:
    """Read the first or last N lines of a file."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not target.exists() or not target.is_file():
            return f"File not found: {target}"
        if not _is_safe_path(target):
            return f"Access denied: {target}"

        with open(target, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()

        selected = all_lines[-lines:] if from_end else all_lines[:lines]
        label = "Last" if from_end else "First"
        header = f"{label} {len(selected)} lines of {target.name} (Total: {len(all_lines)} lines):\n"
        return header + "".join(selected)
    except Exception as e:
        return f"Could not read lines from file: {e}"


def get_file_checksum(path: str, name: str = "", algorithm: str = "sha256") -> str:
    """Calculate the cryptographic checksum (SHA-256 or MD5) of a file."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not target.exists() or not target.is_file():
            return f"File not found: {target}"
        if not _is_safe_path(target):
            return f"Access denied: {target}"

        h = hashlib.sha256() if algorithm.lower() == "sha256" else hashlib.md5()
        with open(target, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)

        digest = h.hexdigest()
        return f"{algorithm.upper()} checksum for '{target.name}':\n  {digest}"
    except Exception as e:
        return f"Could not calculate checksum: {e}"


# ── RECYCLE BIN OPERATIONS ───────────────────────────────────────────────────

def get_recycle_bin_info() -> str:
    """Query item count and total size of deleted files in the Recycle Bin."""
    if _OS != "Windows":
        return "Recycle Bin query is only supported on Windows."
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("i64Size", ctypes.c_int64),
                ("i64NumItems", ctypes.c_int64),
            ]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        res = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if res == 0:
            size_str = _format_size(info.i64Size)
            return f"Recycle Bin status:\n  Items : {info.i64NumItems}\n  Total Size : {size_str}"
        return "Could not query Recycle Bin information."
    except Exception as e:
        return f"Recycle Bin error: {e}"


def empty_recycle_bin() -> str:
    """Empty the Recycle Bin on Windows."""
    if _OS != "Windows":
        return "Emptying trash is only implemented on Windows."
    try:
        import ctypes
        # SHERB_NOCONFIRMATION = 0x00000001, SHERB_NOPROGRESSUI = 0x00000002
        res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x00000007)
        if res == 0:
            return "Recycle Bin has been completely emptied."
        return "Recycle Bin is already empty or could not be cleared."
    except Exception as e:
        return f"Could not empty Recycle Bin: {e}"


# ── STANDARD FILE SYSTEM CRUD ────────────────────────────────────────────────

def open_file(path: str, name: str = "", read_content: bool = True) -> str:
    """Open a file on screen with its default application, and optionally read its content."""
    try:
        global _CURRENT_DIR
        base = _resolve_path(path) if path else _CURRENT_DIR
        target = (base / name) if (name and not base.name.lower() == name.lower()) else base
        if target.is_dir() and name:
            target = target / name
        elif target.is_dir() and not target.is_file():
            return open_folder(str(target))

        if not target.exists():
            try:
                for item in _CURRENT_DIR.iterdir():
                    if target.name.lower() in item.name.lower():
                        target = item
                        break
            except Exception:
                pass

        if not target.exists():
            return f"File not found: {target}"
        if not _is_safe_path(target):
            return f"Access denied: {target}"

        if _OS == "Windows":
            os.startfile(str(target))
        elif _OS == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])

        msg = f"Opened '{target.name}' in default application."
        if read_content and target.is_file():
            read_result = read_file(str(target))
            msg += f"\n\nContent:\n{read_result}"

        return msg
    except Exception as e:
        return f"Error opening file: {e}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    """List directory contents with file sizes and icons."""
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    """Create a file with content at exact destination, auto-creating parent folders."""
    try:
        global _CURRENT_DIR
        raw_path = str(path or "").strip().strip('"').strip("'")
        raw_name = str(name or "").strip().strip('"').strip("'")

        if raw_name and (":" in raw_name or "/" in raw_name or "\\" in raw_name):
            if not raw_path:
                raw_path = raw_name
                raw_name = ""
            elif raw_path.lower() in ("desktop", "current", "here", "."):
                raw_path = raw_name
                raw_name = ""

        if not raw_path and not raw_name:
            target = _CURRENT_DIR / "new_file.txt"
        elif raw_path and not raw_name:
            resolved = _resolve_path(raw_path)
            target = resolved if resolved.suffix else resolved / "new_file.txt"
        elif not raw_path and raw_name:
            target = _CURRENT_DIR / raw_name
        else:
            base = _resolve_path(raw_path)
            if base.suffix and base.name.lower() == raw_name.lower():
                target = base
            elif base.is_dir() or not base.suffix:
                target = base / raw_name
            else:
                target = base.parent / raw_name

        if not _is_safe_path(target):
            return f"Access denied: {target}"

        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        previous = None
        if existed:
            try:
                previous = target.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                previous = None

        target.write_text(content, encoding="utf-8")

        if not target.exists():
            return f"Error: File was not created at {target}"

        _CURRENT_DIR = target.parent
        push_undo(
            f"created {target.name}",
            _undo_write(target, previous) if existed else _undo_create(target),
        )
        return f"File created successfully: {target.resolve()} ({len(content)} characters written)."
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    """Create a new folder at target location."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        already = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        if not already:
            push_undo(f"created folder {target.name}", _undo_create(target))
        return f"Folder created: {target.name}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    """Safely move a file or folder to the Recycle Bin with undo capability."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home(),
            Path("C:/"), Path("D:/")
        }
        if target.resolve() in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"

        original = target.resolve()
        result = _safe_trash(target)
        if result.startswith("Moved to Trash"):
            push_undo(f"deleted {original.name}", lambda p=original: _restore_from_trash(p))
        return result
    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def move_file(path: str, name: str = "", destination: str = "") -> str:
    """Move a file or folder to destination directory."""
    try:
        base = _resolve_path(path)
        src = (base / name) if name else base
        dst = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)
        origin = src.resolve()
        shutil.move(str(src), str(dst))
        push_undo(f"moved {origin.name} to {dst.parent.name}/", _undo_move(origin, dst.resolve()))
        return f"Moved: {src.name} -> {dst.parent.name}/"
    except Exception as e:
        return f"Could not move: {e}"


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    """Copy a file or folder to destination directory."""
    try:
        base = _resolve_path(path)
        src = (base / name) if name else base
        dst = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))

        _copy = dst.resolve()
        def _undo_copy():
            if not _copy.exists():
                return f"The copy '{_copy.name}' is already gone."
            if _copy.is_dir():
                shutil.rmtree(_copy)
            else:
                _copy.unlink()
            return f"Removed the copy in {_copy.parent.name}/."
        push_undo(f"copied {src.name} to {dst.parent.name}/", _undo_copy)
        return f"Copied: {src.name} -> {dst.parent.name}/"
    except Exception as e:
        return f"Could not copy: {e}"


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    """Rename a file or folder."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if not new_name:
            return "No new name provided."

        new_path = target.parent / new_name
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        old_path = target.resolve()
        target.rename(new_path)
        push_undo(f"renamed {old_path.name} to {new_name}", _undo_move(old_path, new_path.resolve()))
        return f"Renamed: {target.name} -> {new_name}"
    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 5000, open_viewer: bool = False) -> str:
    """Read and extract text from ANY file: PDF, Word (.docx), Excel (.xlsx), CSV, Jupyter (.ipynb), text, code."""
    try:
        global _CURRENT_DIR
        base = _resolve_path(path) if path else _CURRENT_DIR
        target = (base / name) if (name and not base.name.lower() == name.lower()) else base
        if target.is_dir() and name:
            target = target / name

        if not target.exists():
            try:
                for item in _CURRENT_DIR.iterdir():
                    if target.name.lower() in item.name.lower():
                        target = item
                        break
            except Exception:
                pass

        if not target.exists():
            return f"File not found: {target.name}"
        if not target.is_file():
            return f"Not a file: {target.name}"
        if not _is_safe_path(target):
            return f"Access denied: {target}"

        if open_viewer and _OS == "Windows":
            try: os.startfile(str(target))
            except Exception: pass

        ext = target.suffix.lower()

        # 1. PDF Documents
        if ext == ".pdf":
            extracted = ""
            try:
                import pdfplumber
                with pdfplumber.open(target) as pdf:
                    for i, page in enumerate(pdf.pages):
                        txt = page.extract_text() or ""
                        if txt.strip():
                            extracted += f"--- Page {i+1} ---\n{txt}\n\n"
                        if len(extracted) >= max_chars:
                            break
            except Exception:
                try:
                    import PyPDF2
                    with open(target, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        for i, page in enumerate(reader.pages):
                            txt = page.extract_text() or ""
                            if txt.strip():
                                extracted += f"--- Page {i+1} ---\n{txt}\n\n"
                            if len(extracted) >= max_chars:
                                break
                except Exception as e:
                    return f"Error reading PDF: {e}"

            if not extracted.strip():
                return f"PDF '{target.name}' opened, but contains no extractable text (may be scanned)."
            if len(extracted) > max_chars:
                extracted = extracted[:max_chars] + f"\n\n[Truncated — {len(extracted)} total chars]"
            return f"Read from {target.name}:\n\n{extracted}"

        # 2. Word Documents (.docx)
        if ext == ".docx":
            try:
                import docx
                doc = docx.Document(target)
                doc_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                if not doc_text.strip():
                    return f"Word document '{target.name}' is empty."
                if len(doc_text) > max_chars:
                    doc_text = doc_text[:max_chars] + f"\n\n[Truncated]"
                return f"Read from {target.name}:\n\n{doc_text}"
            except Exception as e:
                return f"Error reading Word document: {e}"

        # 3. Excel Spreadsheets (.xlsx, .xls)
        if ext in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(target, read_only=True)
                summary = f"Spreadsheet with sheets: {', '.join(wb.sheetnames)}\n"
                sheet = wb.active
                rows = []
                for r in sheet.iter_rows(max_row=20, values_only=True):
                    if any(r):
                        rows.append(" | ".join(str(c) for c in r if c is not None))
                summary += "\n".join(rows[:15])
                return f"Read from {target.name}:\n\n{summary}"
            except Exception as e:
                return f"Error reading spreadsheet: {e}"

        # 4. Jupyter Notebooks (.ipynb)
        if ext == ".ipynb":
            try:
                nb = json.loads(target.read_text(encoding="utf-8", errors="ignore"))
                cells_text = []
                for idx, cell in enumerate(nb.get("cells", []), 1):
                    ctype = cell.get("cell_type", "code")
                    src = "".join(cell.get("source", []))
                    if src.strip():
                        cells_text.append(f"[{ctype.upper()} CELL {idx}]:\n{src}")
                    if sum(len(c) for c in cells_text) >= max_chars:
                        break
                joined = "\n\n".join(cells_text)
                if len(joined) > max_chars:
                    joined = joined[:max_chars] + "\n\n[Truncated]"
                return f"Read from Jupyter Notebook {target.name}:\n\n{joined}"
            except Exception as e:
                return f"Error parsing Jupyter notebook: {e}"

        # 5. Standard text / code files
        try:
            content = target.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            try:
                content = target.read_text(encoding="latin-1", errors="ignore")
            except Exception as e:
                return f"Could not read file: {e}"

        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content
    except Exception as e:
        return f"Could not read file: {e}"


def write_file(path: str, name: str = "", content: str = "", append: bool = False) -> str:
    """Write or append text content to a file."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)

        previous: str | None = None
        undoable = True
        if target.exists():
            try:
                if target.stat().st_size > _UNDO_CONTENT_LIMIT:
                    undoable = False
                else:
                    previous = target.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                undoable = False

        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)

        action = "Appended to" if append else "Written to"
        if undoable:
            push_undo(f"wrote to {target.name}", _undo_write(target, previous))
            return f"{action}: {target.name}"
        return f"{action}: {target.name}. (Too large for in-memory undo)"
    except Exception as e:
        return f"Could not write file: {e}"


def find_files(name: str = "", extension: str = "", path: str = "home", max_results: int = 20) -> str:
    """Find files by filename or extension across a folder tree."""
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results = []
        dir_count = 0
        max_dirs = 500

        for item in search_path.rglob("*"):
            if item.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    break
                continue
            if not item.is_file():
                continue
            if extension and item.suffix.lower() != ("." + extension.lstrip(".")).lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)
    except Exception as e:
        return f"Search error: {e}"


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    """Get the largest files in a directory."""
    count = min(max(count, 1), 50)
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in search_path.rglob("*"):
            if item.is_file():
                try:
                    files.append((item.stat().st_size, item))
                except Exception:
                    continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    """Get disk storage usage for a given directory or drive."""
    try:
        target = _resolve_path(path)
        usage = shutil.disk_usage(target)
        pct = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def get_file_info(path: str, name: str = "") -> str:
    """Get detailed file metadata and properties."""
    try:
        base = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        stat = target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())
    except Exception as e:
        return f"Could not get file info: {e}"


# ── MAIN DISPATCHER ──────────────────────────────────────────────────────────

def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    raw_path = (
        params.get("path")
        or params.get("file_path")
        or params.get("filepath")
        or params.get("target")
        or params.get("folder")
        or params.get("directory")
        or params.get("location")
        or ""
    )
    raw_name = (
        params.get("name")
        or params.get("filename")
        or params.get("file_name")
        or ""
    )

    path = raw_path
    name = raw_name

    if player:
        player.write_log(f"[file] {action} {name or path}")

    try:
        # 1. Navigation & Explorer Windows
        if action in ("open_folder", "navigate", "go_to", "open_dir", "cd", "explorer", "open_explorer"):
            return open_folder(path or _CURRENT_DIR)

        elif action in ("reveal", "reveal_in_explorer", "show_in_explorer", "show_in_folder", "select_in_explorer", "locate"):
            return reveal_in_explorer(path=path, name=name)

        elif action in ("back", "navigate_back", "go_back"):
            return navigate_back()

        elif action in ("forward", "navigate_forward", "go_forward"):
            return navigate_forward()

        elif action in ("up", "navigate_up", "parent"):
            return navigate_up()

        elif action in ("history", "nav_history", "breadcrumbs"):
            return get_navigation_history()

        elif action in ("open_explorers", "open_windows", "list_explorers"):
            return get_open_explorers()

        elif action in ("close_explorer", "close_explorers"):
            return close_explorer(path=path)

        # 2. Drives & Storage
        elif action in ("drives", "list_drives", "all_drives", "get_drives", "storage"):
            return list_drives()

        elif action in ("disk_usage", "usage", "storage_usage"):
            return get_disk_usage(path or _CURRENT_DIR)

        # 3. Viewing & Inspecting
        elif action in ("open_file", "open", "launch", "view"):
            p_res = _resolve_path(path) if path else _CURRENT_DIR
            if p_res.is_dir() and not name:
                return open_folder(str(p_res))
            return open_file(path, name=name)

        elif action in ("list", "ls", "dir"):
            return list_files(path or _CURRENT_DIR)

        elif action in ("tree", "tree_view", "hierarchy", "folder_tree"):
            return tree_view(
                path=path,
                max_depth=int(params.get("max_depth") or params.get("depth") or 2),
                max_items=int(params.get("max_items", 40))
            )

        elif action in ("read", "read_file"):
            return read_file(path, name=name)

        elif action in ("head", "first_lines"):
            return file_head_tail(
                path=path, name=name,
                lines=int(params.get("lines") or params.get("count") or 25),
                from_end=False
            )

        elif action in ("tail", "last_lines"):
            return file_head_tail(
                path=path, name=name,
                lines=int(params.get("lines") or params.get("count") or 25),
                from_end=True
            )

        elif action in ("info", "properties", "stat"):
            return get_file_info(path, name=name)

        elif action in ("checksum", "hash", "sha256", "md5"):
            return get_file_checksum(
                path=path, name=name,
                algorithm=params.get("algorithm", "sha256")
            )

        # 4. Search & Discovery
        elif action in ("find", "find_files", "search"):
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path or "home",
                max_results=min(int(params.get("max_results", 20)), 50),
            )

        elif action in ("search_content", "grep", "find_in_files", "search_in_files", "contains"):
            return search_file_content(
                path=path or _CURRENT_DIR,
                query=params.get("query") or params.get("content") or name,
                extension=params.get("extension", ""),
                max_results=min(int(params.get("max_results", 15)), 40),
            )

        elif action in ("recent", "recent_files", "latest", "latest_files"):
            return get_recent_files(
                path=path or "downloads",
                count=int(params.get("count", 10)),
                hours=float(params.get("hours", 0)),
            )

        elif action in ("largest", "big_files"):
            return get_largest_files(
                path=path or "downloads",
                count=int(params.get("count", 10)),
            )

        elif action in ("duplicates", "find_duplicates", "dup_files"):
            return find_duplicate_files(
                path=path or "downloads",
                max_results=int(params.get("max_results", 15))
            )

        # 5. File Operations & Creation
        elif action in ("create_file", "create", "write_file", "make_file", "new_file"):
            return create_file(path=path, name=name, content=params.get("content", ""))

        elif action in ("create_folder", "make_folder", "mkdir"):
            return create_folder(path, name=name)

        elif action == "delete":
            return delete_file(path, name=name)

        elif action == "move":
            return move_file(path, name=name, destination=params.get("destination", ""))

        elif action == "copy":
            return copy_file(path, name=name, destination=params.get("destination", ""))

        elif action == "rename":
            return rename_file(path, name=name, new_name=params.get("new_name", ""))

        elif action == "write":
            return write_file(
                path, name=name,
                content=params.get("content", ""),
                append=params.get("append", False)
            )

        # 6. Organization & Compression
        elif action in ("organize", "organize_folder", "organize_desktop", "clean_folder", "clean_desktop"):
            return organize_folder(path=path or "desktop")

        elif action in ("zip", "compress", "archive"):
            return compress_target(
                path=path, name=name,
                destination=params.get("destination", ""),
                format=params.get("format", "zip")
            )

        elif action in ("unzip", "extract", "decompress"):
            return extract_archive(
                path=path, name=name,
                destination=params.get("destination", "")
            )

        # 7. Recycle Bin
        elif action in ("recycle_bin", "trash_info", "bin_status"):
            return get_recycle_bin_info()

        elif action in ("empty_trash", "empty_recycle_bin"):
            return empty_recycle_bin()

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"


# ── TOOL DECLARATION (AUTO-DISCOVERED BY CORE/ACTION_LOADER.PY) ──────────────
TOOL = {
    "name": "file_controller",
    "description": (
        "Universal file system controller & explorer with full Windows integration: "
        "open_folder (navigates to drive D:, Desktop, or any folder in File Explorer and shows contents), "
        "reveal (opens File Explorer with that exact file or folder selected/highlighted on screen), "
        "list_drives (shows all drives C:, D:, E:, etc. with labels, types, and free space meters), "
        "tree (visualizes hierarchical folder tree), "
        "recent_files (finds newly downloaded or modified files), "
        "search_content / grep (searches for text or code INSIDE files), "
        "organize_folder (categorizes files in Desktop, Downloads, or any folder into Images, Documents, Code, etc. with instant undo), "
        "open_file (launches file on screen and reads content), "
        "read (extracts text from PDF, Word .docx, Excel, Jupyter .ipynb, code, text), "
        "create_file, create_folder, delete, move, copy, rename, zip, unzip, duplicates, head, tail, checksum, back, up, recycle_bin. "
        "ALWAYS use this tool for file/folder navigation, creation, and explorer control."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "open_folder | reveal | list_drives | tree | list | open_file | read | "
                    "create_file | create_folder | delete | move | copy | rename | write | "
                    "find | search_content | recent_files | largest | duplicates | organize_folder | "
                    "zip | unzip | head | tail | checksum | back | forward | up | history | "
                    "recycle_bin | empty_trash | open_explorers | close_explorer | info"
                )
            },
            "path": {
                "type": "STRING",
                "description": "File or folder path or shortcut: 'desktop', 'downloads', 'documents', 'D:/', 'D:/folder', 'drive e', 'C:/file.txt'"
            },
            "name": {
                "type": "STRING",
                "description": "File or folder name for search, open, create, delete, or reveal"
            },
            "destination": {
                "type": "STRING",
                "description": "Destination directory or file path for move, copy, zip, or unzip"
            },
            "new_name": {
                "type": "STRING",
                "description": "New filename for rename action"
            },
            "content": {
                "type": "STRING",
                "description": "Content for create_file/write or search query for search_content"
            },
            "query": {
                "type": "STRING",
                "description": "Search keyword or text for search_content / grep"
            },
            "extension": {
                "type": "STRING",
                "description": "File extension filter (e.g. '.pdf', '.py', '.txt')"
            },
            "count": {
                "type": "INTEGER",
                "description": "Number of results for largest or recent_files"
            },
            "depth": {
                "type": "INTEGER",
                "description": "Max depth level for tree view (default: 2)"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": file_controller,
}
