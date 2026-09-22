"""Event bus and state notification dispatch for AUREX."""

from enum import Enum
from typing import Callable, Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class EventBus:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EventBus, cls).__new__(cls)
            cls._instance._listeners: Dict[str, List[Callable]] = {}
            cls._instance._current_state = AgentState.IDLE
        return cls._instance

    @property
    def current_state(self) -> AgentState:
        return self._current_state

    def subscribe(self, event_name: str, callback: Callable):
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        if callback not in self._listeners[event_name]:
            self._listeners[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable):
        if event_name in self._listeners and callback in self._listeners[event_name]:
            self._listeners[event_name].remove(callback)

    def publish(self, event_name: str, **kwargs):
        if event_name == "state_changed" and "state" in kwargs:
            self._current_state = kwargs["state"]

        callbacks = list(self._listeners.get(event_name, []))
        for cb in callbacks:
            try:
                cb(**kwargs)
            except Exception as e:
                logger.error(f"Error executing callback for event '{event_name}': {e}")


def get_event_bus() -> EventBus:
    return EventBus()
