"""AUREX Voice System — Interruptible TTS Engine.

Features:
  - Primary provider: EdgeTTS (British RyanNeural JARVIS-style tone)
  - Fallback provider: Windows SAPI (instant offline speech)
  - Barge-in: Instant hardware playback termination via sounddevice.stop()
  - Strictly queue-based serialization (no overlapping speech)
  - Observable speaking state and event hooks
"""

from __future__ import annotations
import asyncio
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
from typing import Callable, List, Optional
import sounddevice as sd
import soundfile as sf

from app.config.settings import get_settings
from app.core.events import get_event_bus, AgentState

logger = logging.getLogger("AurexTTS")

PREFERRED_VOICE = "en-GB-RyanNeural"
FALLBACK_VOICE  = "en-GB-ThomasNeural"
SPEECH_RATE   = "-2%"
SPEECH_PITCH  = "-2Hz"
SPEECH_VOLUME = "+10%"


def sanitize_speech_text(text: str) -> str:
    """
    Sanitize text before speech:
      - Strip markdown code blocks, backticks, JSON, and HTML
      - Strip Windows paths and URLs
      - Intercept and convert terminal stdout/stderr dumps to clean conversational summaries
      - Limit speech to 1-2 natural sentences
    """
    clean = text.strip()
    if not clean:
        return ""

    import re
    # Remove markdown code blocks ```...```
    clean = re.sub(r"```[\s\S]*?```", "", clean)
    # Remove inline code `...`
    clean = re.sub(r"`[^`]*`", "", clean)
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", "", clean)
    # Remove file paths (e.g. C:\... or D:\...)
    clean = re.sub(r"[a-zA-Z]:\\[\w\\\.\-]+", "the file", clean)
    # Remove URLs
    clean = re.sub(r"https?://\S+", "", clean)

    # Normalize unicode punctuation to safe ASCII equivalents
    clean = clean.replace("—", " - ").replace("–", " - ")
    clean = clean.replace("’", "'").replace("‘", "'")
    clean = clean.replace("“", '"').replace("”", '"')
    clean = clean.replace("\u202f", " ").replace("\u00a0", " ")

    # Only treat as raw terminal stdout dump if there are multiple lines with explicit terminal signatures
    lines = [l.strip() for l in clean.splitlines() if l.strip()]
    terminal_signatures = [
        "lastwritetime", "mode    length", "cmd.exe", "powershell", "ps ", "ps c:", "ps d:",
        "cargo build", "compiling ", "finished dev", "directory of", "bytes free",
        "npm err!", "errno -", "fatal: not a git", "exit code:"
    ]
    is_raw_terminal_dump = len(lines) >= 2 and any(
        any(sig in l.lower() for sig in terminal_signatures) for l in lines
    )
    if is_raw_terminal_dump:
        if any("success" in l.lower() or "completed" in l.lower() or "0" in l.lower() for l in lines):
            return "Command executed successfully, Hammad."
        else:
            return "The command completed with an issue, Hammad."

    # Keep only natural sentences (first 2 short sentences, under 180 chars)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(lines))
    speakable = []
    total_len = 0
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        if total_len + len(s_clean) > 200:
            break
        speakable.append(s_clean)
        total_len += len(s_clean)

    result = " ".join(speakable).strip()
    return result if result else "Done, Hammad."


