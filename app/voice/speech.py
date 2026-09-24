"""AUREX Voice System — Speech Recognition adapter delegating to STTEngine."""

from __future__ import annotations
from typing import Optional
from app.voice.stt import get_stt, STTEngine


class SpeechRecognizer:
    def __init__(self):
        self._engine = get_stt()

    def transcribe(self, audio_bytes: bytes, filename: Optional[str] = None) -> str:
        return self._engine.transcribe(audio_bytes, filename=filename)


_global_recognizer = SpeechRecognizer()

def get_recognizer() -> SpeechRecognizer:
    return _global_recognizer
