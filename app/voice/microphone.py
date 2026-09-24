"""AUREX Voice System — Dedicated Non-Blocking Microphone Engine.

Responsibilities:
  - Enumerate and probe available Windows input devices safely
  - Automatically select live microphone with non-zero audio energy
  - Continuous non-blocking callback streaming (zero blocking API errors)
  - Normalize all audio formats to float32 [-1.0, 1.0] and int16 PCM
  - Expose diagnostics, health monitoring, and exponential auto-retry
"""

import time
import threading
import logging
from typing import List, Dict, Any, Optional, Callable, Tuple
import numpy as np

logger = logging.getLogger("AurexMicrophone")


class MicrophoneDevice:
    def __init__(self, index: int, name: str, host_api: int, host_api_name: str,
                 max_channels: int, default_samplerate: float):
        self.index = index
        self.name = name
        self.host_api = host_api
        self.host_api_name = host_api_name
        self.max_channels = max_channels
        self.default_samplerate = default_samplerate

    def __repr__(self) -> str:
        return f"<Mic {self.index}: '{self.name}' ({self.host_api_name}) sr={int(self.default_samplerate)} ch={self.max_channels}>"


class MicrophoneEngine:
    """Non-blocking, robust, self-healing microphone capture engine."""

    def __init__(self, target_samplerate: int = 16000):
        self.target_samplerate = target_samplerate
        self._selected_device: Optional[MicrophoneDevice] = None
        self._stream = None
        self._running = False
        self._lock = threading.Lock()

        # Consumers subscribed to receive (mono_float32, mono_int16, sample_rate)
        self._consumers: List[Callable[[np.ndarray, np.ndarray, int], None]] = []

        # Diagnostics & Health
        self.is_receiving_audio = False
        self.last_frame_time = 0.0
        self.last_rms = 0.0
        self.last_peak = 0.0
        self._last_diag_log = 0.0
        self._retry_thread: Optional[threading.Thread] = None
        self._error_listeners: List[Callable[[str], None]] = []

    def add_frame_consumer(self, callback: Callable[[np.ndarray, np.ndarray, int], None]):
        """Register audio frame consumer: callback(mono_float, mono_int16, samplerate)."""
        with self._lock:
            if callback not in self._consumers:
                self._consumers.append(callback)

    def remove_frame_consumer(self, callback: Callable[[np.ndarray, np.ndarray, int], None]):
        with self._lock:
            if callback in self._consumers:
                self._consumers.remove(callback)

    def add_error_listener(self, callback: Callable[[str], None]):
        """Register error listener: callback(error_message)."""
        with self._lock:
            if callback not in self._error_listeners:
                self._error_listeners.append(callback)

    def get_microphone_devices(self) -> List[MicrophoneDevice]:
        """Enumerate all system input devices across all host APIs."""
        import sounddevice as sd
        devices: List[MicrophoneDevice] = []
        host_apis = sd.query_hostapis()
        raw_devices = sd.query_devices()

        for i, d in enumerate(raw_devices):
            if d.get("max_input_channels", 0) > 0:
                api_idx = d.get("hostapi", 0)
                api_name = host_apis[api_idx]["name"] if api_idx < len(host_apis) else f"API_{api_idx}"
                devices.append(MicrophoneDevice(
                    index=i,
                    name=d.get("name", f"Device_{i}"),
                    host_api=api_idx,
                    host_api_name=api_name,
                    max_channels=d.get("max_input_channels", 1),
                    default_samplerate=d.get("default_samplerate", 16000.0)
                ))
        return devices

    def select_microphone(self) -> Optional[MicrophoneDevice]:
        """
        Probe input devices using safe non-blocking callbacks.
        Finds the device with active, non-zero audio signal.
        """
        import sounddevice as sd
        all_devices = self.get_microphone_devices()

        # Prioritize WASAPI and DirectSound devices over MME
        wasapi = [d for d in all_devices if "wasapi" in d.host_api_name.lower() or d.host_api == 3]
        direct_sound = [d for d in all_devices if "directsound" in d.host_api_name.lower() or d.host_api == 1]
        others = [d for d in all_devices if d not in wasapi and d not in direct_sound]

        candidates = wasapi + direct_sound + others
        filtered = [d for d in candidates if "speaker" not in d.name.lower() and "stereo mix" not in d.name.lower()]

        for dev in (filtered or candidates):
            probed_peak = 0.0
            probed_rms = 0.0
            received = False

            def probe_cb(indata, frames, time_info, status):
                nonlocal probed_peak, probed_rms, received
                received = True
                norm = self._normalize_to_float(indata)
                probed_peak = max(probed_peak, float(np.max(np.abs(norm))))
                probed_rms = float(np.sqrt(np.mean(norm ** 2)))

            ch = min(2, dev.max_channels)
            sr = int(dev.default_samplerate)
            try:
                stream = sd.InputStream(
                    samplerate=sr,
                    channels=ch,
                    dtype="int16",
                    device=dev.index,
                    callback=probe_cb,
                    blocksize=int(sr * 0.05)
                )
                stream.start()
                time.sleep(0.12)
                stream.stop()
                stream.close()

                # A live microphone produces natural non-zero background ambient energy (> 0.0001)
                # while not exceeding 0.999 (which indicates a feedback loop or invalid driver)
                if received and (0.0001 < probed_peak < 0.98):
                    logger.info(f"Microphone probe succeeded on Device {dev.index}: '{dev.name}' ({dev.host_api_name}) Peak={probed_peak:.4f}, RMS={probed_rms:.4f}")
                    return dev
            except Exception as e:
                logger.debug(f"Device {dev.index} probe failed: {e}")
                continue

        # If probe did not find non-zero signal, pick first candidate with valid stream
        if filtered:
            return filtered[0]
        if all_devices:
            return all_devices[0]
        return None

    def start(self) -> bool:
        """Start microphone capture with startup diagnostics and auto-retry."""
        with self._lock:
            if self._running:
                return True

        print("\n[AUREX VOICE]\nInitializing microphone...")
        selected = self.select_microphone()
        if not selected:
            self._handle_error("No functional audio input devices found.")
            return False

        self._selected_device = selected
        print(f"\n[AUREX MIC]\nDevice: {selected.index}")
        print(f"Name: {selected.name}")
        print(f"Host API: {selected.host_api_name}")
        print(f"Sample Rate: {int(selected.default_samplerate)}")
        print(f"Channels: {min(2, selected.max_channels)}")

        return self._open_stream(selected)

    def _open_stream(self, device: MicrophoneDevice) -> bool:
        import sounddevice as sd
        sr = int(device.default_samplerate)
        ch = min(2, device.max_channels)
        block_size = int(sr * 0.05)  # 50ms blocks

        print("[AUREX MIC]\nOpening stream...")
        try:
            self._stream = sd.InputStream(
                samplerate=sr,
                channels=ch,
                dtype="int16",
                device=device.index,
                callback=self._audio_callback,
                blocksize=block_size
            )
            self._stream.start()
            self._running = True
            print("[AUREX MIC]\nStream started.\n[AUREX MIC]\nReceiving audio.\n")
            return True
        except Exception as e:
            self._handle_error(f"Failed to open audio stream on device {device.index}: {e}")
            self._schedule_retry()
            return False

    def _audio_callback(self, indata, frames, time_info, status):
        """High-priority non-blocking audio capture callback."""
        if not self._running:
            return

        now = time.time()
        self.last_frame_time = now
        self.is_receiving_audio = True

        # Convert to mono float32 [-1.0, 1.0] and mono int16 [-32768, 32767]
        mono_float, mono_int16 = self._process_raw_frame(indata)

        # Diagnostics metrics
        rms = float(np.sqrt(np.mean(mono_float ** 2)))
        peak = float(np.max(np.abs(mono_float))) if len(mono_float) > 0 else 0.0
        self.last_rms = rms
        self.last_peak = peak

        # Throttled diagnostics output (at most once every 1000ms during speech)
        if rms > 0.02 and (now - self._last_diag_log > 1.0):
            self._last_diag_log = now
            logger.debug(f"[AUREX AUDIO] RMS={rms:.4f} Peak={peak:.4f}")

        # Dispatch to all consumers
        sr = int(self._selected_device.default_samplerate) if self._selected_device else self.target_samplerate
        with self._lock:
            consumers = list(self._consumers)

        for consumer in consumers:
            try:
                consumer(mono_float, mono_int16, sr)
            except Exception as e:
                logger.error(f"Error in audio frame consumer: {e}")

    def _normalize_to_float(self, data: np.ndarray) -> np.ndarray:
        """Universal normalization of audio frames to float32 [-1.0, 1.0]."""
        if data.dtype == np.int16:
            return data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            return data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            return (data.astype(np.float32) - 128.0) / 128.0
        elif np.issubdtype(data.dtype, np.floating):
            return data.astype(np.float32)
        return data.astype(np.float32)

    def _process_raw_frame(self, raw_data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Convert raw multi-channel input to mono float32 and mono int16."""
        if raw_data.ndim > 1 and raw_data.shape[1] > 1:
            raw_mono = raw_data.mean(axis=1)
        else:
            raw_mono = raw_data.flatten()

        if raw_mono.dtype == np.int16:
            mono_int16 = raw_mono
            mono_float = raw_mono.astype(np.float32) / 32768.0
        else:
            mono_float = self._normalize_to_float(raw_mono)
            mono_int16 = np.clip(mono_float * 32767.0, -32768, 32767).astype(np.int16)

        return mono_float, mono_int16

    def stop(self):
        """Stop microphone stream safely."""
        with self._lock:
            self._running = False
            self.is_receiving_audio = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        logger.info("[AUREX MIC] Microphone stream stopped.")

    start_stream = start
    stop_stream = stop

    def _handle_error(self, message: str):
        logger.error(f"[AUREX MIC ERROR] {message}")
        print(f"\n[AUREX MIC ERROR] {message}\n")
        with self._lock:
            listeners = list(self._error_listeners)
        for cb in listeners:
            try:
                cb(message)
            except Exception:
                pass

    def _schedule_retry(self):
        """Schedule automatic reconnection with exponential backoff."""
        if self._retry_thread and self._retry_thread.is_alive():
            return

        def retry_worker():
            delays = [1.0, 2.0, 4.0, 8.0, 15.0]
            for delay in delays:
                logger.info(f"[AUREX MIC] Retrying microphone initialization in {delay}s...")
                time.sleep(delay)
                with self._lock:
                    if self._running:
                        return
                dev = self.select_microphone()
                if dev:
                    self._selected_device = dev
                    if self._open_stream(dev):
                        logger.info("[AUREX MIC] Microphone reconnected successfully.")
                        return

        self._retry_thread = threading.Thread(target=retry_worker, daemon=True, name="AurexMicRetry")
        self._retry_thread.start()

    @property
    def is_alive(self) -> bool:
        return self._running and (time.time() - self.last_frame_time < 1.5)

    @property
    def selected_device(self) -> Optional[MicrophoneDevice]:
        return self._selected_device


MicrophoneListener = MicrophoneEngine

_global_engine: Optional[MicrophoneEngine] = None

def get_microphone() -> MicrophoneEngine:
    global _global_engine
    if _global_engine is None:
        _global_engine = MicrophoneEngine()
    return _global_engine
