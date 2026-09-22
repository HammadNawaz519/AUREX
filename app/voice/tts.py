"""Text-to-speech output system for AUREX using edge-tts with Windows SAPI fallback."""

import asyncio
import os
import tempfile
import threading
import logging
from pathlib import Path
from typing import Optional
from app.config.settings import get_settings
from app.core.events import get_event_bus, AgentState

logger = logging.getLogger(__name__)


class TextToSpeech:
    def __init__(self):
        self._is_speaking = False
        self._lock = threading.Lock()

    def speak(self, text: str, async_mode: bool = True):
        """Speak the given text calmly."""
        clean = text.strip()
        if not clean:
            return

        # Do not speak code blocks or giant multi-line dumps
        lines = clean.splitlines()
        speakable_lines = [l for l in lines if not l.startswith("```") and len(l) < 300]
        speakable_text = " ".join(speakable_lines[:3])
        if not speakable_text:
            return

        if async_mode:
            threading.Thread(target=self._speak_sync, args=(speakable_text,), daemon=True).start()
        else:
            self._speak_sync(speakable_text)

    def _speak_sync(self, text: str):
        with self._lock:
            self._is_speaking = True
            bus = get_event_bus()
            bus.publish("state_changed", state=AgentState.SPEAKING)

            success = False
            # 1. Try edge-tts (High quality neural voice)
            try:
                success = asyncio.run(self._edge_tts_speak(text))
            except Exception as e:
                logger.debug(f"edge-tts unavailable: {e}")

            # 2. Offline fallback: Windows SAPI (built into all Windows machines)
            if not success:
                try:
                    self._sapi_speak(text)
                    success = True
                except Exception as e:
                    logger.warning(f"SAPI TTS fallback failed: {e}")

            self._is_speaking = False
            bus.publish("state_changed", state=AgentState.IDLE)

    async def _edge_tts_speak(self, text: str) -> bool:
        import edge_tts
        import sounddevice as sd
        import soundfile as sf
        settings = get_settings()
        voice = settings.tts_voice or "en-US-JennyNeural"

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            temp_path = tf.name

        try:
            communicate = edge_tts.Communicate(text, voice)
            await asyncio.wait_for(communicate.save(temp_path), timeout=5.0)

            data, fs = sf.read(temp_path)
            sd.play(data, fs)
            sd.wait()
            return True
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    def _sapi_speak(self, text: str):
        try:
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
        except Exception:
            # Simple powershell SAPI fallback if pywin32 not loaded
            import subprocess
            clean_safe = text.replace('"', '').replace("'", "")
            ps_cmd = f"Add-Type -AssemblyName System.speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{clean_safe}')"
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], creationflags=subprocess.CREATE_NO_WINDOW)


_global_tts = TextToSpeech()

def get_tts() -> TextToSpeech:
    return _global_tts
