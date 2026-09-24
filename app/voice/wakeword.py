"""AUREX Voice System — Wake Word adapter delegating to modular WakeEngine."""

from __future__ import annotations
from typing import Tuple, Callable, Optional
from app.voice.wake_engine import match_wake_phrase, WakeEngine, DoubleClapDetector


class WakeWordDetector:
    """Compatibility wrapper around match_wake_phrase."""

    @classmethod
    def check_and_strip(cls, text: str) -> Tuple[bool, str]:
        return match_wake_phrase(text)


class AcousticWakeService:
    """Compatibility wrapper around the unified WakeEngine."""

    def __init__(self, on_wake: Callable[[], None]):
        self._on_wake = on_wake
        self._engine: Optional[WakeEngine] = None

    def start(self):
        from app.voice.conversation import get_conversation_manager
        cm = get_conversation_manager()
        cm.on("wake_detected", lambda trigger: self._on_wake())
        cm.start()

    def stop(self):
        from app.voice.conversation import get_conversation_manager
        get_conversation_manager().stop()


_global_acoustic_service: Optional[AcousticWakeService] = None

def get_acoustic_wake_service(on_wake: Callable[[], None]) -> AcousticWakeService:
    global _global_acoustic_service
    if _global_acoustic_service is None:
        _global_acoustic_service = AcousticWakeService(on_wake=on_wake)
    return _global_acoustic_service
