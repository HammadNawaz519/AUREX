"""Tools initialization and automatic registration for AUREX."""

from app.tools.base import BaseTool, ToolResult, ToolRegistry, get_tool_registry
from app.tools.filesystem import (
    ReadFileTool,
    WriteFileTool,
    CreateFolderTool,
    MoveFileTool,
    CopyFileTool,
    DeleteFileTool,
    RenameFileTool,
    ListDirectoryTool,
    SearchFilesTool,
)
from app.tools.applications import OpenApplicationTool, CloseApplicationTool
from app.tools.system import GetSystemInfoTool, ListProcessesTool
from app.tools.browser import OpenUrlTool, SearchWebTool
from app.tools.terminal import ExecuteCommandTool
from app.tools.screenshots import TakeScreenshotTool
from app.tools.windows import ListWindowsTool, FocusWindowTool
from app.tools.clipboard import GetClipboardTool, SetClipboardTool


def register_default_tools():
    reg = get_tool_registry()
    tools = [
        ReadFileTool(),
        WriteFileTool(),
        CreateFolderTool(),
        MoveFileTool(),
        CopyFileTool(),
        DeleteFileTool(),
        RenameFileTool(),
        ListDirectoryTool(),
        SearchFilesTool(),
        OpenApplicationTool(),
        CloseApplicationTool(),
        GetSystemInfoTool(),
        ListProcessesTool(),
        OpenUrlTool(),
        SearchWebTool(),
        ExecuteCommandTool(),
        TakeScreenshotTool(),
        ListWindowsTool(),
        FocusWindowTool(),
        GetClipboardTool(),
        SetClipboardTool()
    ]
    for t in tools:
        reg.register(t)


# Register all tools immediately upon import
register_default_tools()

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "get_tool_registry",
    "register_default_tools"
]
