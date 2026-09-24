"""AUREX Push-To-Talk Voice System — Dedicated Microphone Recorder.

Zero background audio processing. Microphone stream is opened ONLY when recording
is requested, and closed immediately upon completion.
"""

from __future__ import annotations
import io
import logging
import threading
import time
import wave
from typing import List, Optional, Tuple
import numpy as np
import sounddevice as sd

logger = logging.getLogger("AurexMicrophone")


class MicrophoneRecorder:
    """Non-blocking, on-demand microphone recorder for push-to-talk."""

    def __init__(self, target_samplerate: int = 16000):
        self.target_samplerate = target_samplerate
        self._device_index: Optional[int] = None
        self._device_samplerate: int = target_samplerate
        self._device_channels: int = 1
        self._stream: Optional[sd.InputStream] = None
        self._chunks: List[np.ndarray] = []
        self._is_recording = False
        self._lock = threading.Lock()
        self._probe_device()

    def _probe_device(self):
        """Find working microphone device on Windows (WASAPI / WDM-KS / DirectSound)."""
        devices = sd.query_devices()
        host_apis = sd.query_hostapis()

        # Prioritize Windows WDM-KS and WASAPI devices that are physical mics
        candidates = []
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name", "").lower()
                if "speaker" not in name and "stereo mix" not in name:
                    candidates.append((i, d))

        # Test candidate streams quickly
        for dev_idx, d in candidates:
            sr = int(d.get("default_samplerate", self.target_samplerate))
            ch = min(2, d.get("max_input_channels", 1))
            try:
                test_stream = sd.InputStream(
                    samplerate=sr,
                    channels=ch,
                    dtype="int16",
                    device=dev_idx,
                    blocksize=int(sr * 0.05),
                )
                test_stream.start()
                test_stream.stop()
                test_stream.close()
                self._device_index = dev_idx
                self._device_samplerate = sr
                self._device_channels = ch
                api_name = host_apis[d.get("hostapi", 0)]["name"] if d.get("hostapi", 0) < len(host_apis) else ""
                logger.info(f"[VOICE] Microphone selected: Device {dev_idx} '{d['name']}' ({api_name}) @ {sr}Hz, ch={ch}")
                return
            except Exception:
                continue

        logger.warning("[VOICE] No tested microphone succeeded. Falling back to default.")
        self._device_index = None

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start(self) -> bool:
        """Start recording from microphone into memory buffer."""
        with self._lock:
            if self._is_recording:
                return True
            self._chunks.clear()

            def callback(indata, frames, time_info, status):
                if not self._is_recording:
                    return
                # Convert multi-channel to mono int16
                if indata.ndim > 1 and indata.shape[1] > 1:
                    mono = indata.mean(axis=1).astype(np.int16)
                else:
                    mono = indata.flatten()
                self._chunks.append(mono.copy())

            sr = self._device_samplerate
            ch = self._device_channels
            block_size = int(sr * 0.05)  # 50ms blocks

            try:
                self._stream = sd.InputStream(
                    samplerate=sr,
                    channels=ch,
                    dtype="int16",
                    device=self._device_index,
                    callback=callback,
                    blocksize=block_size,
                )
                self._stream.start()
                self._is_recording = True
                logger.info("[VOICE] Recording started")
                return True
            except Exception as e:
                logger.error(f"[VOICE] Failed to start microphone: {e}")
                self._is_recording = False
                return False

    def stop(self) -> bytes:
        """Stop microphone capture and return recorded audio as valid WAV bytes."""
        with self._lock:
            if not self._is_recording:
                return b""
            self._is_recording = False

            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

            if not self._chunks:
                logger.info("[VOICE] Recording stopped (empty buffer)")
                return b""

            audio_data = np.concatenate(self._chunks, axis=0)
            self._chunks.clear()

        duration = len(audio_data) / float(self._device_samplerate)
        logger.info(f"[VOICE] Recording stopped (duration: {duration:.2f}s, {len(audio_data)} samples)")

        # Encode to clean standard 16-bit WAV bytes
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._device_samplerate)
            wf.writeframes(audio_data.tobytes())
        return buf.getvalue()


# Global singleton instance
_global_recorder = MicrophoneRecorder()

def get_microphone() -> MicrophoneRecorder:
    return _global_recorder

# Backward-compatible alias
MicrophoneListener = MicrophoneRecorder
MicrophoneEngine = MicrophoneRecorder
