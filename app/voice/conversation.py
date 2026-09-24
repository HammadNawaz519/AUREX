"""AUREX Voice System — Active Conversation Manager & Orchestrator.

Orchestrates:
  - Mode A (Passive Wake Mode) vs Mode B (Active Conversation Mode)
  - Seamless multi-turn conversation with 30-second sliding timeout
  - High-priority barge-in interruption ("STOP" / "CANCEL" / "WAIT")
  - Fast local command routing (<150ms) with AI agent fallback
  - Thread-safe background execution (zero UI/audio blocking)
"""

from __future__ import annotations
import io
import logging
import queue
import re
import threading
import time
from typing import Callable, Dict, Any, List, Optional, Tuple
import numpy as np

from app.voice.voice_state import VoiceState, VoiceStateMachine
from app.voice.microphone import MicrophoneEngine, get_microphone
from app.voice.wake_engine import WakeEngine, match_wake_phrase
from app.voice.vad import VoiceActivityDetector, VADState
from app.voice.stt import STTEngine, get_stt
from app.voice.tts import TTSEngine, get_tts
from app.voice.local_router import FastLocalRouter
from app.voice.health import VoiceHealth, get_voice_health
from app.core.agent import get_agent

logger = logging.getLogger("AurexConversation")

INTERRUPT_KEYWORDS = ["stop", "cancel", "wait", "never mind", "abort", "quiet", "hush"]
DISMISS_KEYWORDS = ["goodbye", "bye", "dismiss", "done", "go to sleep", "stand by", "exit conversation"]


