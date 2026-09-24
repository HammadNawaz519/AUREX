"""AUREX Voice System — STT Engine.

Provides speech-to-text with:
  - Provider abstraction (Groq Whisper turbo primary, Local Whisper fallback)
  - Automatic container validation (WAV / WebM) based on magic bytes
  - PCM array to validated WAV serialization
  - High-precision latency measurement and structured diagnostic logging
"""

from __future__ import annotations
import io
import logging
import time
import wave
from typing import Optional, Tuple
import numpy as np

from app.ai import get_ai_provider

logger = logging.getLogger("AurexSTT")


class BaseSTTProvider:
    """Abstract STT provider interface."""

    def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        raise NotImplementedError


class GroqSTT(BaseSTTProvider):
    """Groq Whisper API provider (whisper-large-v3-turbo)."""

    def __init__(self):
        self.provider_name = "Groq Whisper (whisper-large-v3-turbo)"

    def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        provider = get_ai_provider()
        return provider.transcribe_audio(audio_bytes, filename=filename)


class LocalSTT(BaseSTTProvider):
    """Local offline Whisper provider (if openai-whisper or faster-whisper is installed)."""

    def __init__(self, model_name: str = "tiny.en"):
        self.provider_name = f"Local Whisper ({model_name})"
        self.model_name = model_name
        self._model = None

    def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        try:
            import whisper  # type: ignore
            if self._model is None:
                self._model = whisper.load_model(self.model_name)
            
            # Read audio data from bytes
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                sr = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
                audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

            result = self._model.transcribe(audio_np, fp16=False)
            return result.get("text", "").strip()
        except Exception as e:
            logger.debug(f"Local STT failed: {e}")
            return ""


class STTEngine:
    """Master STT controller handling audio validation, container inspection, and fallback."""

    def __init__(self, primary: Optional[BaseSTTProvider] = None, fallback: Optional[BaseSTTProvider] = None):
        self.primary = primary or GroqSTT()
        self.fallback = fallback or LocalSTT()

    @staticmethod
    def detect_container(audio_bytes: bytes) -> Tuple[str, str]:
        """
        Inspect header magic bytes.
        Returns (filename, mime_type).
        """
        if audio_bytes.startswith(b"\x1a\x45\xdf\xa3") or audio_bytes.startswith(b"\x1aE\xdf\xa3"):
            return "audio.webm", "audio/webm"
        elif audio_bytes.startswith(b"RIFF") and len(audio_bytes) > 12 and audio_bytes[8:12] == b"WAVE":
            return "audio.wav", "audio/wav"
        elif audio_bytes.startswith(b"ID3") or audio_bytes.startswith(b"\xff\xfb"):
            return "audio.mp3", "audio/mpeg"
        elif audio_bytes.startswith(b"OggS"):
            return "audio.ogg", "audio/ogg"
        # Default to wav
        return "audio.wav", "audio/wav"

    @staticmethod
    def pcm_to_wav(pcm_int16: np.ndarray, sample_rate: int) -> bytes:
        """Serialize 16-bit PCM integer samples to valid standard WAV bytes."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_int16.tobytes())
        return buf.getvalue()

    def transcribe(self, audio_bytes: bytes, filename: Optional[str] = None) -> str:
        """
        Transcribe raw audio bytes with automatic container detection and metrics logging.
        """
        if not audio_bytes or len(audio_bytes) < 300:
            logger.warning("[STT] Audio buffer too small for transcription.")
            return ""

        auto_filename, mime = self.detect_container(audio_bytes)
        effective_filename = filename or auto_filename

        # Estimate duration if WAV
        duration_sec = 0.0
        if audio_bytes.startswith(b"RIFF"):
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration_sec = frames / float(rate) if rate > 0 else 0.0
            except Exception:
                pass

        start_time = time.perf_counter()
        provider_used = "Groq Whisper"
        transcription = ""

        try:
            transcription = self.primary.transcribe(audio_bytes, effective_filename)
        except Exception as e:
            logger.warning(f"[STT] Primary provider failed: {e}. Attempting fallback...")
            try:
                provider_used = "Fallback Local"
                transcription = self.fallback.transcribe(audio_bytes, effective_filename)
            except Exception as e_fb:
                logger.error(f"[STT] Fallback provider also failed: {e_fb}")

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Structured diagnostics log
        logger.info(
            f"[STT]\n"
            f"  Audio duration: {duration_sec:.2f}s ({len(audio_bytes)} bytes)\n"
            f"  Container:      {effective_filename} ({mime})\n"
            f"  Provider:       {provider_used}\n"
            f"  Transcription:  '{transcription.strip()}'\n"
            f"  Latency:        {latency_ms:.1f}ms"
        )

        return transcription.strip()

    def transcribe_pcm(self, pcm_int16: np.ndarray, sample_rate: int) -> str:
        """Convenience method to transcribe int16 numpy array directly."""
        if len(pcm_int16) == 0:
            return ""
        wav_bytes = self.pcm_to_wav(pcm_int16, sample_rate)
        return self.transcribe(wav_bytes, "utterance.wav")


_global_stt = STTEngine()

def get_stt() -> STTEngine:
    return _global_stt
