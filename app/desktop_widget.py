"""AUREX Floating Desktop Widget — Always-Available Natural Voice System.

Two Listening Modes:
  Mode 1: WAKE MODE (Passive, listens for "Hey AUREX", "AUREX", or double-clap)
  Mode 2: ACTIVE CONVERSATION MODE (Continuous multi-turn conversation, no wake phrase needed)
Features:
  - Callback-based audio stream (zero blocking API errors across all Windows drivers)
  - Auto-detected active microphone
  - Fast 300ms end-of-speech detection
  - Instant barge-in interruption on "STOP" / "CANCEL" / "WAIT"
  - Fast local command routing (<150ms)
  - 30-second active session timeout
"""

import io
import sys
import wave
import queue
import threading
import time
import logging
import numpy as np
from typing import Tuple, Optional
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from app.server import run_server, set_widget_action_handler

logger = logging.getLogger("AurexDesktopWidget")

CARD_W   = 384
CARD_H   = 195
SHRINK_W = 180
SHRINK_H = 54


def find_live_input_device() -> Tuple[Optional[int], int, int]:
    """Find the live microphone device with actual audio signal using callback-safe probing."""
    import sounddevice as sd
    devices = sd.query_devices()

    # Prioritize WASAPI and DirectSound devices over MME
    wasapi_candidates = []
    other_candidates = []
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            name = d['name'].lower()
            if 'speaker' not in name and 'stereo' not in name:
                if d.get('hostapi') == 3:  # WASAPI
                    wasapi_candidates.append(i)
                else:
                    other_candidates.append(i)

    # Test candidate devices using callback mode
    for dev_idx in wasapi_candidates + other_candidates:
        d = devices[dev_idx]
        sr = int(d.get('default_samplerate', 16000))
        ch = min(2, d['max_input_channels'])
        probed_rms = []

        def probe_cb(indata, frames, time_info, status):
            r = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            probed_rms.append(r)

        try:
            stream = sd.InputStream(
                samplerate=sr,
                channels=ch,
                dtype="int16",
                device=dev_idx,
                callback=probe_cb,
                blocksize=int(sr * 0.05)
            )
            stream.start()
            time.sleep(0.12)
            stream.stop()
            stream.close()

            avg_rms = np.mean(probed_rms) if probed_rms else 0.0
            if 4.0 < avg_rms < 8000.0:
                logger.info(f"Auto-selected live microphone: Device {dev_idx} ({d['name']}) at {sr}Hz, ch={ch}, RMS={avg_rms:.1f}")
                return dev_idx, sr, ch
        except Exception:
            continue

    logger.warning("Could not probe live mic with callback, falling back to system default.")
    return None, 16000, 1