class TTSEngine:
    """Thread-safe, interruptible text-to-speech engine."""

    def __init__(self):
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._is_speaking = False
        self._interrupted = False
        self._current_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

        # Callbacks
        self._on_start_callbacks: List[Callable[[], None]] = []
        self._on_finish_callbacks: List[Callable[[], None]] = []

        self._worker_thread = threading.Thread(
            target=self._process_queue, daemon=True, name="AurexTTSWorker"
        )
        self._worker_thread.start()

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def add_start_listener(self, cb: Callable[[], None]):
        if cb not in self._on_start_callbacks:
            self._on_start_callbacks.append(cb)

    def add_finish_listener(self, cb: Callable[[], None]):
        if cb not in self._on_finish_callbacks:
            self._on_finish_callbacks.append(cb)

    def stop(self):
        """Immediately cut off active speech output (Barge-in / Interruption)."""
        with self._lock:
            self._interrupted = True
            self._is_speaking = False

            # Drain any pending queued speech
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except Exception:
                    break

            # Instantly cut off audio hardware
            try:
                sd.stop()
            except Exception:
                pass

            # Terminate any fallback SAPI subprocess
            if self._current_process:
                try:
                    self._current_process.terminate()
                except Exception:
                    pass
                self._current_process = None

        logger.info("[TTS] Active speech immediately cut off by interruption.")

        # Notify event bus and finish listeners
        try:
            get_event_bus().publish("state_changed", state=AgentState.IDLE)
        except Exception:
            pass

        for cb in self._on_finish_callbacks:
            try:
                cb()
            except Exception:
                pass

    def speak(self, text: str):
        """Enqueue text for speech output."""
        speakable = sanitize_speech_text(text)
        if not speakable:
            return

        with self._lock:
            self._interrupted = False
        self._queue.put(speakable)

    def _process_queue(self):
        while True:
            text = self._queue.get()
            if text is None:
                break

            if self._interrupted:
                self._queue.task_done()
                continue

            try:
                self._speak_sync(text)
            except Exception as e:
                logger.error(f"[TTS] Speech synthesis error: {e}")
            finally:
                self._queue.task_done()

    def _speak_sync(self, text: str):
        if self._interrupted:
            return

        self._is_speaking = True
        try:
            get_event_bus().publish("state_changed", state=AgentState.SPEAKING)
        except Exception:
            pass

        for cb in self._on_start_callbacks:
            try:
                cb()
            except Exception:
                pass

        success = False

        # Attempt 1: EdgeTTS (High-fidelity neural voice)
        try:
            success = asyncio.run(self._edge_tts_speak(text))
        except Exception as e:
            logger.debug(f"[TTS] Edge-TTS error: {e}")

        # Attempt 2: Windows SAPI (Instant offline fallback)
        if not success and not self._interrupted:
            try:
                self._sapi_speak(text)
                success = True
            except Exception as e:
                logger.warning(f"[TTS] Windows SAPI fallback failed: {e}")

        self._is_speaking = False

        if not self._interrupted:
            try:
                get_event_bus().publish("state_changed", state=AgentState.IDLE)
            except Exception:
                pass

        for cb in self._on_finish_callbacks:
            try:
                cb()
            except Exception:
                pass

    async def _edge_tts_speak(self, text: str) -> bool:
        if self._interrupted:
            return False

        import edge_tts

        settings = get_settings()
        voice = getattr(settings, "tts_voice", None) or PREFERRED_VOICE

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            temp_path = tf.name

        try:
            communicate = edge_tts.Communicate(
                text,
                voice,
                rate=SPEECH_RATE,
                pitch=SPEECH_PITCH,
                volume=SPEECH_VOLUME,
            )
            await asyncio.wait_for(communicate.save(temp_path), timeout=8.0)

            if self._interrupted:
                return False

            data, fs = sf.read(temp_path)
            sd.play(data, fs)

            # Polling wait with fast interruption check (every 50ms)
            while sd.get_stream() and sd.get_stream().active:
                if self._interrupted:
                    sd.stop()
                    return False
                time.sleep(0.05)

            return True

        except Exception as e:
            logger.debug(f"[TTS] Edge-TTS primary attempt failed: {e}")
            if self._interrupted:
                return False
            try:
                communicate = edge_tts.Communicate(text, FALLBACK_VOICE, rate=SPEECH_RATE)
                await asyncio.wait_for(communicate.save(temp_path), timeout=6.0)
                if self._interrupted:
                    return False
                data, fs = sf.read(temp_path)
                sd.play(data, fs)
                while sd.get_stream() and sd.get_stream().active:
                    if self._interrupted:
                        sd.stop()
                        return False
                    time.sleep(0.05)
                return True
            except Exception:
                return False
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    def _sapi_speak(self, text: str):
        """Windows SAPI speech via PowerShell SpVoice COM object."""
        if self._interrupted:
            return

        clean_safe = text.replace('"', ' ').replace("'", " ")
        ps_cmd = f"(New-Object -ComObject SAPI.SpVoice).Speak('{clean_safe}')"
        self._current_process = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        while self._current_process.poll() is None:
            if self._interrupted:
                try:
                    self._current_process.terminate()
                except Exception:
                    pass
                self._current_process = None
                return
            time.sleep(0.05)
        self._current_process = None


# Backward-compatible alias
TextToSpeech = TTSEngine

_global_tts = TTSEngine()

def get_tts() -> TTSEngine:
    return _global_tts
