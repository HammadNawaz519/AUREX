"""AUREX Voice System — Voice Activity Detector (VAD).

Provides robust speech boundary detection:
  - Adaptive ambient noise floor tracking
  - Pre-roll ring buffer (ensures first syllables are never truncated)
  - Configurable speech-start trigger and natural silence end-of-speech detection
  - Utterance duration enforcement (min/max duration guardrails)
"""

from __future__ import annotations
import collections
import enum
import logging
import time
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger("AurexVAD")


class VADState(enum.Enum):
    IDLE = "IDLE"
    SPEECH_START = "SPEECH_START"
    SPEECH_CONTINUES = "SPEECH_CONTINUES"
    SPEECH_END = "SPEECH_END"
    MAX_DURATION_REACHED = "MAX_DURATION_REACHED"


class VoiceActivityDetector:
    """Adaptive energy-based Voice Activity Detector with pre-roll history."""

    def __init__(
        self,
        min_speech_frames: int = 2,
        silence_duration: float = 0.45,
        min_utterance_duration: float = 0.3,
        max_utterance_duration: float = 15.0,
        pre_roll_duration: float = 0.3,
        base_threshold: float = 0.015,
        adaptive_multiplier: float = 2.2,
    ):
        self.min_speech_frames = min_speech_frames
        self.silence_duration = silence_duration
        self.min_utterance_duration = min_utterance_duration
        self.max_utterance_duration = max_utterance_duration
        self.pre_roll_duration = pre_roll_duration
        self.base_threshold = base_threshold
        self.adaptive_multiplier = adaptive_multiplier

        # Adaptive noise floor
        self.noise_floor = base_threshold
        self.adaptive_alpha = 0.05  # Slow EMA smoothing

        # Runtime state
        self._state = VADState.IDLE
        self._speech_frames_count = 0
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        self._pre_roll_buffer: collections.deque[Tuple[np.ndarray, np.ndarray]] = collections.deque(maxlen=20)
        self._recorded_float_chunks: list[np.ndarray] = []
        self._recorded_int16_chunks: list[np.ndarray] = []
        self._sample_rate = 16000

    @property
    def state(self) -> VADState:
        return self._state

    @property
    def is_speech_active(self) -> bool:
        return self._state in (VADState.SPEECH_START, VADState.SPEECH_CONTINUES)

    def reset(self):
        """Reset state for a fresh utterance capture."""
        self._state = VADState.IDLE
        self._speech_frames_count = 0
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        self._pre_roll_buffer.clear()
        self._recorded_float_chunks.clear()
        self._recorded_int16_chunks.clear()

    def process_frame(
        self, mono_float: np.ndarray, mono_int16: np.ndarray, sample_rate: int
    ) -> VADState:
        """
        Process a single audio frame and return current VAD transition state.
        
        Args:
            mono_float: normalized float32 array in [-1.0, 1.0]
            mono_int16: 16-bit PCM integer array
            sample_rate: sampling frequency in Hz
        """
        self._sample_rate = sample_rate
        now = time.time()

        if len(mono_float) == 0:
            return self._state

        # Calculate frame RMS energy
        rms = float(np.sqrt(np.mean(mono_float ** 2)))

        # Dynamic threshold based on tracked background noise floor
        active_threshold = max(self.base_threshold, self.noise_floor * self.adaptive_multiplier)
        is_frame_speech = rms >= active_threshold

        if self._state == VADState.IDLE:
            # Maintain pre-roll ring buffer
            # Adjust maxlen to match configured pre_roll_duration
            frame_duration = len(mono_float) / float(sample_rate)
            if frame_duration > 0:
                needed_slots = max(3, int(self.pre_roll_duration / frame_duration))
                if self._pre_roll_buffer.maxlen != needed_slots:
                    self._pre_roll_buffer = collections.deque(
                        list(self._pre_roll_buffer), maxlen=needed_slots
                    )
            self._pre_roll_buffer.append((mono_float.copy(), mono_int16.copy()))

            if is_frame_speech:
                self._speech_frames_count += 1
                if self._speech_frames_count >= self.min_speech_frames:
                    # Speech confirmed! Transition to SPEECH_START
                    self._state = VADState.SPEECH_START
                    self._speech_start_time = now
                    self._last_speech_time = now

                    # Transfer pre-roll audio into recording buffers
                    self._recorded_float_chunks.clear()
                    self._recorded_int16_chunks.clear()
                    for f_chunk, i_chunk in self._pre_roll_buffer:
                        self._recorded_float_chunks.append(f_chunk)
                        self._recorded_int16_chunks.append(i_chunk)
                    self._pre_roll_buffer.clear()

                    logger.debug(
                        f"VAD: SPEECH_START (RMS={rms:.4f} > th={active_threshold:.4f}, noise_floor={self.noise_floor:.4f})"
                    )
                    return VADState.SPEECH_START
            else:
                self._speech_frames_count = 0
                # Adapt background noise floor slowly during silence
                self.noise_floor = (1.0 - self.adaptive_alpha) * self.noise_floor + self.adaptive_alpha * rms
            return VADState.IDLE

        elif self._state in (VADState.SPEECH_START, VADState.SPEECH_CONTINUES):
            # Accumulate audio chunk
            self._recorded_float_chunks.append(mono_float.copy())
            self._recorded_int16_chunks.append(mono_int16.copy())

            utterance_duration = now - self._speech_start_time

            # Check max duration guardrail
            if utterance_duration >= self.max_utterance_duration:
                self._state = VADState.MAX_DURATION_REACHED
                logger.info(f"VAD: Max utterance duration reached ({utterance_duration:.1f}s)")
                return VADState.MAX_DURATION_REACHED

            if is_frame_speech:
                self._last_speech_time = now
                self._state = VADState.SPEECH_CONTINUES
                return VADState.SPEECH_CONTINUES
            else:
                # Silence frame encountered during active speech
                silence_gap = now - self._last_speech_time
                if silence_gap >= self.silence_duration:
                    # Check if utterance satisfies minimum duration
                    if utterance_duration >= self.min_utterance_duration:
                        self._state = VADState.SPEECH_END
                        logger.debug(
                            f"VAD: SPEECH_END detected (duration={utterance_duration:.2f}s, silence={silence_gap:.2f}s)"
                        )
                        return VADState.SPEECH_END
                    else:
                        # Too short (e.g. click or cough), discard and return to IDLE
                        logger.debug(f"VAD: Utterance too short ({utterance_duration:.2f}s), resetting to IDLE")
                        self.reset()
                        return VADState.IDLE
                else:
                    self._state = VADState.SPEECH_CONTINUES
                    return VADState.SPEECH_CONTINUES

        elif self._state in (VADState.SPEECH_END, VADState.MAX_DURATION_REACHED):
            # Utterance finalized, waiting for caller to reset()
            return self._state

        return self._state

    def get_recorded_audio(self) -> Tuple[np.ndarray, np.ndarray, int]:
        """
        Return the captured speech utterance.
        
        Returns:
            (mono_float32, mono_int16, samplerate)
        """
        if not self._recorded_float_chunks:
            return np.empty(0, dtype=np.float32), np.empty(0, dtype=np.int16), self._sample_rate

        full_float = np.concatenate(self._recorded_float_chunks, axis=0)
        full_int16 = np.concatenate(self._recorded_int16_chunks, axis=0)
        return full_float, full_int16, self._sample_rate