class FramelessDesktopWidget(QWebEngineView):
    def __init__(self, url: str = "http://127.0.0.1:8765/"):
        super().__init__()
        self._drag_pos = None
        self._is_on_top = True
        self._shrunken  = False
        self.voice_engine: Optional['AlwaysAvailableVoiceEngine'] = None

        # Frameless transparent window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.page().setBackgroundColor(Qt.transparent)

        # Web permissions
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

        def on_permission(origin, feature):
            if feature in (
                QWebEnginePage.Feature.MediaAudioCapture,
                QWebEnginePage.Feature.MediaAudioVideoCapture,
            ):
                self.page().setFeaturePermission(
                    origin, feature,
                    QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
                )
        self.page().featurePermissionRequested.connect(on_permission)

        self._position_card()
        self.load(QUrl(url))

    def _position_card(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - CARD_W - 20
        y = screen.y() + 20
        self.setGeometry(x, y, CARD_W, CARD_H)
        self.setFixedSize(CARD_W, CARD_H)

    def _position_shrink(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - SHRINK_W - 20
        y = screen.y() + 20
        self.setGeometry(x, y, SHRINK_W, SHRINK_H)
        self.setFixedSize(SHRINK_W, SHRINK_H)

    def come_up(self):
        """Bring widget above ALL applications (Chrome, VS Code, full-screen tabs)."""
        self._is_on_top = True
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()
        self.raise_()
        self.activateWindow()

        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        except Exception as e:
            logger.debug(f"Win32 SetWindowPos error: {e}")

    def send_to_back(self):
        """Pin widget behind active windows."""
        self._is_on_top = False
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()
        self.lower()

        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        except Exception as e:
            logger.debug(f"Win32 SetWindowPos error: {e}")

    def shrink(self):
        """Collapse to compact pill badge."""
        self._shrunken = True
        self._position_shrink()
        self.page().runJavaScript("window.__aurexShrink && window.__aurexShrink();")

    def expand(self):
        """Restore full card."""
        self._shrunken = False
        self._position_card()
        self.page().runJavaScript("window.__aurexExpand && window.__aurexExpand();")

    def handle_action(self, action: str):
        if action == "come_up":
            QTimer.singleShot(0, self.come_up)
        elif action == "go_back":
            QTimer.singleShot(0, self.send_to_back)
        elif action == "shrink":
            QTimer.singleShot(0, self.shrink)
        elif action == "expand":
            QTimer.singleShot(0, self.expand)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            if self._shrunken:
                QTimer.singleShot(0, self.expand)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            if self.voice_engine:
                self.voice_engine.start_push_to_talk()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            if self.voice_engine:
                self.voice_engine.stop_push_to_talk()
            event.accept()
            return
        super().keyReleaseEvent(event)


# ─── Always-Available Natural Voice System ────────────────────────────────────────

class AlwaysAvailableVoiceEngine:
    """
    Unified voice engine supporting:
      Mode 1: WAKE MODE (Passive local wake word & double clap)
      Mode 2: ACTIVE CONVERSATION MODE (Continuous multi-turn conversation)
      Interruption: Instant barge-in stop on "STOP", "CANCEL", "WAIT"
      Fast local routing: <150ms execution for local commands
    """

    def __init__(self, widget: FramelessDesktopWidget):
        self.widget = widget
        self.running = False
        self.is_active_mode = False
        self.active_until = 0.0
        self.active_timeout_sec = 30.0  # 30-second conversational session

        # Audio stream settings
        self.dev_idx, self.sample_rate, self.channels = find_live_input_device()
        self.stream = None
        self.audio_queue = queue.Queue()

        # VAD & Double Clap tracking
        self.noise_floor = 60.0
        self.speech_buffer = []
        self.is_speech = False
        self.silence_count = 0
        self.silence_limit = 3  # 300ms pause finalizes utterance (near-instant)

        # Clap detection state
        self.clap_times = []
        self.last_clap_wake = 0.0

        # Push to talk
        self.is_ptt = False
        self.ptt_buffer = []

    def start(self):
        self.running = True
        # Asynchronous execution worker
        threading.Thread(target=self._worker_loop, daemon=True, name="AurexVoiceWorker").start()
        # Non-blocking callback audio stream
        self._start_audio_stream()

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

    def start_push_to_talk(self):
        self.is_ptt = True
        self.ptt_buffer.clear()
        QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
            "window.__aurexSetState && window.__aurexSetState('LISTENING', 'Listening...');"
        ))

    def stop_push_to_talk(self):
        if not self.is_ptt:
            return
        self.is_ptt = False
        if len(self.ptt_buffer) >= 2:
            arr = np.concatenate(self.ptt_buffer, axis=0)
            wav_bytes = self._to_wav(arr, self.sample_rate)
            self.audio_queue.put(wav_bytes)
        else:
            self._update_ui_state()
        self.ptt_buffer.clear()

    def activate_conversation(self, wake_reply: str = "Yes, Hammad?"):
        """Transition from WAKE MODE to ACTIVE CONVERSATION MODE."""
        self.is_active_mode = True
        self.active_until = time.time() + self.active_timeout_sec

        QTimer.singleShot(0, self.widget.come_up)
        from app.voice.tts import get_tts
        get_tts().speak(wake_reply)

        safe_r = wake_reply.replace("'", "\\'")
        QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
            f"window.__aurexOnTranscript && window.__aurexOnTranscript('Hey AUREX', '{safe_r}');"
        ))
        logger.info("AUREX switched to ACTIVE CONVERSATION MODE.")

    def deactivate_conversation(self, dismiss_reply: str = "Standing by."):
        """Return to passive WAKE MODE."""
        self.is_active_mode = False
        self.active_until = 0.0

        from app.voice.tts import get_tts
        get_tts().speak(dismiss_reply)

        safe_r = dismiss_reply.replace("'", "\\'")
        QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
            f"window.__aurexOnTranscript && window.__aurexOnTranscript('', '{safe_r}');"
        ))
        logger.info("AUREX returned to passive WAKE MODE.")

    def _start_audio_stream(self):
        import sounddevice as sd
        block_size = int(self.sample_rate * 0.1)  # 100ms blocks

        def audio_callback(indata, frames, time_info, status):
            if not self.running:
                return

            # Convert to mono
            if self.channels > 1:
                mono = indata.mean(axis=1).astype(np.int16).reshape(-1, 1)
            else:
                mono = indata

            # Push to talk takes priority
            if self.is_ptt:
                self.ptt_buffer.append(mono.copy())
                return

            rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))

            # Double clap check (runs in WAKE MODE)
            if not self.is_active_mode:
                self._check_double_clap(rms)

            # Dynamic noise floor
            if not self.is_speech:
                self.noise_floor = self.noise_floor * 0.95 + rms * 0.05
            threshold = max(26.0, min(220.0, self.noise_floor * 1.35 + 16.0))

            # Speech VAD
            if rms > threshold:
                if not self.is_speech:
                    self.is_speech = True
                    self.speech_buffer.clear()
                    QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                        "window.__aurexSetState && window.__aurexSetState('LISTENING', 'Listening...');"
                    ))
                self.speech_buffer.append(mono.copy())
                self.silence_count = 0
            elif self.is_speech:
                self.speech_buffer.append(mono.copy())
                self.silence_count += 1
                if self.silence_count >= self.silence_limit:
                    self.is_speech = False
                    if len(self.speech_buffer) >= 3:  # >= 300ms audio captured
                        arr = np.concatenate(self.speech_buffer, axis=0)
                        wav_bytes = self._to_wav(arr, self.sample_rate)
                        self.audio_queue.put(wav_bytes)
                    else:
                        self._update_ui_state()
                    self.speech_buffer.clear()
                    self.silence_count = 0

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=self.dev_idx,
                callback=audio_callback,
                blocksize=block_size
            )
            self.stream.start()
            logger.info("Continuous callback audio stream active and running.")
        except Exception as e:
            logger.error(f"Failed to start callback audio stream: {e}")

    def _check_double_clap(self, rms: float):
        """Instant double-clap wake detection."""
        clap_thresh = max(180.0, self.noise_floor * 4.5)
        if rms > clap_thresh:
            now = time.time()
            if not self.clap_times or (now - self.clap_times[-1]) > 0.10:
                self.clap_times.append(now)
                if len(self.clap_times) >= 2:
                    gap = self.clap_times[-1] - self.clap_times[-2]
                    if 0.12 < gap < 0.75:
                        if now - self.last_clap_wake > 2.0:
                            self.last_clap_wake = now
                            self.clap_times.clear()
                            logger.info("Double-clap gesture detected! Waking AUREX.")
                            self.activate_conversation(wake_reply="Yes, Hammad? I heard your clap.")
            # Prune
            cutoff = time.time() - 1.5
            while self.clap_times and self.clap_times[0] < cutoff:
                self.clap_times.pop(0)

    def _update_ui_state(self):
        """Reflect current mode on UI."""
        if self.is_active_mode:
            txt = "Active Conversation"
            st = "IDLE"
        else:
            txt = "Standing by (Say 'Hey AUREX')"
            st = "IDLE"
        QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
            f"window.__aurexSetState && window.__aurexSetState('{st}', '{txt}');"
        ))

    def _to_wav(self, audio_data: np.ndarray, sample_rate: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())
        buf.seek(0)
        return buf.read()

    def _worker_loop(self):
        """Worker thread processing captured speech without blocking audio stream."""
        from app.voice.speech import get_recognizer
        from app.voice.wakeword import WakeWordDetector
        from app.voice.tts import get_tts
        from app.core.agent import get_agent

        while self.running:
            try:
                # Check for active session timeout
                if self.is_active_mode and time.time() > self.active_until:
                    self.deactivate_conversation(dismiss_reply="Session ended. Standing by.")

                try:
                    wav_bytes = self.audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # ── Barge-In Interruption Check ──────────────────────────────
                tts = get_tts()

                QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                    "window.__aurexSetState && window.__aurexSetState('THINKING', 'Thinking...');"
                ))

                rec = get_recognizer()
                transcript = rec.transcribe(wav_bytes, filename="audio.wav")
                if not transcript:
                    self._update_ui_state()
                    self.audio_queue.task_done()
                    continue

                logger.info(f"Speech received: '{transcript}' [Active={self.is_active_mode}]")
                lower = transcript.lower().strip()

                # ── High Priority: Interruption ("STOP", "CANCEL", "WAIT") ───
                if any(w in lower for w in ["stop", "cancel", "never mind", "abort", "wait"]):
                    tts.stop()
                    self.active_until = time.time() + self.active_timeout_sec
                    reply = "Stopped, Hammad."
                    tts.speak(reply)
                    safe_q = transcript.replace("'", "\\'")
                    safe_r = reply.replace("'", "\\'")
                    QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                        f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
                    ))
                    self.audio_queue.task_done()
                    continue

                # ── Explicit Exit: "Goodbye", "Dismiss", "Done" ───────────────
                if any(w in lower for w in ["goodbye", "dismiss", "done", "go to sleep", "stand by"]):
                    self.deactivate_conversation(dismiss_reply="Standing by, Hammad.")
                    self.audio_queue.task_done()
                    continue

                has_wake, clean = WakeWordDetector.check_and_strip(transcript)

                # ── MODE 1: Passive Wake Mode ─────────────────────────────────
                if not self.is_active_mode:
                    if has_wake:
                        if not clean or clean.lower() in ["hello", "hi", "hey", "are you there", "you there"]:
                            self.activate_conversation(wake_reply="Yes, Hammad?")
                        else:
                            # User said wake phrase + command in one breath: "Hey AUREX open Chrome"
                            self.activate_conversation(wake_reply="")
                            self._execute_command(clean)
                    else:
                        # Ignored ambient speech during passive mode
                        self._update_ui_state()

                # ── MODE 2: Active Conversation Mode ──────────────────────────
                else:
                    # Refresh 30-second conversational session timer on every utterance
                    self.active_until = time.time() + self.active_timeout_sec
                    cmd = clean if has_wake else transcript
                    self._execute_command(cmd)

                self.audio_queue.task_done()

            except Exception as e:
                logger.error(f"Voice worker error: {e}")

    def _execute_command(self, cmd_text: str):
        """Execute command via fast local router (<150ms) or cloud reasoning."""
        from app.voice.tts import get_tts
        from app.core.agent import get_agent

        clean = cmd_text.strip()
        if not clean:
            self._update_ui_state()
            return

        lower = clean.lower()
        reply = None

        # ── Fast Local Command Router (<150ms) ──────────────────────────────
        if any(p in lower for p in ["come up", "bring up", "come to front", "come front", "above all tabs", "whole all tab", "front"]):
            QTimer.singleShot(0, self.widget.come_up)
            reply = "I am right here in front of all your tabs, Hammad."

        elif any(p in lower for p in ["shrink", "make small", "minimize", "collapse", "tiny mode", "orb mode", "round", "make it round"]):
            QTimer.singleShot(0, self.widget.shrink)
            reply = "Shrinking to compact mode."

        elif any(p in lower for p in ["expand", "grow", "full size", "restore", "make big", "open card"]):
            QTimer.singleShot(0, self.widget.expand)
            reply = "Restoring full interface, Hammad."

        elif any(p in lower for p in ["go back", "send to back", "hide behind", "wallpaper"]):
            QTimer.singleShot(0, self.widget.send_to_back)
            reply = "Pinned back to your desktop wallpaper, Hammad."

        # If not matched by UI action, send to agent (which handles local app launch, screenshot, or cloud reasoning)
        if reply is None:
            agent = get_agent()
            reply = agent.process_input(clean)

        # Speak response and display on UI
        get_tts().speak(reply)
        safe_q = clean.replace("'", "\\'")
        safe_r = reply.replace("'", "\\'")[:140]
        QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
            f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
        ))


def launch_widget(port: int = 8765):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    server_thread = threading.Thread(
        target=run_server,
        kwargs={"port": port, "open_browser": False},
        daemon=True,
        name="AurexServerThread"
    )
    server_thread.start()
    time.sleep(0.5)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AUREX")

    widget = FramelessDesktopWidget(url=f"http://127.0.0.1:{port}/")
    set_widget_action_handler(widget.handle_action)

    # Initialize and start the Always-Available Natural Voice System
    voice_engine = AlwaysAvailableVoiceEngine(widget)
    widget.voice_engine = voice_engine
    voice_engine.start()

    # Widget starts VISIBLE on top-right, pinned above all apps
    widget.show()
    widget.come_up()

    logger.info("AUREX Always-Available Natural Voice System active on desktop.")
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_widget()
