"""AUREX Voice Subsystem — Complete Central Voice Controller.

Architecture:
  SPACEBAR        -> PUSH-TO-TALK -> RECORD AUDIO -> STT -> SHOW TRANSCRIPT -> AGENT -> TTS
  DOUBLE CLAP     -> BRING FORWARD -> 5-SECOND LISTEN WINDOW -> STT / CANCEL & RESTORE WINDOW
  SPACEBAR ANYTIME-> INSTANT TTS CUTOFF & START RECORDING
"""

from __future__ import annotations
import ctypes
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from app.voice.microphone import MicrophoneRecorder, get_microphone
from app.voice.speech import SpeechToText, get_stt, clean_wake_phrase
from app.voice.clap_detector import DoubleClapDetector
from app.voice.tts import TTSEngine, get_tts
from app.core.agent import get_agent

logger = logging.getLogger("AurexVoiceController")


class VoiceController:
    """Central controller coordinating Push-To-Talk, Double-Clap trigger, and Agent execution."""

    def __init__(
        self,
        mic: Optional[MicrophoneRecorder] = None,
        speech: Optional[SpeechToText] = None,
        tts: Optional[TTSEngine] = None,
        ui_action_handler: Optional[Callable[[str], None]] = None,
        enable_clap: bool = True,
    ):
        self.mic = mic or get_microphone()
        self.speech = speech or get_stt()
        self.tts = tts or get_tts()
        self.ui_action_handler = ui_action_handler

        self._state = "IDLE"
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

        # Double-clap & temporary 5-second interaction state
        self._prev_active_hwnd: Optional[int] = None
        self._temp_window_active = False
        self._cancel_temp_window = threading.Event()
        self._temp_thread: Optional[threading.Thread] = None

        # Event callbacks
        self._listeners: Dict[str, List[Callable[..., None]]] = {
            "state": [],
            "user_transcript": [],
            "assistant_response": [],
        }

        # Wire TTS finish callback to return to IDLE
        self.tts.add_finish_listener(self._on_tts_finished)

        # Initialize lightweight double-clap detector
        self.clap_detector = DoubleClapDetector(on_double_clap=self._on_double_clap)
        if enable_clap:
            self.clap_detector.start()

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
            self._set_state("IDLE", "Space to speak")

    def set_ui_action_handler(self, handler: Callable[[str], None]):
        self.ui_action_handler = handler

    # ─── Push-to-Talk (Spacebar) ─────────────────────────────────────────────

    def start_recording(self):
        """User pressed Space bar: immediately cut off any active speech and start recording."""
        # 1. Interrupt any active speech immediately (Section 4)
        if self.tts.is_speaking:
            logger.info("[VOICE] Active speech interrupted by Spacebar push-to-talk.")
            self.tts.stop()

        # 2. Cancel any active temporary double-clap window
        self._cancel_temporary_window()

        # 3. Reset UI transcript and status
        self._emit("user_transcript", "")
        self._emit("assistant_response", "")

        # 4. Start microphone capture
        success = self.mic.start()
        if success:
            self._set_state("LISTENING", "Listening...")
        else:
            self._set_state("ERROR", "Microphone unavailable")

    def stop_recording(self):
        """User released Space bar: stop mic, transcribe, display transcript immediately, and execute."""
        if not self.mic.is_recording:
            return

        self._set_state("TRANSCRIBING", "Transcribing...")
        audio_bytes = self.mic.stop()

        if not audio_bytes or len(audio_bytes) < 200:
            logger.debug("[VOICE] Recording empty or too short, resetting to IDLE.")
            self._set_state("IDLE", "Space to speak")
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
        """Pipeline: STT -> Show Transcript Immediately -> Agent -> Show Response -> TTS."""
        try:
            # 1. Transcribe audio via Groq Whisper
            transcript = self.speech.transcribe(audio_bytes)

            if not transcript or not transcript.strip():
                logger.debug("[VOICE] No speech transcribed.")
                self._set_state("IDLE", "Space to speak")
                return

            # Strip any accidental wake phrase prefix
            _, clean = clean_wake_phrase(transcript)
            user_text = (clean if clean else transcript).strip()
            if not user_text:
                self._set_state("IDLE", "Space to speak")
                return

            # 2. SHOW USER TRANSCRIPT ON UI IMMEDIATELY (before agent runs)
            logger.info(f'[VOICE] User said: "{user_text}"')
            self._emit("user_transcript", user_text)
            self._set_state("THINKING", "Thinking...")

            # 3. Check fast local UI controls
            lower = user_text.lower().strip()
            reply = None

            if any(p in lower for p in [
                "shrink", "make small", "pill", "pill mode", "pill shape",
                "collapse", "tiny mode", "change to pill", "turn to pill",
                "change into pill", "go small", "compact", "switch to pill",
                "make it a pill", "make it pill"
            ]):
                if self.ui_action_handler:
                    self.ui_action_handler("shrink")
                reply = "Shrinking to pill mode."

            elif any(p in lower for p in [
                "expand", "make big", "box", "box mode", "box shape",
                "restore", "card mode", "full size", "revert to box",
                "change to box", "revert", "open box", "normal mode", "card shape"
            ]):
                if self.ui_action_handler:
                    self.ui_action_handler("expand")
                reply = "Restoring full interface, Hammad."

            elif any(p in lower for p in [
                "come up", "bring up", "come front", "come to front",
                "above all tabs", "front", "bring to front", "on top",
                "show front", "to the front", "bring forward", "forward"
            ]):
                if self.ui_action_handler:
                    self.ui_action_handler("come_up")
                reply = "I am right here in front of all your tabs, Hammad."

            elif any(p in lower for p in [
                "go back", "send to back", "hide behind", "wallpaper",
                "desktop", "stick to wallpaper", "pin to wallpaper",
                "to the back", "move to back", "behind windows", "behind tabs",
                "back to wallpaper", "send to wallpaper"
            ]):
                if self.ui_action_handler:
                    self.ui_action_handler("go_back")
                reply = "Pinned back to your desktop wallpaper, Hammad."

            # 4. If not a UI command, send to existing AUREX Agent for ANY task
            if reply is None:
                self._set_state("WORKING", "Working...")
                logger.info(f'[AGENT] Processing command: "{user_text}"')
                try:
                    agent = get_agent()
                    reply = agent.process_input(user_text)
                except Exception as e:
                    logger.error(f"[AGENT] Execution error: {e}")
                    reply = f"I encountered an error executing that: {e}"

            # 5. SHOW ASSISTANT RESPONSE ON UI
            self._emit("assistant_response", reply)

            # 6. SPEAK RESPONSE
            self._set_state("SPEAKING", "Speaking...")
            logger.info("[TTS] Speaking response")
            self.tts.speak(reply)

        except Exception as e:
            logger.error(f"[VOICE] Error in voice processing: {e}", exc_info=True)
            self._set_state("ERROR", "Voice processing failed")
            self.tts.speak("I encountered an error processing your request.")

    # ─── Double-Clap Trigger & 5-Second Temporary Interaction ───────────────

    def _on_double_clap(self):
        """Called when DoubleClapDetector registers two distinct claps."""
        if self.mic.is_recording or self.tts.is_speaking:
            logger.debug("[CLAP] Double clap ignored: system is already active.")
            return

        logger.info("[CLAP] Double clap triggered! Bringing AUREX front for 5s instruction window.")

        # 1. Remember previously active window (Section 9)
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                self._prev_active_hwnd = hwnd
                logger.info(f"[CLAP] Saved previously active window HWND: {hwnd}")
        except Exception as e:
            logger.debug(f"[CLAP] Error getting active window: {e}")

        # 2. Bring AUREX frontmost (Section 6)
        if self.ui_action_handler:
            self.ui_action_handler("come_up")

        # 3. Start 5-second instruction window (Section 7)
        self._cancel_temporary_window()
        self._cancel_temp_window.clear()
        self._temp_window_active = True

        self._temp_thread = threading.Thread(
            target=self._temporary_instruction_worker,
            daemon=True,
            name="Aurex5SecWindow",
        )
        self._temp_thread.start()

    def _cancel_temporary_window(self):
        if self._temp_window_active:
            self._cancel_temp_window.set()
            self._temp_window_active = False

    def _temporary_instruction_worker(self):
        """5-second instruction window: waits for speech, transcribes, or reverts to previous app."""
        self._emit("user_transcript", "")
        self._emit("assistant_response", "")
        self._set_state("LISTENING", "Listening (5s)...")

        # Start microphone
        if not self.mic.start():
            self._set_state("IDLE", "Space to speak")
            self._temp_window_active = False
            return

        start_time = time.time()
        speech_detected = False
        speech_threshold = 0.025  # Normalized RMS speech energy threshold

        # Wait up to 5.0 seconds for initial speech
        while (time.time() - start_time) < 5.0:
            if self._cancel_temp_window.is_set():
                self.mic.stop()
                self._temp_window_active = False
                return

            rms = self.mic.get_recent_rms()
            if rms >= speech_threshold:
                logger.info(f"[CLAP-WINDOW] Speech detected (RMS: {rms:.3f}). Extending capture.")
                speech_detected = True
                self._set_state("LISTENING", "Listening...")
                break

            time.sleep(0.04)

        if not speech_detected:
            # Section 8: 5 SECONDS EXPIRED, NO SPEECH DETECTED -> CANCEL & RESTORE
            logger.info("[CLAP-WINDOW] 5 seconds expired without speech. Canceling and restoring previous window.")
            self.mic.stop()
            self._temp_window_active = False
            self._set_state("IDLE", "Space to speak")

            # Hide AUREX overlay
            if self.ui_action_handler:
                self.ui_action_handler("go_back")

            # Restore previous window focus (Section 9)
            if self._prev_active_hwnd:
                try:
                    ctypes.windll.user32.SetForegroundWindow(self._prev_active_hwnd)
                    logger.info(f"[CLAP-WINDOW] Restored focus to previous HWND {self._prev_active_hwnd}")
                except Exception as e:
                    logger.debug(f"[CLAP-WINDOW] Error restoring previous window: {e}")
                self._prev_active_hwnd = None
            return

        # Section 10: USER SPOKE A COMMAND -> RECORD UNTIL SILENCE, TRANSCRIBE & EXECUTE
        silence_start: Optional[float] = None
        utterance_start = time.time()

        while (time.time() - utterance_start) < 7.0:
            if self._cancel_temp_window.is_set():
                self.mic.stop()
                self._temp_window_active = False
                return

            rms = self.mic.get_recent_rms()
            if rms < speech_threshold:
                if silence_start is None:
                    silence_start = time.time()
                elif (time.time() - silence_start) >= 0.7:
                    logger.debug("[CLAP-WINDOW] Trailing silence detected, stopping recording.")
                    break
            else:
                silence_start = None

            time.sleep(0.05)

        self._temp_window_active = False
        audio_bytes = self.mic.stop()

        transcript = ""
        if audio_bytes and len(audio_bytes) >= 200:
            self._set_state("TRANSCRIBING", "Transcribing...")
            transcript = self.speech.transcribe(audio_bytes)

        clean_text = transcript.strip(" .!?,;:") if transcript else ""
        is_meaningful = bool(clean_text) and clean_text.lower() not in ["you", "thank you", "bye"]

        if is_meaningful:
            logger.info(f"[CLAP-WINDOW] Meaningful speech captured: '{clean_text}'")
            self._prev_active_hwnd = None  # Command executed; user stays with AUREX response
            self._process_utterance(audio_bytes)
        else:
            # Section 8: No useful speech detected -> cancel and restore previous window
            logger.info("[CLAP-WINDOW] No useful speech detected. Canceling and restoring previous window.")
            self._set_state("IDLE", "Space to speak")
            if self.ui_action_handler:
                self.ui_action_handler("go_back")
            if self._prev_active_hwnd:
                try:
                    ctypes.windll.user32.SetForegroundWindow(self._prev_active_hwnd)
                    logger.info(f"[CLAP-WINDOW] Restored focus to previous HWND {self._prev_active_hwnd}")
                except Exception as e:
                    logger.debug(f"[CLAP-WINDOW] Error restoring previous window: {e}")
                self._prev_active_hwnd = None

    def shutdown(self):
        """Clean shutdown of all voice threads and listeners."""
        self._cancel_temporary_window()
        self.clap_detector.stop()
        self.mic.stop()
        self.tts.stop()


_global_controller: Optional[VoiceController] = None

def get_voice_controller() -> VoiceController:
    global _global_controller
    if _global_controller is None:
        _global_controller = VoiceController()
    return _global_controller
