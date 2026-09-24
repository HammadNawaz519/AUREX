"""Speech recognition integration for AUREX using Groq Whisper turbo."""

import io
import logging
from typing import Optional
from app.ai import get_ai_provider

logger = logging.getLogger(__name__)


class SpeechRecognizer:
    def __init__(self):
        pass

    def transcribe(self, audio_bytes: bytes, filename: Optional[str] = None) -> str:
        """
        Transcribe audio bytes (WAV or WebM) using the active AI provider (Groq Whisper-v3-turbo).
        """
        if not audio_bytes or len(audio_bytes) < 400:
            return ""

        # Auto-detect audio container format from header magic bytes
        if filename is None:
            if audio_bytes.startswith(b"\x1a\x45\xdf\xa3") or audio_bytes.startswith(b"\x1aE\xdf\xa3"):
                filename = "audio.webm"
            elif audio_bytes.startswith(b"RIFF"):
                filename = "audio.wav"
            else:
                filename = "audio.wav"

        try:
            provider = get_ai_provider()
            text = provider.transcribe_audio(audio_bytes, filename=filename)
            clean = text.strip()
            logger.info(f"Transcribed voice input ({filename}): '{clean}'")
            return clean
        except Exception as e:
            logger.error(f"Speech transcription failed: {e}")
            return ""


_global_recognizer = SpeechRecognizer()

def get_recognizer() -> SpeechRecognizer:
    return _global_recognizer
