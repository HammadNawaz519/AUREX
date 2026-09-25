"""Filesystem manipulation tools for AUREX.

Enforces zero-compromise C: drive write protection.
Every write/modify/delete/move/rename operation must pass is_path_allowed.
"""

import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.tools.base import BaseTool, ToolResult
from app.core.security import is_path_allowed, canonical_path, PathSecurityError
from app.config.settings import get_settings


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read text content from a file."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative path to the file"}
        },
        "required": ["path"]
    }
    is_write = False

    def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            resolved = canonical_path(path)
            if not resolved.exists():
                return ToolResult(success=False, error=f"File not found: '{path}'")
            if resolved.is_dir():
                return ToolResult(success=False, error=f"Path is a directory, not a file: '{path}'")

            # Limit read size to 1 MB for safety
            if resolved.stat().st_size > 1024 * 1024:
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(1024 * 1024) + "\n... [TRUNCATED at 1MB]"
            else:
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

            return ToolResult(success=True, data=content, message=f"Successfully read {len(content)} characters from {resolved.name}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read file: {e}")


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create or overwrite a file with given text content inside approved workspace or user's Desktop (e.g., 'desktop/notes.txt')."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Destination file path"},
            "content": {"type": "string", "description": "Text content to write"}
        },
        "required": ["path", "content"]
    }
    is_write = True

    def execute(self, path: str, content: str = "", **kwargs) -> ToolResult:
        allowed, reason = is_path_allowed(path, is_write=True)
        if not allowed:
            return ToolResult(success=False, error=reason)

        try:
            resolved = canonical_path(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, data=str(resolved), message=f"Successfully wrote {len(content)} characters to {resolved}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write file: {e}")


class CreateFolderTool(BaseTool):
    name = "create_folder"
    description = "Create a directory inside approved workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to create"}
        },
        "required": ["path"]
    }
    is_write = True

    def execute(self, path: str, **kwargs) -> ToolResult:
        allowed, reason = is_path_allowed(path, is_write=True)
        if not allowed:
            return ToolResult(success=False, error=reason)

        try:
            resolved = canonical_path(path)
            resolved.mkdir(parents=True, exist_ok=True)
            return ToolResult(success=True, data=str(resolved), message=f"Created folder: {resolved}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create folder: {e}")


class MoveFileTool(BaseTool):
    name = "move_file"
    description = "Move a file or directory from source to destination within approved workspace."
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source path"},
            "destination": {"type": "string", "description": "Destination path"}
        },
        "required": ["source", "destination"]
    }
    is_write = True

    def execute(self, source: str, destination: str, **kwargs) -> ToolResult:
        # Both source and destination must be write-permitted (moving deletes source)
        for p, label in [(source, "Source"), (destination, "Destination")]:
            allowed, reason = is_path_allowed(p, is_write=True)
            if not allowed:
                return ToolResult(success=False, error=f"{label} {reason}")

        try:
            src = canonical_path(source)
            dst = canonical_path(destination)
            if not src.exists():
                return ToolResult(success=False, error=f"Source does not exist: {source}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            final_dst = shutil.move(str(src), str(dst))
            return ToolResult(success=True, data=final_dst, message=f"Moved '{src.name}' to '{final_dst}'")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to move: {e}")


class CopyFileTool(BaseTool):
    name = "copy_file"
    description = "Copy a file from source to destination."
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source file path"},
            "destination": {"type": "string", "description": "Destination file path"}
        },
        "required": ["source", "destination"]
    }
    is_write = True

    def execute(self, source: str, destination: str, **kwargs) -> ToolResult:
        allowed, reason = is_path_allowed(destination, is_write=True)
        if not allowed:
            return ToolResult(success=False, error=reason)

        try:
            src = canonical_path(source)
            dst = canonical_path(destination)
            if not src.exists():
                return ToolResult(success=False, error=f"Source does not exist: {source}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                final_dst = shutil.copytree(str(src), str(dst))
            else:
                final_dst = shutil.copy2(str(src), str(dst))
            return ToolResult(success=True, data=final_dst, message=f"Copied '{src.name}' to '{final_dst}'")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to copy: {e}")


class DeleteFileTool(BaseTool):
    name = "delete_file"
    description = "Delete a file or empty folder inside approved workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to delete"}
        },
        "required": ["path"]
    }
    is_write = True

    def execute(self, path: str, **kwargs) -> ToolResult:
        allowed, reason = is_path_allowed(path, is_write=True)
        if not allowed:
            return ToolResult(success=False, error=reason)

        try:
            resolved = canonical_path(path)
            if not resolved.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")

            if resolved.is_file():
                resolved.unlink()
                return ToolResult(success=True, message=f"Deleted file: {resolved}")
            elif resolved.is_dir():
                shutil.rmtree(str(resolved))
                return ToolResult(success=True, message=f"Deleted directory: {resolved}")
            return ToolResult(success=False, error="Unknown file type.")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to delete: {e}")


class RenameFileTool(BaseTool):
    name = "rename_file"
    description = "Rename a file or folder inside approved workspace."
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Existing path"},
            "new_name": {"type": "string", "description": "New filename or relative name"}
        },
        "required": ["source", "new_name"]
    }
    is_write = True

    def execute(self, source: str, new_name: str, **kwargs) -> ToolResult:
        src = canonical_path(source)
        dst = src.parent / new_name

        for p, label in [(src, "Source"), (dst, "Destination")]:
            allowed, reason = is_path_allowed(p, is_write=True)
            if not allowed:
                return ToolResult(success=False, error=f"{label} {reason}")

        try:
            if not src.exists():
                return ToolResult(success=False, error=f"Path not found: {source}")
            os.rename(src, dst)
            return ToolResult(success=True, data=str(dst), message=f"Renamed '{src.name}' to '{new_name}'")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to rename: {e}")


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List items in a folder with sizes and dates."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list"}
        },
        "required": ["path"]
    }
    is_write = False

    def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            resolved = canonical_path(path)
            if not resolved.exists() or not resolved.is_dir():
                return ToolResult(success=False, error=f"Directory does not exist: {path}")

            items = []
            for entry in resolved.iterdir():
                try:
                    stat = entry.stat()
                    items.append({
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "size_bytes": stat.st_size if not entry.is_dir() else 0,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    })
                except Exception:
                    continue

            # Sort directories first, then alphabetically
            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            return ToolResult(success=True, data=items, message=f"Found {len(items)} items in {resolved}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list directory: {e}")


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search for files by name pattern or extension within an approved directory."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "File search pattern or extension, e.g. *.py, report, .pdf"},
            "directory": {"type": "string", "description": "Directory to search in (defaults to workspace root)"}
        },
        "required": ["query"]
    }
    is_write = False

    def execute(self, query: str, directory: Optional[str] = None, **kwargs) -> ToolResult:
        settings = get_settings()
        root = canonical_path(directory or settings.workspace_root)
        if not root.exists():
            return ToolResult(success=False, error=f"Search root does not exist: {root}")

        matches = []
        q_lower = query.lower()
        try:
            for dirpath, _, filenames in os.walk(root):
                for f in filenames:
                    if q_lower in f.lower() or (q_lower.startswith("*") and f.lower().endswith(q_lower[1:])):
                        full_p = os.path.join(dirpath, f)
                        matches.append(full_p)
                        if len(matches) >= 50:
                            break
                if len(matches) >= 50:
                    break
            return ToolResult(success=True, data=matches, message=f"Found {len(matches)} matching files for '{query}'")
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e}")
