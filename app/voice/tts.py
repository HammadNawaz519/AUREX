"""Text-to-speech for AUREX — warm JARVIS-style voice (Hammad personalized)."""

import asyncio
import os
import queue
import tempfile
import threading
import logging
from typing import Optional
from app.config.settings import get_settings
from app.core.events import get_event_bus, AgentState

logger = logging.getLogger(__name__)

# Warm, cultured British neural voice — JARVIS tone
PREFERRED_VOICE = "en-GB-RyanNeural"
FALLBACK_VOICE  = "en-GB-ThomasNeural"
US_FALLBACK     = "en-US-GuyNeural"

# Natural, confident prosody — warm resonance
SPEECH_RATE   = "-3%"   # natural, unhurried
SPEECH_PITCH  = "-2Hz"  # deep, warm chest tone
SPEECH_VOLUME = "+10%"


class TextToSpeech:
    def __init__(self):
        self._queue = queue.Queue()
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True, name="AurexTTSWorker")
        self._worker_thread.start()

    def speak(self, text: str, async_mode: bool = True):
        """Speak text in a calm, warm JARVIS voice."""
        clean = text.strip()
        if not clean:
            return

        # Skip code blocks and long technical dumps for speech
        lines = clean.splitlines()
        speakable_lines = [l for l in lines if not l.startswith("```") and len(l) < 300]
        speakable = " ".join(speakable_lines[:4]).strip()
        if not speakable:
            return

        self._queue.put(speakable)

    def _process_queue(self):
        """Sequential speaker to prevent speech overlaps."""
        while True:
            text = self._queue.get()
            try:
                self._speak_sync(text)
            except Exception as e:
                logger.error(f"TTS error: {e}")
            finally:
                self._queue.task_done()

    def _speak_sync(self, text: str):
        bus = get_event_bus()
        bus.publish("state_changed", state=AgentState.SPEAKING)

        success = False

        # 1. edge-tts — high-quality British neural voice
        try:
            success = asyncio.run(self._edge_tts_speak(text))
        except Exception as e:
            logger.debug(f"edge-tts failed: {e}")

        # 2. Windows SAPI fallback (always available offline)
        if not success:
            try:
                self._sapi_speak(text)
                success = True
            except Exception as e:
                logger.warning(f"SAPI TTS failed: {e}")

        bus.publish("state_changed", state=AgentState.IDLE)

    async def _edge_tts_speak(self, text: str) -> bool:
        import edge_tts
        import sounddevice as sd
        import soundfile as sf

        settings = get_settings()
        voice = getattr(settings, "tts_voice", None) or PREFERRED_VOICE

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            temp_path = tf.name

        try:
            communicate = edge_tts.Communicate(
                text, voice,
                rate=SPEECH_RATE,
                pitch=SPEECH_PITCH,
                volume=SPEECH_VOLUME,
            )
            await asyncio.wait_for(communicate.save(temp_path), timeout=9.0)

            data, fs = sf.read(temp_path)
            sd.play(data, fs)
            sd.wait()
            return True
        except Exception as e:
            logger.debug(f"edge-tts primary error: {e}")
            # Try secondary British fallback voice
            try:
                communicate = edge_tts.Communicate(text, FALLBACK_VOICE, rate=SPEECH_RATE)
                await asyncio.wait_for(communicate.save(temp_path), timeout=8.0)
                data, fs = sf.read(temp_path)
                sd.play(data, fs)
                sd.wait()
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
        """Windows SAPI — instant offline fallback."""
        try:
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Rate = -1
            speaker.Volume = 100
            speaker.Speak(text)
        except Exception:
            clean_safe = text.replace('"', ' ').replace("'", " ")
            import subprocess
            ps = f"(New-Object -ComObject SAPI.SpVoice).Speak('{clean_safe}')"
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW
            )


_global_tts = TextToSpeech()

def get_tts() -> TextToSpeech:
    return _global_tts
