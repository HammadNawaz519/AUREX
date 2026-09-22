"""Controlled terminal and shell execution tools for AUREX.

Enforces strict CommandValidator checks and prevents any arbitrary C: writes or security bypasses.
"""

import subprocess
import os
from typing import Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult
from app.core.validator import CommandValidator
from app.core.security import canonical_path, is_path_allowed
from app.config.settings import get_settings


class ExecuteCommandTool(BaseTool):
    name = "execute_command"
    description = "Execute a safe PowerShell or CMD command within an approved workspace directory."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute"},
            "cwd": {"type": "string", "description": "Working directory (must be inside approved workspace)"}
        },
        "required": ["command"]
    }
    is_write = True
    is_shell = True

    def execute(self, command: str, cwd: Optional[str] = None, **kwargs) -> ToolResult:
        # 1. Run through CommandValidator
        allowed, reason, req_confirm = CommandValidator.validate(command)
        if not allowed:
            return ToolResult(success=False, error=reason)

        # 2. Check working directory
        settings = get_settings()
        work_dir = cwd or settings.workspace_root
        allowed_dir, dir_reason = is_path_allowed(work_dir, is_write=True)
        if not allowed_dir:
            return ToolResult(success=False, error=f"Invalid working directory: {dir_reason}")

        try:
            resolved_cwd = canonical_path(work_dir)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=str(resolved_cwd),
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"

            success = (result.returncode == 0)
            return ToolResult(
                success=success,
                data={
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                },
                message=output.strip() or f"Command exited with code {result.returncode}"
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Command execution timed out (30s limit).")
        except Exception as e:
            return ToolResult(success=False, error=f"Command failed to execute: {e}")
