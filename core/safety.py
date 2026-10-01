"""
core/safety.py — Central Filesystem & Subprocess Safety Layer for AUREX.

HIGHEST PRIORITY RULES:
1. C: DRIVE — ABSOLUTELY NO INTENTIONAL ACCESS (Read, Write, List, Search, Delete, etc.).
   Returns: "BLOCKED: AUREX is not permitted to access the C: drive."
2. D: DRIVE — FULL NORMAL ACCESS (Read, List, Search, Create, Edit, Rename, Append, etc.)
   EXCEPT DELETION: ABSOLUTELY ZERO DELETION ON D: (No files, folders, temp, cache, backups).
   Returns: "Blocked: AUREX cannot delete files or folders on the D: drive."
3. LOWEST-LEVEL ENFORCEMENT:
   Patches os.remove, os.unlink, os.rmdir, Path.unlink, Path.rmdir, shutil.rmtree, send2trash,
   and subprocess execution of destructive shell commands.
"""

from __future__ import annotations

import inspect
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional, Union

_OS = platform.system()
_AUREX_ROOT = Path(__file__).resolve().parent.parent

# Error messages matching exact policy specifications
MSG_C_DRIVE_BLOCKED = "BLOCKED: AUREX is not permitted to access the C: drive."
MSG_D_DELETE_BLOCKED = "Blocked: AUREX cannot delete files or folders on the D: drive."


def canonicalize(p: Union[str, Path, None]) -> Path:
    """Canonicalize and resolve a path completely handling .., symlinks, env vars."""
    if p is None:
        return Path(".")
    s = str(p).strip().strip('"').strip("'")
    if not s:
        return Path(".")
    try:
        exp = os.path.expandvars(os.path.expanduser(s))
        return Path(exp).resolve()
    except Exception:
        try:
            return Path(s).resolve()
        except Exception:
            return Path(s)


def is_c_drive(p: Union[str, Path, None]) -> bool:
    """Returns True if the path targets or resolves to the C: drive."""
    if p is None:
        return False
    s = str(p).strip().strip('"').strip("'")
    if not s:
        return False
    # Direct string pattern checks
    norm = s.replace("\\", "/")
    if re.match(r"^[cC]:", norm) or norm.lower().startswith(("/c/", "c:/")):
        return True
    # Canonical path resolution
    try:
        c = canonicalize(p)
        if c.drive.upper() == "C:":
            return True
    except Exception:
        # Fail closed on ambiguity
        return True
    return False


def is_d_drive(p: Union[str, Path, None]) -> bool:
    """Returns True if the path targets or resolves to the D: drive."""
    if p is None:
        return False
    s = str(p).strip().strip('"').strip("'")
    if not s:
        return False
    norm = s.replace("\\", "/")
    if re.match(r"^[dD]:", norm) or norm.lower().startswith(("/d/", "d:/")):
        return True
    try:
        c = canonicalize(p)
        return c.drive.upper() == "D:"
    except Exception:
        return False


def is_aurex_root(p: Union[str, Path, None]) -> bool:
    """Returns True if the path targets or is inside the AUREX project root."""
    try:
        c = canonicalize(p)
        return c == _AUREX_ROOT or c.is_relative_to(_AUREX_ROOT)
    except Exception:
        return False


def guard_path_access(p: Union[str, Path, None]) -> Optional[str]:
    """
    Validates that a path is permitted for non-destructive operations.
    Returns error string if blocked, or None if permitted.
    """
    if is_c_drive(p):
        return MSG_C_DRIVE_BLOCKED
    return None


def guard_deletion(p: Union[str, Path, None]) -> Optional[str]:
    """
    Validates a deletion target.
    Deletion is permanently forbidden on D: drive (and C: is blocked from all access).
    """
    if is_c_drive(p):
        return MSG_C_DRIVE_BLOCKED
    if is_d_drive(p):
        return MSG_D_DELETE_BLOCKED
    # Any attempt to delete is blocked under zero-delete policy
    return MSG_D_DELETE_BLOCKED


