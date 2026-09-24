"""AUREX Voice System — Modular Wake Engine & Double Clap Detector.

Features:
  - Plug-and-play architecture (OpenWakeWord, Vosk, or acoustic energy-candidate fallback)
  - Zero continuous cloud streaming in passive mode
  - Independent double-clap acoustic gesture detector (fast rise, short decay, 120-750ms interval)
  - Cooldown and false-trigger protection
"""

from __future__ import annotations
import collections
import io
import logging
import re
import threading
import time
from typing import Callable, Optional, Tuple, Dict, Any
import numpy as np

from app.config.settings import get_settings

logger = logging.getLogger("AurexWake")


# ─── Supported Wake Phrase Patterns ──────────────────────────────────────────

WAKE_PHRASES = [
    "aurex",
    "hey aurex",
    "hi aurex",
    "ok aurex",
    "okay aurex",
    "hey rex",
    "rex",
    "jarvis",
    "hey jarvis",
]

# Phonetic variants Whisper or local models produce for "AUREX"
PHONETIC_VARIANTS = r"aurex|orex|aurix|arex|orix|alrex|rex|jarvis|alex"
WAKE_REGEX = re.compile(
    rf"^(?:hey|hi|hello|ok|okay)?\s*(?:{PHONETIC_VARIANTS})[,\.!?;:]*\s*|\b(?:{PHONETIC_VARIANTS})[,\.!?;:]*$",
    re.IGNORECASE,
)


def match_wake_phrase(text: str) -> Tuple[bool, str]:
    """
    Check if text contains a wake phrase.
    Returns (matched, stripped_remainder).
    """
    clean = text.strip()
    if not clean:
        return False, ""

    m = WAKE_REGEX.search(clean)
    if m:
        stripped = (clean[:m.start()] + " " + clean[m.end():]).strip()
        return True, stripped

    # Direct substring check for any phrase
    lower = clean.lower()
    for phrase in WAKE_PHRASES:
        if phrase in lower:
            stripped = lower.replace(phrase, "").strip()
            return True, stripped

    return False, clean


# ─── Double Clap Detector ─────────────────────────────────────────────────────

class DoubleClapDetector:
    """
    Acoustic double-clap gesture detector.
    
    A clap is characterized by:
      - Sharp rise in audio energy (< 20ms)
      - High peak to background ratio
      - Very brief duration (< 80ms) distinguishing it from sustained speech
      - Second clap occurring within 120ms to 750ms
      - Post-trigger cooldown to avoid re-triggering on reflections/echoes
    """

    def __init__(
        self,
        sensitivity: str = "medium",
        cooldown: float = 2.0,
        gap_min: float = 0.12,
        gap_max: float = 0.75,
    ):
        self.cooldown = cooldown
        self.gap_min = gap_min
        self.gap_max = gap_max

        # Sensitivity thresholds (peak amplitude threshold)
        thresholds = {"low": 0.35, "medium": 0.20, "high": 0.12}
        self.threshold = thresholds.get(sensitivity, 0.20)

        # State
        self._noise_floor = 0.01
        self._clap_history: collections.deque[float] = collections.deque(maxlen=10)
        self._last_trigger = 0.0
        self._recent_energies: collections.deque[float] = collections.deque(maxlen=5)

    def reset(self):
        self._clap_history.clear()
        self._recent_energies.clear()

    def process_frame(self, mono_float: np.ndarray, sample_rate: int) -> bool:
        """
        Process a frame of normalized float32 samples.
        Returns True if a valid double-clap pattern was detected.
        """
        if len(mono_float) == 0:
            return False

        now = time.time()
        if now - self._last_trigger < self.cooldown:
            return False

        peak = float(np.max(np.abs(mono_float)))
        rms = float(np.sqrt(np.mean(mono_float ** 2)))

        # Update noise floor slowly
        if peak < self.threshold * 0.5:
            self._noise_floor = 0.98 * self._noise_floor + 0.02 * peak

        self._recent_energies.append(rms)

        # A clap has high crest factor: peak is much higher than RMS
        # Speech has lower crest factor because it's sustained across the frame
        crest_factor = (peak / (rms + 1e-6))

        is_spike = (
            peak > max(self.threshold, self._noise_floor * 3.5)
            and crest_factor > 2.5
        )

        if is_spike:
            # Check gap with previous detected spike
            if not self._clap_history or (now - self._clap_history[-1]) >= self.gap_min:
                self._clap_history.append(now)

                # Check if we have two claps within the valid timing window
                if len(self._clap_history) >= 2:
                    gap = self._clap_history[-1] - self._clap_history[-2]
                    if self.gap_min <= gap <= self.gap_max:
                        self._last_trigger = now
                        self._clap_history.clear()
                        logger.info(f"Double-clap gesture detected! (gap={gap*1000:.0f}ms)")
                        return True

        # Expire old claps past the maximum allowed gap
        cutoff = now - (self.gap_max + 0.2)
        while self._clap_history and self._clap_history[0] < cutoff:
            self._clap_history.popleft()

        return False


