"""AUREX Push-To-Talk Voice System — Fast Speech-To-Text.

Uses Groq Whisper (whisper-large-v3-turbo) for ultra-fast, accurate transcription.
Zero background polling.
"""

from __future__ import annotations
import io
import logging
import re
import time
from typing import Optional, Tuple

from app.ai import get_ai_provider

logger = logging.getLogger("AurexSpeech")

WAKE_PREFIX_PATTERN = re.compile(
    r"^(?:hey|hi|hello|ok|okay)?\s*(?:aurex|orex|aurix|arex|orix|alrex|rex|jarvis|alex)[,\.!?;:]*\s*",
    re.IGNORECASE,
)


def clean_wake_phrase(text: str) -> Tuple[bool, str]:
    """Strip any accidental wake prefix if user says 'Hey AUREX open Chrome'."""
    clean = text.strip()
    if not clean:
        return False, ""
    m = WAKE_PREFIX_PATTERN.match(clean)
    if m:
        stripped = clean[m.end():].strip()
        return True, stripped
    return False, clean


class SpeechToText:
    """Fast speech-to-text converter using Groq Whisper turbo."""

    def __init__(self):
        pass

    def transcribe(self, audio_bytes: bytes, filename: Optional[str] = None) -> str:
        """Transcribe audio bytes (WAV or WebM)."""
        if not audio_bytes or len(audio_bytes) < 300:
            return ""

        # Container detection from magic bytes
        if filename is None:
            if audio_bytes.startswith(b"\x1a\x45\xdf\xa3") or audio_bytes.startswith(b"\x1aE\xdf\xa3"):
                filename = "audio.webm"
            else:
                filename = "audio.wav"

        logger.info("[STT] Transcribing...")
        start_t = time.perf_counter()

        try:
            provider = get_ai_provider()
            text = provider.transcribe_audio(audio_bytes, filename=filename)
            latency_ms = (time.perf_counter() - start_t) * 1000.0
            clean = text.strip()
            logger.info(f'[STT] "{clean}" ({latency_ms:.0f}ms)')
            return clean
        except Exception as e:
            logger.error(f"[STT] Transcription error: {e}")
            return ""


# Backward-compatible classes and functions
class WakeWordDetector:
    @classmethod
    def check_and_strip(cls, text: str) -> Tuple[bool, str]:
        return clean_wake_phrase(text)


SpeechRecognizer = SpeechToText

_global_stt = SpeechToText()

def get_recognizer() -> SpeechToText:
    return _global_stt

def get_stt() -> SpeechToText:
    return _global_stt