_DELETION_CMD_REGEX = re.compile(
    r"\b(?:del|erase|rmdir|rd|remove-item|rm|ri|git\s+rm|git\s+clean|os\.remove|os\.unlink|os\.rmdir|shutil\.rmtree|Path\.unlink|Path\.rmdir|send2trash)\b",
    re.IGNORECASE
)


def guard_action_call(name: str, parameters: dict) -> Optional[str]:
    """
    Checks incoming tool/plugin action and parameters before dispatch.
    Returns error message if blocked, or None if permitted.
    """
    if not isinstance(parameters, dict):
        return None

    # Check for deletion action intent
    action_val = str(
        parameters.get("action", "") or parameters.get("operation", "") or parameters.get("cmd", "")
    ).lower().strip()
    if action_val in ("delete", "remove", "unlink", "rmtree", "empty_trash", "empty_recycle_bin", "purge", "trash"):
        return MSG_D_DELETE_BLOCKED

    # Check all parameter values recursively
    def _check_val(val: Any) -> Optional[str]:
        if isinstance(val, (str, Path)):
            s = str(val).strip()
            # If targets C:
            if is_c_drive(s):
                return MSG_C_DRIVE_BLOCKED
            # If parameter has explicit delete instruction or destructive command
            if _DELETION_CMD_REGEX.search(s):
                if is_d_drive(s) or "d:" in s.lower():
                    return MSG_D_DELETE_BLOCKED
        elif isinstance(val, dict):
            for k, v in val.items():
                if str(k).lower() in ("delete", "remove") and v is True:
                    return MSG_D_DELETE_BLOCKED
                err = _check_val(v)
                if err:
                    return err
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                err = _check_val(item)
                if err:
                    return err
        return None

    return _check_val(parameters)


# ── LOWEST-LEVEL PYTHON HOOKS ────────────────────────────────────────────────

_orig_os_remove = os.remove
_orig_os_unlink = os.unlink
_orig_os_rmdir = os.rmdir
_orig_path_unlink = Path.unlink
_orig_path_rmdir = Path.rmdir
_orig_shutil_rmtree = shutil.rmtree
_orig_subprocess_Popen = subprocess.Popen


def _is_tempfile_internal(path: Any) -> bool:
    """Detects internal Python runtime tempfile module bootstrapping probes."""
    try:
        s = str(path)
        if "Temp" in s or "temp" in s or "tmp" in s:
            for frame in inspect.stack()[1:5]:
                if "tempfile.py" in frame.filename:
                    return True
    except Exception:
        pass
    return False


def _hooked_os_remove(path, *args, **kwargs):
    if is_d_drive(path):
        raise PermissionError(MSG_D_DELETE_BLOCKED)
    if is_c_drive(path) and not _is_tempfile_internal(path):
        raise PermissionError(MSG_C_DRIVE_BLOCKED)
    return _orig_os_remove(path, *args, **kwargs)


def _hooked_os_unlink(path, *args, **kwargs):
    if is_d_drive(path):
        raise PermissionError(MSG_D_DELETE_BLOCKED)
    if is_c_drive(path) and not _is_tempfile_internal(path):
        raise PermissionError(MSG_C_DRIVE_BLOCKED)
    return _orig_os_unlink(path, *args, **kwargs)


def _hooked_os_rmdir(path, *args, **kwargs):
    if is_d_drive(path):
        raise PermissionError(MSG_D_DELETE_BLOCKED)
    if is_c_drive(path):
        raise PermissionError(MSG_C_DRIVE_BLOCKED)
    return _orig_os_rmdir(path, *args, **kwargs)


def _hooked_path_unlink(self, *args, **kwargs):
    if is_d_drive(self):
        raise PermissionError(MSG_D_DELETE_BLOCKED)
    if is_c_drive(self) and not _is_tempfile_internal(self):
        raise PermissionError(MSG_C_DRIVE_BLOCKED)
    return _orig_path_unlink(self, *args, **kwargs)


def _hooked_path_rmdir(self, *args, **kwargs):
    if is_d_drive(self):
        raise PermissionError(MSG_D_DELETE_BLOCKED)
    if is_c_drive(self):
        raise PermissionError(MSG_C_DRIVE_BLOCKED)
    return _orig_path_rmdir(self, *args, **kwargs)


