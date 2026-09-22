"""Central path security and C: drive protection for AUREX.

Treats the entire C: drive as READ-ONLY and PROTECTED.
Resolves canonical paths to prevent traversal, symlink, or junction bypasses.
"""

import os
import sys
from pathlib import Path
from typing import Tuple, List, Optional
from app.config.settings import get_settings


class PathSecurityError(PermissionError):
    """Raised when an operation violates AUREX filesystem security policy."""
    pass


def canonical_path(path_input: str | Path) -> Path:
    """
    Resolve a path to its strict canonical, real filesystem path.
    Handles relative paths, traversal tricks (e.g., ..\\..\\),
    Windows extended path prefixes (\\\\?\\, \\\\.\\), and symlinks/junctions.
    If the target does not yet exist, its existing ancestor is resolved.
    """
    if isinstance(path_input, Path):
        raw_str = str(path_input)
    else:
        raw_str = str(path_input).strip()

    # Strip Windows extended-length path prefixes for normalized checking
    clean_str = raw_str
    if clean_str.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        clean_str = clean_str[4:]

    # Remove quotes if present
    clean_str = clean_str.strip('"').strip("'")

    p = Path(clean_str)

    # If the file/folder exists, use realpath/resolve directly
    if p.exists():
        try:
            return Path(os.path.realpath(p.resolve()))
        except Exception:
            return Path(os.path.abspath(clean_str))

    # If it does not exist yet (e.g., target for write/create),
    # resolve the deepest existing parent and reconstruct the tail.
    parts = list(p.parts)
    if not parts:
        return Path(os.path.abspath("."))

    # Find the deepest parent that actually exists
    curr = p
    tail_parts = []
    while not curr.exists() and len(curr.parts) > 1:
        tail_parts.insert(0, curr.name)
        curr = curr.parent

    try:
        resolved_parent = Path(os.path.realpath(curr.resolve()))
    except Exception:
        resolved_parent = Path(os.path.abspath(curr))

    # Reassemble with the pending non-existent children
    reconstructed = resolved_parent
    for part in tail_parts:
        reconstructed = reconstructed / part

    return Path(os.path.normpath(str(reconstructed)))


def is_c_drive(resolved_path: Path) -> bool:
    """Determine if a resolved path is on the C: drive."""
    path_str = str(resolved_path).upper()
    drive = resolved_path.drive.upper()
    if drive == "C:":
        return True
    if path_str.startswith("C:") or path_str.startswith(("\\\\?\\C:", "//?/C:", "\\\\.\\C:", "//./C:")):
        return True
    return False


def is_path_allowed(
    path_input: str | Path,
    is_write: bool = True,
    allowed_dirs: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """
    Validate whether an operation on path_input is permissible under AUREX security rules.

    Rules:
    1. C: drive is STRICTLY READ-ONLY. No write, delete, move, create, or modify operation
       is ever permitted if the destination resolves to C:.
       Rejection message: 'ACCESS DENIED: AUREX is not permitted to modify the C: drive.'
    2. Write operations must resolve into an approved workspace directory (e.g., D:\\AUREX, D:\\Projects).
    3. Traversal attempts (e.g., D:\\AUREX\\..\\..\\C:\\Windows) resolve to their actual destination
       and are rejected accordingly.

    Returns:
        (True, "") if allowed.
        (False, error_reason) if rejected.
    """
    try:
        resolved = canonical_path(path_input)
    except Exception as e:
        return False, f"ACCESS DENIED: Invalid or unresolvable path '{path_input}': {e}"

    # RULE 1: C: DRIVE WRITE PROTECTION (HARD POLICY)
    if is_write:
        if is_c_drive(resolved):
            return False, "ACCESS DENIED: AUREX is not permitted to modify the C: drive."

        # RULE 2: ALLOWED WORKSPACE ENFORCEMENT
        settings = get_settings()
        configured_allowed = allowed_dirs or settings.allowed_directories

        # Canonicalize all approved directories
        canonical_allowed: List[Path] = []
        for d in configured_allowed:
            try:
                can_d = canonical_path(d)
                # Never allow C: in approved directories even if entered in config
                if not is_c_drive(can_d):
                    canonical_allowed.append(can_d)
            except Exception:
                continue

        # Check if resolved path is inside any approved directory
        is_inside_allowed = False
        resolved_str = str(resolved).lower()
        for allowed in canonical_allowed:
            allowed_str = str(allowed).lower()
            try:
                # Check with relative_to or prefix match
                resolved.relative_to(allowed)
                is_inside_allowed = True
                break
            except ValueError:
                # On Windows drive letters match check
                if resolved_str.startswith(allowed_str + os.sep) or resolved_str == allowed_str:
                    is_inside_allowed = True
                    break

        if not is_inside_allowed:
            return (
                False,
                f"ACCESS DENIED: Destination '{resolved}' is outside approved workspace directories. "
                f"Approved locations: {', '.join(str(a) for a in canonical_allowed)}"
            )

    return True, ""


def check_path_security(path_input: str | Path, is_write: bool = True) -> Path:
    """
    Convenience function that validates the path and raises PathSecurityError if forbidden.
    Returns the resolved Path if allowed.
    """
    allowed, reason = is_path_allowed(path_input, is_write=is_write)
    if not allowed:
        raise PathSecurityError(reason)
    return canonical_path(path_input)
