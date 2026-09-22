"""Speech recognition integration for AUREX using Groq Whisper turbo."""

import io
import logging
from typing import Optional
from app.ai import get_ai_provider

logger = logging.getLogger(__name__)


class SpeechRecognizer:
    def __init__(self):
        pass

    def transcribe(self, wav_bytes: bytes) -> str:
        """
        Transcribe WAV audio bytes to text using the active AI provider (Groq Whisper-v3-turbo).
        """
        if not wav_bytes or len(wav_bytes) < 1000:
            return ""

        try:
            provider = get_ai_provider()
            text = provider.transcribe_audio(wav_bytes, filename="audio.wav")
            clean = text.strip()
            logger.info(f"Transcribed voice input: '{clean}'")
            return clean
        except Exception as e:
            logger.error(f"Speech transcription failed: {e}")
            return ""


_global_recognizer = SpeechRecognizer()

def get_recognizer() -> SpeechRecognizer:
    return _global_recognizer
