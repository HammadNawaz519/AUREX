"""AUREX Voice System — Lightweight Double-Clap Detector.

Zero speech recognition. Zero Whisper. Zero cloud streaming.
Runs a lightweight local peak/transient detector on audio blocks to identify
two distinct, sharp acoustic claps within a short interval (0.15s - 0.85s).
"""

from __future__ import annotations
import logging
import threading
import time
from typing import Callable, Optional
import numpy as np
import sounddevice as sd

logger = logging.getLogger("AurexClapDetector")


class DoubleClapDetector:
    """Non-blocking, low-CPU double-clap transient detector."""

    def __init__(
        self,
        on_double_clap: Optional[Callable[[], None]] = None,
        samplerate: int = 16000,
        threshold: float = 0.28,
        min_gap: float = 0.15,
        max_gap: float = 0.85,
        cooldown: float = 2.5,
    ):
        self.on_double_clap = on_double_clap
        self.samplerate = samplerate
        self.threshold = threshold
        self.min_gap = min_gap
        self.max_gap = max_gap
        self.cooldown = cooldown

        self._running = False
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

        # Detection state
        self._last_clap_time: float = 0.0
        self._disarmed_until: float = 0.0
        self._noise_floor: float = 0.02
        self._last_energy: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Start background microphone stream for double-clap detection."""
        with self._lock:
            if self._running:
                return True

            self._last_clap_time = 0.0
            self._disarmed_until = 0.0
            block_size = int(self.samplerate * 0.03)  # 30ms blocks for fast transient detection

            def callback(indata, frames, time_info, status):
                if not self._running:
                    return
                self._process_block(indata)

            try:
                self._stream = sd.InputStream(
                    samplerate=self.samplerate,
                    channels=1,
                    dtype="float32",
                    callback=callback,
                    blocksize=block_size,
                )
                self._stream.start()
                self._running = True
                logger.info("[CLAP] Double-clap listener online.")
                return True
            except Exception as e:
                logger.warning(f"[CLAP] Failed to start clap detector stream: {e}")
                self._running = False
                return False

    def stop(self):
        """Stop background clap detection stream."""
        with self._lock:
            self._running = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            logger.info("[CLAP] Double-clap listener stopped.")

    def _process_block(self, indata: np.ndarray):
        """Analyze 30ms audio block for sharp transient peak."""
        now = time.time()
        if now < self._disarmed_until:
            return

        # Peak amplitude and RMS in this block
        samples = indata.flatten()
        peak = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(samples ** 2)))

        # Update dynamic background noise floor (slow moving average)
        self._noise_floor = 0.95 * self._noise_floor + 0.05 * min(rms, 0.05)

        # Clap signature:
        # 1. Peak exceeds absolute threshold
        # 2. Crest factor (peak / rms) is high (sharp transient, not a hum or sustained speech vowel)
        # 3. Peak is at least 3.5x higher than ambient noise floor
        # 4. Energy jumped sharply compared to previous block
        is_transient = (
            peak >= self.threshold
            and peak > (self._noise_floor * 3.5)
            and (rms > 0.001 and (peak / rms) >= 2.2)
            and (peak > self._last_energy * 2.0)
        )
        self._last_energy = peak

        if is_transient:
            self._handle_clap_event(now)

    def _handle_clap_event(self, now: float):
        """State machine for evaluating clap cadence."""
        dt = now - self._last_clap_time

        if self._last_clap_time > 0 and self.min_gap <= dt <= self.max_gap:
            # Valid second clap!
            logger.info(f"[CLAP] Double clap detected! (interval: {dt:.2f}s)")
            self._disarmed_until = now + self.cooldown
            self._last_clap_time = 0.0

            if self.on_double_clap:
                try:
                    # Fire callback on separate thread so audio callback is never blocked
                    threading.Thread(target=self.on_double_clap, daemon=True, name="AurexClapTrigger").start()
                except Exception as e:
                    logger.error(f"[CLAP] Error triggering double clap callback: {e}")

        elif dt > self.max_gap or self._last_clap_time == 0:
            # First clap detected, start window for second clap
            logger.debug(f"[CLAP] First clap candidate registered.")
            self._last_clap_time = now
        else:
            # Too fast (e.g. room echo < 0.15s), ignore
            pass