def _hooked_shutil_rmtree(path, *args, **kwargs):
    if is_d_drive(path):
        raise PermissionError(MSG_D_DELETE_BLOCKED)
    if is_c_drive(path):
        raise PermissionError(MSG_C_DRIVE_BLOCKED)
    return _orig_shutil_rmtree(path, *args, **kwargs)


class _SafePopen(_orig_subprocess_Popen):
    def __init__(self, args, **kwargs):
        cwd = kwargs.get("cwd")
        err = validate_command_line(args, cwd)
        if err:
            raise PermissionError(err)
        super().__init__(args, **kwargs)


def install_filesystem_hooks():
    """Installs low-level python filesystem protection hooks."""
    os.remove = _hooked_os_remove
    os.unlink = _hooked_os_unlink
    os.rmdir = _hooked_os_rmdir
    Path.unlink = _hooked_path_unlink
    Path.rmdir = _hooked_path_rmdir
    shutil.rmtree = _hooked_shutil_rmtree

    try:
        import send2trash
        def _hooked_send2trash(path, *args, **kwargs):
            if is_d_drive(path):
                raise PermissionError(MSG_D_DELETE_BLOCKED)
            if is_c_drive(path):
                raise PermissionError(MSG_C_DRIVE_BLOCKED)
            return None
        send2trash.send2trash = _hooked_send2trash
    except Exception:
        pass

    if subprocess.Popen is not _SafePopen:
        subprocess.Popen = _SafePopen


# ── SUBPROCESS / SHELL HOOKS ────────────────────────────────────────────────

def _cmd_targets_c_drive(cmd: Any) -> bool:
    """Returns True if command arguments intentionally target files/folders on C:."""
    if isinstance(cmd, (list, tuple)):
        tokens = [str(x) for x in cmd]
        if not tokens:
            return False
        # If there are arguments after the binary
        for arg in tokens[1:]:
            if is_c_drive(arg) or re.search(r"(?:^|[\s\"'=])(?:[cC]:[/\\]|/[cC]/)", arg):
                return True
        # If only 1 token (the command itself)
        if len(tokens) == 1:
            token = tokens[0].strip()
            if is_c_drive(token) and not token.lower().endswith(("\\python.exe", "/python.exe", "\\pythonw.exe", "/pythonw.exe")):
                return True
        return False
    else:
        s = str(cmd or "").strip()
        if not s:
            return False
        # Match leading executable: either quoted "..." or unquoted token
        m = re.match(r'^\s*("[^"]+"|\S+)\s*(.*)$', s)
        if m:
            first, rest = m.group(1), m.group(2)
            if re.search(r"(?:^|[\s\"'=])(?:[cC]:[/\\]|/[cC]/)", rest):
                return True
            first_unquoted = first.strip('"').strip("'")
            if is_c_drive(first_unquoted) and not first_unquoted.lower().endswith(("\\python.exe", "/python.exe", "\\pythonw.exe", "/pythonw.exe")):
                return True
            first_base = Path(first_unquoted).name.lower()
            if first_base in ("dir", "type", "del", "erase", "rmdir", "rd", "copy", "move", "find", "findstr"):
                if re.search(r"[cC]:", s):
                    return True
        return False


def validate_command_line(cmd: Any, cwd: Any = None) -> Optional[str]:
    """
    Inspects command line and working directory for shell deletion on D: or access to C:.
    Returns error string if forbidden, or None if permitted.
    """
    if cwd and is_c_drive(cwd):
        return MSG_C_DRIVE_BLOCKED

    # Check for C: drive targeting
    if _cmd_targets_c_drive(cmd):
        return MSG_C_DRIVE_BLOCKED

    if isinstance(cmd, (list, tuple)):
        cmd_str = " ".join(str(c) for c in cmd)
    else:
        cmd_str = str(cmd or "")

    # Check for destructive shell deletion
    if _DELETION_CMD_REGEX.search(cmd_str):
        effective_cwd = cwd or Path.cwd()
        if is_d_drive(cmd_str) or is_d_drive(effective_cwd) or ("d:" in cmd_str.lower()):
            return MSG_D_DELETE_BLOCKED
        return MSG_D_DELETE_BLOCKED

    return None


# Install hooks immediately upon module load
install_filesystem_hooks()
