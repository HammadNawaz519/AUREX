"""Microphone recording and Voice Activity Detection (VAD) for AUREX."""

import io
import wave
import time
import threading
import logging
from typing import Callable, Optional
import numpy as np
from app.core.events import get_event_bus, AgentState

logger = logging.getLogger(__name__)


class MicrophoneListener:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._is_listening = False
        self._is_recording = False
        self._frames = []
        self._lock = threading.Lock()
        self._callback: Optional[Callable[[bytes], None]] = None
        self._stream = None

    def set_callback(self, callback: Callable[[bytes], None]):
        self._callback = callback

    def start_push_to_talk(self):
        """Start capturing audio during push-to-talk hold."""
        import sounddevice as sd
        with self._lock:
            self._frames.clear()
            self._is_recording = True
            get_event_bus().publish("state_changed", state=AgentState.LISTENING)

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio status: {status}")
            if self._is_recording:
                self._frames.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                callback=audio_callback
            )
            self._stream.start()
        except Exception as e:
            logger.warning(f"Could not open microphone for push-to-talk: {e}")
            self._is_recording = False

    def stop_push_to_talk(self) -> Optional[bytes]:
        """Stop capturing and return the recorded WAV bytes."""
        with self._lock:
            self._is_recording = False

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if not self._frames:
            get_event_bus().publish("state_changed", state=AgentState.IDLE)
            return None

        audio_data = np.concatenate(self._frames, axis=0)
        self._frames.clear()
        wav_bytes = self._to_wav_bytes(audio_data)
        get_event_bus().publish("state_changed", state=AgentState.THINKING)
        return wav_bytes

    def _to_wav_bytes(self, audio_data: np.ndarray) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit int
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data.tobytes())
        buf.seek(0)
        return buf.read()

    def start_continuous_listening(self):
        """Start background VAD listening loop."""
        if self._is_listening:
            return
        self._is_listening = True
        threading.Thread(target=self._vad_loop, daemon=True, name="AurexVADThread").start()

    def stop_continuous_listening(self):
        self._is_listening = False

    def _vad_loop(self):
        """Simple RMS energy-based voice activity detector."""
        try:
            import sounddevice as sd
        except Exception as e:
            logger.warning(f"sounddevice not available for continuous listening: {e}")
            return

        block_size = int(self.sample_rate * 0.1)  # 100ms blocks
        silence_threshold = 450  # RMS threshold
        silence_blocks_limit = 8  # 800ms of silence to end phrase

        buffer = []
        is_speaking = False
        silence_count = 0

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=self.channels, dtype="int16") as stream:
                while self._is_listening:
                    data, _ = stream.read(block_size)
                    rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))

                    if rms > silence_threshold:
                        if not is_speaking:
                            is_speaking = True
                            buffer.clear()
                            get_event_bus().publish("state_changed", state=AgentState.LISTENING)
                        buffer.append(data)
                        silence_count = 0
                    elif is_speaking:
                        buffer.append(data)
                        silence_count += 1
                        if silence_count > silence_blocks_limit:
                            is_speaking = False
                            # Finished speaking
                            if len(buffer) > 5:  # At least 500ms of audio
                                concatenated = np.concatenate(buffer, axis=0)
                                wav_bytes = self._to_wav_bytes(concatenated)
                                if self._callback:
                                    self._callback(wav_bytes)
                            buffer.clear()
                            silence_count = 0
        except Exception as e:
            logger.warning(f"Continuous microphone loop stopped: {e}")
            self._is_listening = False


_global_listener = MicrophoneListener()

def get_microphone() -> MicrophoneListener:
    return _global_listener