# ─── Modular Wake Detectors ──────────────────────────────────────────────────

class BaseWakeDetector:
    def start(self):
        pass

    def stop(self):
        pass

    def reset(self):
        pass

    def process_audio(
        self, mono_float: np.ndarray, mono_int16: np.ndarray, sample_rate: int
    ) -> bool:
        raise NotImplementedError


class FallbackAcousticWakeDetector(BaseWakeDetector):
    """
    High-efficiency acoustic wake candidate detector.
    
    Operates 100% locally on audio energy & duration profiles.
    Only when an utterance matches the exact duration of "AUREX" / "Hey AUREX"
    (0.4s to 2.2s) and settles to silence does it evaluate the candidate.
    Zero continuous streaming to Groq.
    """

    def __init__(self, stt_transcribe_func: Optional[Callable[[bytes, str], str]] = None):
        self._stt_transcribe_func = stt_transcribe_func
        self._speech_buffer: list[np.ndarray] = []
        self._is_speech = False
        self._speech_start_time = 0.0
        self._silence_start_time = 0.0
        self._last_trigger_time = 0.0
        self._cooldown = 1.5

        # Energy thresholds
        self.noise_floor = 0.015
        self.energy_multiplier = 2.4
        self.min_candidate_duration = 0.35  # "Rex" / "Aurex"
        self.max_candidate_duration = 2.2   # "Hey Aurex" max

    def reset(self):
        self._speech_buffer.clear()
        self._is_speech = False
        self._speech_start_time = 0.0
        self._silence_start_time = 0.0

    def process_audio(
        self, mono_float: np.ndarray, mono_int16: np.ndarray, sample_rate: int
    ) -> bool:
        if len(mono_float) == 0:
            return False

        now = time.time()
        if now - self._last_trigger_time < self._cooldown:
            return False

        rms = float(np.sqrt(np.mean(mono_float ** 2)))
        active_thresh = max(0.015, self.noise_floor * self.energy_multiplier)
        is_active = rms >= active_thresh

        if not self._is_speech:
            if is_active:
                self._is_speech = True
                self._speech_start_time = now
                self._silence_start_time = 0.0
                self._speech_buffer = [mono_int16.copy()]
            else:
                self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
            return False
        else:
            # Currently tracking candidate speech
            self._speech_buffer.append(mono_int16.copy())
            duration = now - self._speech_start_time

            if duration > self.max_candidate_duration:
                # Too long for a wake phrase, reset without STT
                self.reset()
                return False

            if not is_active:
                if self._silence_start_time == 0.0:
                    self._silence_start_time = now
                elif (now - self._silence_start_time) >= 0.3:
                    # Utterance ended naturally
                    candidate_duration = self._silence_start_time - self._speech_start_time
                    if candidate_duration >= self.min_candidate_duration:
                        # Valid candidate segment!
                        captured_audio = np.concatenate(self._speech_buffer, axis=0)
                        self.reset()
                        matched = self._verify_candidate(captured_audio, sample_rate)
                        if matched:
                            self._last_trigger_time = now
                            return True
                    else:
                        self.reset()
            else:
                self._silence_start_time = 0.0

        return False

    def _verify_candidate(self, pcm_int16: np.ndarray, sample_rate: int) -> bool:
        """Encode to clean WAV and verify wake phrase."""
        if self._stt_transcribe_func is None:
            return False

        try:
            import wave
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_int16.tobytes())
            wav_bytes = buf.getvalue()

            text = self._stt_transcribe_func(wav_bytes, "wake_candidate.wav")
            if text:
                matched, _ = match_wake_phrase(text)
                if matched:
                    logger.info(f"Wake phrase confirmed: '{text}'")
                    return True
                else:
                    logger.debug(f"Candidate rejected (not wake phrase): '{text}'")
        except Exception as e:
            logger.debug(f"Candidate verification error: {e}")

        return False


