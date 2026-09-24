"""AUREX Push-To-Talk Voice Controller.

Coordinates:
  SPACEBAR / MIC BUTTON -> START RECORDING -> STOP RECORDING -> FAST STT ->
  IMMEDIATE TRANSCRIPT ON UI -> AUREX AGENT -> RESPONSE ON UI -> TTS
"""

from __future__ import annotations
import logging
import threading
from typing import Callable, Dict, List, Optional

from app.voice.microphone import MicrophoneRecorder, get_microphone
from app.voice.speech import SpeechToText, get_stt, clean_wake_phrase
from app.voice.tts import TTSEngine, get_tts
from app.core.agent import get_agent

logger = logging.getLogger("AurexVoiceController")


class VoiceController:
    """Central controller for push-to-talk voice interactions."""

    def __init__(
        self,
        mic: Optional[MicrophoneRecorder] = None,
        speech: Optional[SpeechToText] = None,
        tts: Optional[TTSEngine] = None,
        ui_action_handler: Optional[Callable[[str], None]] = None,
    ):
        self.mic = mic or get_microphone()
        self.speech = speech or get_stt()
        self.tts = tts or get_tts()
        self.ui_action_handler = ui_action_handler

        self._state = "IDLE"
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

        # Event callbacks
        self._listeners: Dict[str, List[Callable[..., None]]] = {
            "state": [],
            "user_transcript": [],
            "assistant_response": [],
        }

        # Wire TTS finish callback to return to IDLE
        self.tts.add_finish_listener(self._on_tts_finished)

    def on(self, event_name: str, callback: Callable[..., None]):
        """Subscribe to UI events: 'state', 'user_transcript', 'assistant_response'."""
        if event_name in self._listeners and callback not in self._listeners[event_name]:
            self._listeners[event_name].append(callback)

    def _emit(self, event_name: str, *args, **kwargs):
        for cb in self._listeners.get(event_name, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.error(f"[VOICE] Error in {event_name} listener: {e}")

    def _set_state(self, state: str, text: str):
        with self._lock:
            self._state = state
        self._emit("state", state, text)

    def _on_tts_finished(self):
        if self._state == "SPEAKING":
            self._set_state("IDLE", "Press Space to speak")

    def set_ui_action_handler(self, handler: Callable[[str], None]):
        self.ui_action_handler = handler

    # ─── Push-to-Talk Triggers ────────────────────────────────────────────────

    def start_recording(self):
        """User pressed Space bar or clicked microphone: start recording."""
        # 1. Interrupt any active speech immediately
        if self.tts.is_speaking:
            logger.info("[VOICE] Active speech interrupted by user voice input.")
            self.tts.stop()

        # 2. Reset partial and emit listening prompt to UI
        self._last_partial = ""
        self._emit("user_transcript", "Listening...")

        # 3. Start microphone capture
        success = self.mic.start()
        if success:
            self._set_state("LISTENING", "Listening...")
            self._stream_thread = threading.Thread(
                target=self._live_stream_worker,
                daemon=True,
                name="AurexLiveSTT"
            )
            self._stream_thread.start()
        else:
            self._set_state("ERROR", "Microphone unavailable")

    def _live_stream_worker(self):
        """Periodically transcribe in-flight audio so words appear live in UI while speaking."""
        import time
        time.sleep(0.8)
        while self.mic.is_recording:
            try:
                audio_bytes = self.mic.get_audio_so_far()
                if audio_bytes and len(audio_bytes) > 20000:
                    text = self.speech.transcribe(audio_bytes)
                    if text and self.mic.is_recording:
                        _, clean = clean_wake_phrase(text)
                        clean = clean.strip()
                        if clean and clean != getattr(self, "_last_partial", ""):
                            self._last_partial = clean
                            self._emit("user_transcript", clean)
            except Exception as e:
                logger.debug(f"[VOICE] Live partial STT: {e}")
            time.sleep(0.8)

    def stop_recording(self):
        """User released Space bar: transcribe and execute."""
        if not self.mic.is_recording:
            return

        self._set_state("TRANSCRIBING", "Transcribing...")
        audio_bytes = self.mic.stop()

        if not audio_bytes or len(audio_bytes) < 400:
            logger.debug("[VOICE] Recording too short, resetting to IDLE.")
            self._set_state("IDLE", "Press Space to speak")
            return

        # Process asynchronously so GUI thread remains completely responsive
        self._worker_thread = threading.Thread(
            target=self._process_utterance,
            args=(audio_bytes,),
            daemon=True,
            name="AurexVoiceWorker",
        )
        self._worker_thread.start()

    def _process_utterance(self, audio_bytes: bytes):
        """Background pipeline: STT -> Show Transcript -> Agent -> Show Response -> TTS."""
        try:
            # 1. Transcribe audio via Groq Whisper
            transcript = self.speech.transcribe(audio_bytes)
            if not transcript and getattr(self, "_last_partial", ""):
                transcript = self._last_partial

            if not transcript:
                self._set_state("IDLE", "Press Space to speak")
                return

            # Strip any accidental wake phrase prefix
            _, clean = clean_wake_phrase(transcript)
            user_text = (clean if clean else transcript).strip()
            if not user_text:
                self._set_state("IDLE", "Press Space to speak")
                return

            # 2. SHOW USER TRANSCRIPT ON UI IMMEDIATELY (before agent runs)
            self._emit("user_transcript", user_text)
            self._set_state("THINKING", "Thinking...")

            # 3. Check fast local UI controls
            lower = user_text.lower().strip()
            reply = None

            if any(p in lower for p in ["shrink", "make small", "pill", "pill mode", "pill shape", "collapse", "tiny mode"]):
                if self.ui_action_handler:
                    self.ui_action_handler("shrink")
                reply = "Shrinking to pill mode."

            elif any(p in lower for p in ["expand", "make big", "box", "box mode", "box shape", "restore", "card mode", "full size"]):
                if self.ui_action_handler:
                    self.ui_action_handler("expand")
                reply = "Restoring full interface, Hammad."

            elif any(p in lower for p in ["come up", "bring up", "come front", "come to front", "above all tabs", "front"]):
                if self.ui_action_handler:
                    self.ui_action_handler("come_up")
                reply = "I am right here in front of all your tabs, Hammad."

            elif any(p in lower for p in ["go back", "send to back", "hide behind", "wallpaper"]):
                if self.ui_action_handler:
                    self.ui_action_handler("go_back")
                reply = "Pinned back to your desktop wallpaper, Hammad."

            # 4. If not a UI command, send to existing AUREX Agent for ANY task
            if reply is None:
                self._set_state("EXECUTING", "Working...")
                logger.info(f'[AGENT] Processing command: "{user_text}"')
                try:
                    agent = get_agent()
                    reply = agent.process_input(user_text)
                except Exception as e:
                    logger.error(f"[AGENT] Execution error: {e}")
                    reply = f"I encountered an error executing that: {e}"

            # 5. SHOW ASSISTANT RESPONSE ON UI
            self._emit("assistant_response", reply)

            # 6. SPEAK RESPONSE (Sanitized, no terminal dumps)
            self._set_state("SPEAKING", "Speaking...")
            logger.info("[TTS] Speaking response")
            self.tts.speak(reply)

        except Exception as e:
            logger.error(f"[VOICE] Error in voice processing: {e}", exc_info=True)
            self._set_state("ERROR", "Voice processing failed")
            self.tts.speak("I encountered an error processing your request.")


_global_controller: Optional[VoiceController] = None

def get_voice_controller() -> VoiceController:
    global _global_controller
    if _global_controller is None:
        _global_controller = VoiceController()
    return _global_controller
