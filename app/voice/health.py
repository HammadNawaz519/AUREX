"""AUREX Voice System — Health Monitor & Diagnostic Status.

Tracks:
  - Microphone connection & streaming liveness
  - Wake engine readiness
  - STT and TTS availability
  - Real-time timestamp telemetry and formatted diagnostic reports
"""

from __future__ import annotations
import logging
import time
from typing import Optional, Dict, Any

from app.voice.voice_state import VoiceState

logger = logging.getLogger("AurexHealth")


class VoiceHealth:
    """Telemetry and diagnostic health monitor for the AUREX voice pipeline."""

    def __init__(self):
        self.microphone_connected: bool = False
        self.microphone_device_name: str = "None"
        self.audio_callback_alive: bool = False
        self.wake_engine_alive: bool = False
        self.tts_available: bool = True
        self.stt_available: bool = True

        self.last_audio_timestamp: float = 0.0
        self.last_wake_timestamp: float = 0.0
        self.last_command_timestamp: float = 0.0
        self.last_error: Optional[str] = None
        self.current_state: VoiceState = VoiceState.STARTING

    def record_audio_frame(self):
        self.last_audio_timestamp = time.time()
        self.audio_callback_alive = True

    def record_wake(self):
        self.last_wake_timestamp = time.time()

    def record_command(self):
        self.last_command_timestamp = time.time()

    def record_error(self, err: str):
        self.last_error = err

    def is_healthy(self) -> bool:
        """Returns True if mic is connected and audio frames arrived in last 3 seconds."""
        now = time.time()
        audio_fresh = (now - self.last_audio_timestamp) < 3.0 if self.last_audio_timestamp > 0 else False
        return self.microphone_connected and audio_fresh

    def get_status_report(self) -> str:
        """Format human-readable diagnostics for UI or terminal display."""
        now = time.time()

        audio_ago = (
            f"{now - self.last_audio_timestamp:.1f}s ago"
            if self.last_audio_timestamp > 0
            else "Never"
        )
        wake_ago = (
            f"{now - self.last_wake_timestamp:.1f}s ago"
            if self.last_wake_timestamp > 0
            else "None"
        )
        cmd_ago = (
            f"{now - self.last_command_timestamp:.1f}s ago"
            if self.last_command_timestamp > 0
            else "None"
        )

        mic_status = "ONLINE" if self.microphone_connected else "OFFLINE"
        stream_status = "ACTIVE" if (now - self.last_audio_timestamp < 3.0 and self.last_audio_timestamp > 0) else "INACTIVE"
        wake_status = "ACTIVE" if self.wake_engine_alive else "INACTIVE"

        return (
            "================ AUREX VOICE STATUS ================\n"
            f"Mode:          {self.current_state.value}\n"
            f"Microphone:    {mic_status} ({self.microphone_device_name})\n"
            f"Audio Stream:  {stream_status} (Last audio: {audio_ago})\n"
            f"Wake Engine:   {wake_status} (Last wake: {wake_ago})\n"
            f"TTS:           {'ONLINE' if self.tts_available else 'OFFLINE'}\n"
            f"STT:           {'ONLINE' if self.stt_available else 'OFFLINE'}\n"
            f"Last Command:  {cmd_ago}\n"
            f"Last Error:    {self.last_error or 'None'}\n"
            "====================================================="
        )


_global_health = VoiceHealth()

def get_voice_health() -> VoiceHealth:
    return _global_health
