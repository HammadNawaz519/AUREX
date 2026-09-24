"""AUREX Voice System — Formal Voice State Machine.

Explicit states and logged transitions:
  PASSIVE -> WAKING -> ACTIVATING -> LISTENING -> RECORDING ->
  TRANSCRIBING -> THINKING -> EXECUTING -> SPEAKING -> LISTENING
"""

import logging
import threading
from enum import Enum
from typing import Callable, List, Optional

logger = logging.getLogger("AurexVoiceState")


class VoiceState(Enum):
    STARTING      = "STARTING"
    PASSIVE       = "PASSIVE"         # Mode A: Passive wake-word listening
    WAKING        = "WAKING"          # Wake word or double clap detected
    ACTIVATING    = "ACTIVATING"      # Switching to active mode, UI coming front
    LISTENING     = "LISTENING"       # Mode B: Active conversation, standing by for user speech
    RECORDING     = "RECORDING"       # User is speaking, VAD buffering utterance
    TRANSCRIBING  = "TRANSCRIBING"    # Speech finalized, converting audio to text
    THINKING      = "THINKING"        # Intent routing and cognitive processing
    EXECUTING     = "EXECUTING"       # Tool / Computer-use action running
    SPEAKING      = "SPEAKING"        # Vocalizing response via TTS
    INTERRUPTING  = "INTERRUPTING"    # User said "STOP", cutting off TTS & actions
    ERROR         = "ERROR"           # Subsystem error (e.g. microphone offline)
    STOPPING      = "STOPPING"        # Graceful shutdown


class VoiceStateMachine:
    """Thread-safe state machine tracking AUREX voice lifecycle."""

    def __init__(self, initial_state: VoiceState = VoiceState.STARTING):
        self._state = initial_state
        self._lock = threading.Lock()
        self._listeners: List[Callable[[VoiceState, VoiceState, str], None]] = []

    @property
    def current_state(self) -> VoiceState:
        with self._lock:
            return self._state

    @property
    def state(self) -> VoiceState:
        return self.current_state

    def add_listener(self, callback: Callable[[VoiceState, VoiceState, str], None]):
        """Subscribe to state transitions: callback(old_state, new_state, description)."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[VoiceState, VoiceState, str], None]):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def transition_to(self, new_state: VoiceState, reason: str = "") -> bool:
        """Execute state transition with debug logging and callback dispatch."""
        with self._lock:
            old_state = self._state
            if old_state == new_state and new_state not in (VoiceState.RECORDING, VoiceState.LISTENING):
                return False

            self._state = new_state
            listeners = list(self._listeners)

        desc = f" ({reason})" if reason else ""
        logger.info(f"[VOICE] {old_state.value} -> {new_state.value}{desc}")

        for cb in listeners:
            try:
                cb(old_state, new_state, reason)
            except Exception as e:
                logger.error(f"Error in voice state listener callback: {e}")

        return True

    def __repr__(self) -> str:
        return f"<VoiceStateMachine state={self._state.value}>"
