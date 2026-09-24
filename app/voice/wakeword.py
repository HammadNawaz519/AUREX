"""
Wake-word and double-clap detection for AUREX.

WakeWordDetector  — text-based wake phrase stripping (used after STT)
AcousticWakeService — continuous microphone listener using OpenWakeWord or
                      Vosk-based keyword spotting (local, zero-cloud).
                      Falls back to threshold-based acoustic detection.
DoubleClapDetector  — detects double-clap gesture from microphone audio energy.
"""
from __future__ import annotations
import re
import time
import logging
import threading
import numpy as np
from typing import Tuple, Optional, Callable
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


# ─── Text-Level Wake Word Check ────────────────────────────────────────────────

class WakeWordDetector:
    """Strip wake phrases from transcribed text."""

    @classmethod
    def check_and_strip(cls, text: str) -> Tuple[bool, str]:
        """
        Returns (has_wake_word, cleaned_text).
        Strips: Hey/Hi/Ok AUREX, AUREX, Rex, Jarvis from start of text.
        """
        settings = get_settings()
        custom = settings.wake_word.lower()
        clean = text.strip()

        # Phonetic variants Whisper often produces for 'AUREX'
        wake_names = rf"{re.escape(custom)}|aurex|orex|aurix|arex|orix|alrex|rex|jarvis|alex"
        patterns = [
            rf"^(?:hey|hi|hello|ok|okay)?\s*(?:{wake_names})[,\.!?;:]*\s*",
            rf"(?:hey|hi|hello|ok|okay)\s+(?:{wake_names})[,\.!?;:]*\s*",
            rf"\b(?:{wake_names})[,\.!?;:]*$",
        ]
        for p in patterns:
            m = re.search(p, clean, re.IGNORECASE)
            if m:
                # Strip matched wake phrase
                stripped = (clean[:m.start()] + " " + clean[m.end():]).strip()
                return True, stripped

        return False, clean


# ─── Acoustic Wake Service ──────────────────────────────────────────────────────

class AcousticWakeService:
    """
    Continuous background listener that fires a callback when:
      - "AUREX" / "Hey AUREX" wake phrase is detected (via OpenWakeWord or VAD+STT)
      - Double-clap gesture is detected
    Runs entirely locally — no cloud audio streaming.
    """

    def __init__(self, on_wake: Callable[[], None]):
        self._on_wake = on_wake
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._backend: str = "none"

        # Double-clap detector
        settings = get_settings()
        self._double_clap_enabled: bool = getattr(settings, "double_clap_enabled", True)
        self._clap_sensitivity: str = getattr(settings, "clap_sensitivity", "medium")
        self._clap_detector = DoubleClapDetector(on_clap=self._handle_wake)
        self._cooldown: float = 2.0
        self._last_wake: float = 0.0

        self._init_backend()

    def _init_backend(self):
        # Try OpenWakeWord (best local wake-word engine)
        try:
            import openwakeword  # type: ignore
            from openwakeword.model import Model  # type: ignore
            self._oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            self._backend = "oww"
            logger.info("AcousticWake: OpenWakeWord backend initialized.")
            return
        except Exception:
            pass

        # Try Vosk keyword spotting
        try:
            import vosk  # type: ignore
            import json
            self._backend = "vosk"
            logger.info("AcousticWake: Vosk keyword backend initialized.")
            return
        except Exception:
            pass

        # Fallback: VAD energy + Whisper STT
        self._backend = "vad_stt"
        logger.info("AcousticWake: VAD+STT fallback wake detection.")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="aurex-wake-listener"
        )
        self._thread.start()
        if self._double_clap_enabled:
            self._clap_detector.start()
        logger.info("AcousticWake: listener started.")

    def stop(self):
        self._running = False
        self._clap_detector.stop()
        logger.info("AcousticWake: listener stopped.")

    def _handle_wake(self):
        now = time.time()
        if now - self._last_wake < self._cooldown:
            return
        self._last_wake = now
        logger.info("AUREX wake event triggered.")
        try:
            self._on_wake()
        except Exception as e:
            logger.error(f"Wake callback error: {e}")

    def _listen_loop(self):
        """Continuously listen for wake word using selected backend."""
        if self._backend == "oww":
            self._oww_loop()
        elif self._backend == "vosk":
            self._vosk_loop()
        else:
            self._vad_stt_loop()

    def _oww_loop(self):
        try:
            import sounddevice as sd
            CHUNK = 1280
            SR = 16000
            buf = np.zeros(CHUNK, dtype=np.int16)

            def callback(indata, frames, time_info, status):
                nonlocal buf
                buf = (indata[:, 0] * 32767).astype(np.int16)

            with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                blocksize=CHUNK, callback=callback):
                while self._running:
                    prediction = self._oww_model.predict(buf)
                    # Check for any activation
                    for model_name, score in prediction.items():
                        if score > 0.5:
                            logger.info(f"OpenWakeWord: '{model_name}' detected (score={score:.2f})")
                            self._handle_wake()
                            time.sleep(self._cooldown)
                    time.sleep(0.05)
        except Exception as e:
            logger.warning(f"OWW loop error: {e}; falling back to VAD+STT")
            self._backend = "vad_stt"
            self._vad_stt_loop()

    def _vosk_loop(self):
        try:
            import vosk  # type: ignore
            import sounddevice as sd
            import json
            SR = 16000
            model = vosk.Model(lang="en-us")
            rec = vosk.KaldiRecognizer(model, SR)
            rec.SetWords(True)

            WAKE_WORDS = {"aurex", "hey aurex", "jarvis"}

            def callback(indata, frames, time_info, status):
                data = (indata[:, 0] * 32767).astype(np.int16).tobytes()
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").lower()
                    if any(w in text for w in WAKE_WORDS):
                        self._handle_wake()

            with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                blocksize=4000, callback=callback):
                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            logger.warning(f"Vosk loop error: {e}")
            self._backend = "vad_stt"
            self._vad_stt_loop()

    def _vad_stt_loop(self):
        """
        VAD energy gate → short Whisper STT → check for wake word.
        Only transcribes when speech energy detected above threshold.
        Keeps cloud calls to zero by using local Whisper (if available).
        """
        try:
            import sounddevice as sd
            SR = 16000
            CHUNK = 1024
            SILENCE_THRESH = 0.008   # RMS threshold for speech
            SPEECH_FRAMES = 20       # frames before transcribing
            MAX_RECORD = 60          # max speech frames to capture

            speech_buf = []
            is_speech = False
            silent_frames = 0
            SILENCE_MAX = 25         # frames of silence before sending to STT

            def callback(indata, frames, time_info, status):
                nonlocal is_speech, silent_frames, speech_buf
                rms = float(np.sqrt(np.mean(indata ** 2)))

                if rms > SILENCE_THRESH:
                    silent_frames = 0
                    if not is_speech and len(speech_buf) == 0:
                        is_speech = True
                    speech_buf.append(indata.copy())
                else:
                    if is_speech:
                        silent_frames += 1
                        speech_buf.append(indata.copy())

            with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                blocksize=CHUNK, callback=callback):
                while self._running:
                    time.sleep(0.1)

                    if is_speech and silent_frames >= SILENCE_MAX:
                        # Transcribe buffered audio
                        captured = speech_buf[:MAX_RECORD]
                        speech_buf = []
                        is_speech = False
                        silent_frames = 0

                        if len(captured) > SPEECH_FRAMES:
                            audio_data = np.concatenate(captured, axis=0).flatten()
                            text = self._local_transcribe(audio_data, SR)
                            if text:
                                has_wake, _ = WakeWordDetector.check_and_strip(text)
                                if has_wake:
                                    self._handle_wake()

        except Exception as e:
            logger.warning(f"VAD+STT wake loop error: {e}")

    def _local_transcribe(self, audio: np.ndarray, sr: int) -> str:
        """Attempt local Whisper transcription of captured audio."""
        try:
            import whisper  # type: ignore
            model = getattr(self, "_whisper_model", None)
            if model is None:
                model = whisper.load_model("tiny.en")
                self._whisper_model = model
            result = model.transcribe(audio.astype(np.float32), fp16=False)
            return result.get("text", "").strip()
        except Exception:
            return ""