class ConversationManager:
    """Master voice pipeline orchestrator."""

    def __init__(
        self,
        mic_engine: Optional[MicrophoneEngine] = None,
        wake_engine: Optional[WakeEngine] = None,
        vad: Optional[VoiceActivityDetector] = None,
        stt: Optional[STTEngine] = None,
        tts: Optional[TTSEngine] = None,
        local_router: Optional[FastLocalRouter] = None,
        active_timeout_sec: float = 30.0,
    ):
        self.state_machine = VoiceStateMachine(initial_state=VoiceState.STARTING)
        self.mic = mic_engine or get_microphone()
        self.stt = stt or get_stt()
        self.tts = tts or get_tts()
        self.vad = vad or VoiceActivityDetector(silence_duration=0.35, min_utterance_duration=0.25)
        self.wake = wake_engine or WakeEngine(stt_transcribe_func=self.stt.transcribe)
        self.router = local_router or FastLocalRouter()
        self.health = get_voice_health()

        self.active_timeout_sec = active_timeout_sec
        self._active_deadline: float = 0.0
        self._is_running = False

        # Work queues
        self._utterance_queue: queue.Queue[Tuple[np.ndarray, int]] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None

        # Event listeners for UI integration
        self._listeners: Dict[str, List[Callable[..., None]]] = {
            "state_changed": [],
            "wake_detected": [],
            "transcription": [],
            "response": [],
            "error": [],
            "mic_status": [],
            "tts_started": [],
            "tts_finished": [],
        }

        # Wire internal listeners
        self.state_machine.add_listener(self._handle_state_transition)
        self.tts.add_start_listener(lambda: self._emit("tts_started"))
        self.tts.add_finish_listener(self._handle_tts_finished)
        self.mic.add_error_listener(self._handle_mic_error)

        # Connect mic frames to self.process_audio_frame
        self.mic.add_frame_consumer(self.process_audio_frame)

    # ─── Event Subscription ───────────────────────────────────────────────────

    def on(self, event_name: str, callback: Callable[..., None]):
        """Subscribe to UI/system events."""
        if event_name in self._listeners:
            if callback not in self._listeners[event_name]:
                self._listeners[event_name].append(callback)

    def _emit(self, event_name: str, *args, **kwargs):
        for cb in self._listeners.get(event_name, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {event_name} listener: {e}")

    def _handle_state_transition(self, old_state: VoiceState, new_state: VoiceState, reason: str = ""):
        self.health.current_state = new_state
        state_text = self._get_status_text_for_state(new_state)
        self._emit("state_changed", new_state, state_text)

    def _get_status_text_for_state(self, state: VoiceState) -> str:
        mapping = {
            VoiceState.STARTING: "Starting AUREX...",
            VoiceState.PASSIVE: "Standing by (Say 'Hey AUREX')",
            VoiceState.WAKING: "Wake detected!",
            VoiceState.ACTIVATING: "Waking up...",
            VoiceState.LISTENING: "Listening...",
            VoiceState.RECORDING: "Recording speech...",
            VoiceState.TRANSCRIBING: "Transcribing...",
            VoiceState.THINKING: "Thinking...",
            VoiceState.EXECUTING: "Executing command...",
            VoiceState.SPEAKING: "Speaking...",
            VoiceState.INTERRUPTING: "Interrupted.",
            VoiceState.ERROR: "Voice error",
            VoiceState.STOPPING: "Stopping...",
        }
        return mapping.get(state, state.value)

    def _handle_tts_finished(self):
        self._emit("tts_finished")
        # Return to LISTENING if still in active session
        if self.is_active_mode and self.state_machine.state == VoiceState.SPEAKING:
            self.vad.reset()
            self.state_machine.transition_to(VoiceState.LISTENING)

    def _handle_mic_error(self, err: str):
        self.health.record_error(err)
        self.health.microphone_connected = False
        self._emit("error", err)
        self._emit("mic_status", False, "Microphone Error")
        self.state_machine.transition_to(VoiceState.ERROR)

    @property
    def is_active_mode(self) -> bool:
        return self.state_machine.state in (
            VoiceState.WAKING,
            VoiceState.ACTIVATING,
            VoiceState.LISTENING,
            VoiceState.RECORDING,
            VoiceState.TRANSCRIBING,
            VoiceState.THINKING,
            VoiceState.EXECUTING,
            VoiceState.SPEAKING,
            VoiceState.INTERRUPTING,
        )

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        """Initialize and start the voice pipeline in Mode A (Passive Wake Mode)."""
        logger.info("[AUREX VOICE] Starting voice pipeline...")
        self._is_running = True

        # 1. Start worker thread
        self._worker_thread = threading.Thread(
            target=self._utterance_worker, daemon=True, name="AurexUtteranceWorker"
        )
        self._worker_thread.start()

        # 2. Start microphone
        mic_dev = self.mic.select_microphone()
        if mic_dev:
            self.health.microphone_connected = True
            self.health.microphone_device_name = mic_dev.name
            self._emit("mic_status", True, mic_dev.name)
        else:
            self.health.microphone_connected = False
            self._emit("mic_status", False, "No Microphone Found")

        stream_ok = self.mic.start_stream()
        if not stream_ok:
            logger.error("[AUREX VOICE] Failed to start microphone stream. Retrying in background...")
            self.state_machine.transition_to(VoiceState.ERROR)
            return

        # 3. Start Wake Engine in passive mode
        self.wake.start()
        self.health.wake_engine_alive = True
        self.state_machine.transition_to(VoiceState.PASSIVE)
        logger.info("[AUREX VOICE] Ready. Mode: PASSIVE (Listening for 'Hey AUREX')")

    def stop(self):
        """Stop all audio streams and workers."""
        logger.info("[AUREX VOICE] Stopping voice pipeline...")
        self._is_running = False
        self.state_machine.transition_to(VoiceState.STOPPING)
        self.wake.stop()
        self.mic.stop_stream()
        self.tts.stop()

    # ─── Audio Frame Callback Dispatcher ──────────────────────────────────────

    def process_audio_frame(self, mono_float: np.ndarray, mono_int16: np.ndarray, sample_rate: int):
        """Dispatches audio frames based on active state without blocking audio capture."""
        if not self._is_running:
            return

        self.health.record_audio_frame()
        current_st = self.state_machine.state

        # Check session timeout while in active mode
        if self.is_active_mode and current_st not in (VoiceState.RECORDING, VoiceState.TRANSCRIBING, VoiceState.THINKING, VoiceState.EXECUTING):
            if time.time() > self._active_deadline:
                logger.info("[AUREX VOICE] Active conversation timeout reached. Returning to PASSIVE mode.")
                self.deactivate_to_passive(speak_farewell=True)
                return

        # ── MODE A: PASSIVE WAKE MODE ─────────────────────────────────────────
        if current_st == VoiceState.PASSIVE:
            trigger = self.wake.process_audio(mono_float, mono_int16, sample_rate)
            if trigger:
                self.health.record_wake()
                self.wake.reset()
                logger.info(f"[AUREX VOICE] Wake event triggered: {trigger}")
                self._emit("wake_detected", trigger)
                self.activate_conversation(greeting="Yes, Hammad?")
            return

        # ── MODE B: ACTIVE CONVERSATION MODE ──────────────────────────────────
        # During SPEAKING: Ignore microphone input so speaker output does not trigger false feedback loop
        if current_st == VoiceState.SPEAKING:
            return

        # Normal LISTENING / RECORDING speech capture
        if current_st in (VoiceState.LISTENING, VoiceState.RECORDING):
            vad_state = self.vad.process_frame(mono_float, mono_int16, sample_rate)

            if vad_state == VADState.SPEECH_START and current_st == VoiceState.LISTENING:
                self.state_machine.transition_to(VoiceState.RECORDING)

            elif vad_state in (VADState.SPEECH_END, VADState.MAX_DURATION_REACHED) and current_st == VoiceState.RECORDING:
                self.state_machine.transition_to(VoiceState.TRANSCRIBING)
                _, captured_i16, sr = self.vad.get_recorded_audio()
                self.vad.reset()

                if len(captured_i16) > int(sr * 0.25):  # Min 250ms audio
                    self._utterance_queue.put((captured_i16, sr))
                else:
                    self.state_machine.transition_to(VoiceState.LISTENING)

    # ─── Active Conversation Controls ─────────────────────────────────────────

    def activate_conversation(self, greeting: str = "Yes, Hammad?"):
        """Awaken AUREX into Active Conversation Mode."""
        self.wake.stop()
        self.state_machine.transition_to(VoiceState.WAKING)
        self.state_machine.transition_to(VoiceState.ACTIVATING)
        self._refresh_session_timeout()

        if greeting:
            self.state_machine.transition_to(VoiceState.SPEAKING)
            self.tts.speak(greeting)
            self._emit("response", "Wake Trigger", greeting)
        else:
            self.vad.reset()
            self.state_machine.transition_to(VoiceState.LISTENING)

    def deactivate_to_passive(self, speak_farewell: bool = True):
        """Return to low-power passive wake mode."""
        self.tts.stop()
        self.vad.reset()
        if speak_farewell:
            self.tts.speak("Standing by.")
            self._emit("response", "", "Standing by.")

        self.wake.reset()
        self.wake.start()
        self.state_machine.transition_to(VoiceState.PASSIVE)
        logger.info("[AUREX VOICE] Switched to PASSIVE mode.")

    def _refresh_session_timeout(self):
        self._active_deadline = time.time() + self.active_timeout_sec

    # ─── Background Utterance Worker ──────────────────────────────────────────

    def _utterance_worker(self):
        """Processes captured utterances asynchronously so audio callback is never blocked."""
        while self._is_running:
            try:
                item = self._utterance_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            pcm_int16, sample_rate = item
            try:
                self._process_utterance(pcm_int16, sample_rate)
            except Exception as e:
                logger.error(f"[AUREX VOICE] Error processing utterance: {e}", exc_info=True)
                self.vad.reset()
                self.state_machine.transition_to(VoiceState.LISTENING)
            finally:
                self._utterance_queue.task_done()

    def _process_utterance(self, pcm_int16: np.ndarray, sample_rate: int):
        # 1. Transcribe
        transcript = self.stt.transcribe_pcm(pcm_int16, sample_rate)
        if not transcript:
            logger.debug("[AUREX VOICE] Empty transcription. Returning to LISTENING.")
            self.state_machine.transition_to(VoiceState.LISTENING)
            return

        self.health.record_command()
        self._emit("transcription", transcript)
        logger.info(f"[AUREX VOICE] User utterance: '{transcript}'")
        clean_text = transcript.strip()
        lower = clean_text.lower()

        # ── High Priority Interruption ("STOP", "CANCEL", "WAIT") ─────────────
        if any(w in lower for w in INTERRUPT_KEYWORDS):
            self.tts.stop()
            self.state_machine.transition_to(VoiceState.INTERRUPTING)
            self._refresh_session_timeout()
            reply = "Stopped, Hammad."
            self.state_machine.transition_to(VoiceState.SPEAKING)
            self.tts.speak(reply)
            self._emit("response", transcript, reply)
            return

        # ── Explicit Exit ("GOODBYE", "DISMISS", "DONE") ──────────────────────
        if any(w in lower for w in DISMISS_KEYWORDS):
            self.deactivate_to_passive(speak_farewell=True)
            return

        # ── Strip wake phrase if user said "Hey AUREX open Chrome" in one breath
        has_wake, stripped_command = match_wake_phrase(clean_text)
        command_to_execute = stripped_command if has_wake else clean_text

        # If user just said wake word alone while in conversation
        if not command_to_execute:
            self._refresh_session_timeout()
            reply = "I'm listening, Hammad."
            self.state_machine.transition_to(VoiceState.SPEAKING)
            self.tts.speak(reply)
            self._emit("response", transcript, reply)
            return

        # ── Execute Command ───────────────────────────────────────────────────
        self.state_machine.transition_to(VoiceState.THINKING)
        self._refresh_session_timeout()

        # 1. Check Fast Local Router (<150ms)
        matched_local, local_reply = self.router.handle(command_to_execute)
        if matched_local:
            self.state_machine.transition_to(VoiceState.EXECUTING)
            reply = local_reply
        else:
            # 2. Route to AI Agent for planning / computer use / complex reasoning
            self.state_machine.transition_to(VoiceState.EXECUTING)
            try:
                agent = get_agent()
                reply = agent.process_input(command_to_execute)
                # Record to context memory
                self.router.context.record_turn(command_to_execute, reply)
            except Exception as e:
                logger.error(f"[AUREX AGENT] Execution failed: {e}")
                reply = f"I encountered an error executing that: {e}"

        # ── Speak Response ────────────────────────────────────────────────────
        self.state_machine.transition_to(VoiceState.SPEAKING)
        self.tts.speak(reply)
        self._emit("response", command_to_execute, reply)


_global_conversation_mgr: Optional[ConversationManager] = None

def get_conversation_manager() -> ConversationManager:
    global _global_conversation_mgr
    if _global_conversation_mgr is None:
        _global_conversation_mgr = ConversationManager()
    return _global_conversation_mgr
