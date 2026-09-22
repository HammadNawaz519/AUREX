"""Base Tool framework and Tool Registry for AUREX."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable
import logging
from app.core.permissions import get_permission_manager, ActionLevel, ActionRequest

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    success: bool
    data: Any = None
    message: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "message": self.message,
            "error": self.error
        }


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    is_write: bool = False
    is_shell: bool = False

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        pass

    def get_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class ToolRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolRegistry, cls).__new__(cls)
            cls._instance._tools: Dict[str, BaseTool] = {}
        return cls._instance

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [tool.get_openai_schema() for tool in self._tools.values()]

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool '{name}'")

        # Evaluate permissions
        pm = get_permission_manager()
        targets = []
        for key in ["path", "source", "destination", "file_path", "folder_path"]:
            if key in arguments and arguments[key]:
                targets.append(str(arguments[key]))

        desc = f"Execute tool '{name}' with {arguments}"
        req = pm.evaluate_action(
            action_type=name,
            target_paths=targets,
            description=desc,
            is_write=tool.is_write,
            is_shell=tool.is_shell,
            metadata=arguments
        )

        if not pm.authorize(req):
            if req.level == ActionLevel.BLOCKED:
                return ToolResult(success=False, error=req.reason or "Action was permanently BLOCKED by security policy.")
            return ToolResult(success=False, error="Action was rejected by user or confirmation policy.")

        try:
            return tool.execute(**arguments)
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}", exc_info=True)
            return ToolResult(success=False, error=str(e))


_global_registry = ToolRegistry()

def get_tool_registry() -> ToolRegistry:
    return _global_registry