# ─── Double-Clap Detector ──────────────────────────────────────────────────────

class DoubleClapDetector:
    """
    Detects the CLAP → pause → CLAP pattern from microphone audio.
    Uses energy spike detection — no cloud, no model needed.
    """

    SENSITIVITY_MAP = {
        "low": 0.25,
        "medium": 0.15,
        "high": 0.08,
    }

    def __init__(self, on_clap: Callable[[], None],
                 sensitivity: str = "medium",
                 cooldown: float = 2.0):
        self._on_clap = on_clap
        self._threshold = self.SENSITIVITY_MAP.get(sensitivity, 0.15)
        self._cooldown = cooldown
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_trigger: float = 0.0

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="aurex-clap-detector"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        try:
            import sounddevice as sd
            SR = 16000
            CHUNK = 512
            WIN = 3        # frames per window
            GAP_MIN = 0.1  # seconds min between claps
            GAP_MAX = 0.8  # seconds max between claps

            clap_times = []
            window_rms = []

            def callback(indata, frames, time_info, status):
                rms = float(np.sqrt(np.mean(indata ** 2)))
                window_rms.append(rms)
                if len(window_rms) > WIN:
                    window_rms.pop(0)

                avg = np.mean(window_rms) if window_rms else 0.0
                if avg > self._threshold:
                    now = time.time()
                    if not clap_times or (now - clap_times[-1]) > GAP_MIN:
                        clap_times.append(now)
                        # Check for double clap
                        if len(clap_times) >= 2:
                            gap = clap_times[-1] - clap_times[-2]
                            if GAP_MIN < gap < GAP_MAX:
                                trigger_now = time.time()
                                if trigger_now - self._last_trigger > self._cooldown:
                                    self._last_trigger = trigger_now
                                    clap_times.clear()
                                    logger.info("Double-clap wake gesture detected.")
                                    threading.Thread(
                                        target=self._on_clap, daemon=True
                                    ).start()

                    # Prune old clap times
                    cutoff = time.time() - 2.0
                    while clap_times and clap_times[0] < cutoff:
                        clap_times.pop(0)

            with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                blocksize=CHUNK, callback=callback):
                while self._running:
                    time.sleep(0.05)
        except Exception as e:
            logger.debug(f"Clap detector error: {e}")


# ─── Global instance ────────────────────────────────────────────────────────────

_acoustic_service: Optional[AcousticWakeService] = None

def get_acoustic_wake_service(on_wake: Callable[[], None]) -> AcousticWakeService:
    global _acoustic_service
    if _acoustic_service is None:
        _acoustic_service = AcousticWakeService(on_wake=on_wake)
    return _acoustic_service