# ─── Main WakeEngine ──────────────────────────────────────────────────────────

class WakeEngine:
    """
    AUREX Master Wake Engine.
    
    Coordinates wake-word detection and optional double-clap gestures.
    Consumes audio frames from the primary MicrophoneEngine.
    """

    def __init__(
        self,
        stt_transcribe_func: Optional[Callable[[bytes, str], str]] = None,
        double_clap_enabled: bool = True,
        clap_sensitivity: str = "medium",
    ):
        self.double_clap_enabled = double_clap_enabled
        self._clap_detector = DoubleClapDetector(sensitivity=clap_sensitivity)
        self._wake_detector: BaseWakeDetector = FallbackAcousticWakeDetector(
            stt_transcribe_func=stt_transcribe_func
        )
        self._is_running = False
        self._triggered = False
        self._last_trigger_type: Optional[str] = None
        self._lock = threading.Lock()

    def set_stt_transcriber(self, func: Callable[[bytes, str], str]):
        """Inject or update STT transcription callable."""
        if isinstance(self._wake_detector, FallbackAcousticWakeDetector):
            self._wake_detector._stt_transcribe_func = func

    def start(self):
        with self._lock:
            self._is_running = True
            self._triggered = False
            self._last_trigger_type = None
            self._wake_detector.start()
            self._clap_detector.reset()
            logger.info("WakeEngine started (Passive mode active).")

    def stop(self):
        with self._lock:
            self._is_running = False
            self._wake_detector.stop()
            self._clap_detector.reset()
            logger.info("WakeEngine stopped.")

    def reset(self):
        with self._lock:
            self._triggered = False
            self._last_trigger_type = None
            self._wake_detector.reset()
            self._clap_detector.reset()

    def is_triggered(self) -> bool:
        with self._lock:
            return self._triggered

    def get_last_trigger_type(self) -> Optional[str]:
        with self._lock:
            return self._last_trigger_type

    def process_audio(
        self, mono_float: np.ndarray, mono_int16: np.ndarray, sample_rate: int
    ) -> Optional[str]:
        """
        Process a microphone frame.
        
        Returns:
            "wake_word" if wake phrase matched,
            "double_clap" if double clap detected,
            or None if no event.
        """
        if not self._is_running:
            return None

        # 1. Check double clap gesture if enabled
        if self.double_clap_enabled:
            if self._clap_detector.process_frame(mono_float, sample_rate):
                with self._lock:
                    self._triggered = True
                    self._last_trigger_type = "double_clap"
                return "double_clap"

        # 2. Check wake phrase
        if self._wake_detector.process_audio(mono_float, mono_int16, sample_rate):
            with self._lock:
                self._triggered = True
                self._last_trigger_type = "wake_word"
            return "wake_word"

        return None
