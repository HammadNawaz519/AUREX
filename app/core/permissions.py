"""Tool permission and confirmation management system for AUREX.

Enforces three tiers:
- SAFE: Runs automatically (reads, app launches, telemetry, workspace creates)
- CONFIRM: Prompts user via confirmation modal (deletes, bulk moves, shell commands, shutdowns)
- BLOCKED: Prohibited actions that are never permitted (C: writes, system tampering)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any
from app.core.security import is_path_allowed, is_c_drive, canonical_path


class ActionLevel(Enum):
    SAFE = "SAFE"
    CONFIRM = "CONFIRM"
    BLOCKED = "BLOCKED"


@dataclass
class ActionRequest:
    action_type: str
    description: str
    target_paths: List[str] = field(default_factory=list)
    level: ActionLevel = ActionLevel.SAFE
    reason: str = ""
    metadata: dict = field(default_factory=dict)


class PermissionManager:
    """Manages evaluation and confirmation dispatch for computer control actions."""

    def __init__(self):
        self._confirmation_handler: Optional[Callable[[ActionRequest], bool]] = None

    def set_confirmation_handler(self, handler: Callable[[ActionRequest], bool]):
        """Set the GUI callback to present confirmation dialogs."""
        self._confirmation_handler = handler

    def evaluate_action(
        self,
        action_type: str,
        target_paths: Optional[List[str]] = None,
        description: str = "",
        is_write: bool = False,
        is_shell: bool = False,
        file_count: int = 1,
        metadata: Optional[dict] = None
    ) -> ActionRequest:
        """
        Classify an intended action into SAFE, CONFIRM, or BLOCKED.
        """
        targets = target_paths or []
        meta = metadata or {}
        req = ActionRequest(
            action_type=action_type,
            description=description or f"Perform {action_type}",
            target_paths=targets,
            metadata=meta
        )

        # 1. HARD BLOCK CHECK: Any write/delete to C: is permanently BLOCKED
        if is_write or action_type in ("write_file", "delete_file", "move_file", "rename_file", "create_folder"):
            for t in targets:
                allowed, reason = is_path_allowed(t, is_write=True)
                if not allowed:
                    req.level = ActionLevel.BLOCKED
                    req.reason = reason
                    return req

        # 2. SHELL COMMANDS: Require confirmation by default
        if is_shell:
            req.level = ActionLevel.CONFIRM
            req.reason = "Shell execution requires user verification."
            return req

        # 3. DESTRUCTIVE / SENSITIVE ACTIONS: Require user confirmation
        if action_type in ("delete_file", "delete_folder"):
            req.level = ActionLevel.CONFIRM
            req.reason = f"Deleting {file_count} file(s) permanently."
            return req

        if action_type in ("move_file", "move_folder") and file_count > 5:
            req.level = ActionLevel.CONFIRM
            req.reason = f"Moving {file_count} files in bulk."
            return req

        if action_type in ("system_shutdown", "system_restart"):
            req.level = ActionLevel.CONFIRM
            req.reason = "System power state modification."
            return req

        # 4. DEFAULT TO SAFE for vetted operations
        req.level = ActionLevel.SAFE
        return req

    def authorize(self, request: ActionRequest) -> bool:
        """
        Check if the action is authorized to proceed.
        Returns True if SAFE or confirmed by user, False if BLOCKED or rejected.
        """
        if request.level == ActionLevel.BLOCKED:
            return False

        if request.level == ActionLevel.SAFE:
            return True

        if request.level == ActionLevel.CONFIRM:
            if self._confirmation_handler:
                return self._confirmation_handler(request)
            # If no GUI dialog handler attached (headless/fallback), reject for safety
            return False

        return False


_global_permission_manager = PermissionManager()

def get_permission_manager() -> PermissionManager:
    return _global_permission_manager
