"""AUREX Floating Desktop Widget — always-on-top or wallpaper-pinned."""

import io
import sys
import wave
import threading
import time
import logging
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from app.server import run_server, set_widget_action_handler

logger = logging.getLogger("AurexDesktopWidget")

# Widget dimensions (Ample padding to ensure bottom corners are perfectly rounded, zero clipping)
CARD_W  = 384
CARD_H  = 205
ORBS_W  = 92    # shrunken circular orb size
ORBS_H  = 92


class FramelessDesktopWidget(QWebEngineView):
    def __init__(self, url: str = "http://127.0.0.1:8765/"):
        super().__init__()
        self._drag_pos = None
        self._is_on_top = False
        self._shrunken  = False

        # Frameless transparent tool window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.page().setBackgroundColor(Qt.transparent)

        # Permissions
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

        # Position top-right corner
        self._position_card()
        self.load(QUrl(url))
        self.send_to_back()

    def _position_card(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - CARD_W - 20
        y = screen.y() + 20
        self.setGeometry(x, y, CARD_W, CARD_H)
        self.setFixedSize(CARD_W, CARD_H)

    def _position_orb(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - ORBS_W - 20
        y = screen.y() + 20
        self.setGeometry(x, y, ORBS_W, ORBS_H)
        self.setFixedSize(ORBS_W, ORBS_H)

    # ── Z-order & Visibility ───────────────────────────────────────────────────

    def come_up(self):
        """Bring widget above ALL applications (Chrome, VS Code, full-screen tabs)."""
        self._is_on_top = True
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()
        self.raise_()
        self.activateWindow()

        # Force Win32 HWND_TOPMOST so it stays pinned above all tabs
        try:
            import ctypes
            hwnd = int(self.winId())
            # HWND_TOPMOST = -1, SWP_NOMOVE = 0x0002, SWP_NOSIZE = 0x0001, SWP_SHOWWINDOW = 0x0040
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        except Exception as e:
            logger.debug(f"Win32 SetWindowPos error: {e}")

        logger.info("AUREX: brought to front above all tabs.")

    def send_to_back(self):
        """Pin widget behind active windows (desktop wallpaper level)."""
        self._is_on_top = False
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()
        self.lower()

        # Win32 HWND_BOTTOM
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        except Exception as e:
            logger.debug(f"Win32 SetWindowPos error: {e}")

        logger.info("AUREX: sent to background.")

    def shrink(self):
        """Collapse to round orb-only circle."""
        self._shrunken = True
        self._position_orb()
        self.page().runJavaScript("window.__aurexShrink && window.__aurexShrink();")
        logger.info("AUREX: shrunken to round orb.")

    def expand(self):
        """Restore full card."""
        self._shrunken = False
        self._position_card()
        self.page().runJavaScript("window.__aurexExpand && window.__aurexExpand();")
        logger.info("AUREX: expanded to full interface.")

    def handle_action(self, action: str):
        if action == "come_up":
            QTimer.singleShot(0, self.come_up)
        elif action == "go_back":
            QTimer.singleShot(0, self.send_to_back)
        elif action == "shrink":
            QTimer.singleShot(0, self.shrink)
        elif action == "expand":
            QTimer.singleShot(0, self.expand)

    # ── Drag & Click ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # Clicking the shrunken orb expands it back to the full card
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

    # ── Space key bridge ──────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.page().runJavaScript("window.__aurexStartListen && window.__aurexStartListen();")
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.page().runJavaScript("window.__aurexStopListen && window.__aurexStopListen();")
            event.accept()
            return
        super().keyReleaseEvent(event)


# ─── Continuous Background Microphone Listener ───────────────────────────────────

class AurexBackgroundListener:
    """Always-on microphone listener that listens for 'Hey AUREX' and user commands."""

    def __init__(self, widget: FramelessDesktopWidget):
        self.widget = widget
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="AurexBackgroundMic")
        self.thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        import sounddevice as sd
        from app.voice.speech import get_recognizer
        from app.voice.wakeword import WakeWordDetector
        from app.voice.tts import get_tts
        from app.core.agent import get_agent

        sample_rate = 16000
        block_size = int(sample_rate * 0.1)  # 100ms chunks
        energy_threshold = 380               # RMS voice threshold
        silence_limit = 7                    # 700ms silence to conclude utterance

        buffer = []
        is_speaking = False
        silence_count = 0

        logger.info("AUREX background audio listener initialized — active and ready.")

        while self.running:
            try:
                with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
                    while self.running:
                        data, _ = stream.read(block_size)
                        rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))

                        if rms > energy_threshold:
                            if not is_speaking:
                                is_speaking = True
                                buffer.clear()
                                QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                                    "window.__aurexSetState && window.__aurexSetState('LISTENING', 'Listening...');"
                                ))
                            buffer.append(data)
                            silence_count = 0
                        elif is_speaking:
                            buffer.append(data)
                            silence_count += 1
                            if silence_count > silence_limit:
                                is_speaking = False
                                if len(buffer) > 4:  # At least 400ms audio captured
                                    audio_arr = np.concatenate(buffer, axis=0)
                                    wav_bytes = self._to_wav(audio_arr, sample_rate)
                                    self._process_audio(wav_bytes)
                                else:
                                    QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                                        "window.__aurexSetState && window.__aurexSetState('IDLE');"
                                    ))
                                buffer.clear()
                                silence_count = 0
            except Exception as e:
                logger.warning(f"Background audio stream error: {e}. Retrying in 2 seconds...")
                time.sleep(2.0)

    def _to_wav(self, audio_data: np.ndarray, sample_rate: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())
        buf.seek(0)
        return buf.read()

    def _process_audio(self, wav_bytes: bytes):
        from app.voice.speech import get_recognizer
        from app.voice.wakeword import WakeWordDetector
        from app.voice.tts import get_tts
        from app.core.agent import get_agent

        QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
            "window.__aurexSetState && window.__aurexSetState('THINKING', 'Thinking...');"
        ))

        rec = get_recognizer()
        transcript = rec.transcribe(wav_bytes)
        if not transcript:
            QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                "window.__aurexSetState && window.__aurexSetState('IDLE');"
            ))
            return

        logger.info(f"AUREX recognized: '{transcript}'")
        lower_trans = transcript.lower()
        has_wake, clean_trans = WakeWordDetector.check_and_strip(transcript)

        # User says "Hey AUREX" or "AUREX"
        if (has_wake and not clean_trans) or clean_trans.lower() in ["", "hello", "hi", "hey", "are you there", "you there"]:
            QTimer.singleShot(0, self.widget.come_up)
            reply = "Yes Hammad."
            get_tts().speak(reply)
            safe_q = transcript.replace("'", "\\'")
            safe_r = reply.replace("'", "\\'")
            QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
            ))
        elif any(p in lower_trans for p in [
            "come up", "bring up", "come to front", "come front",
            "pop up", "wake up", "come here", "show yourself",
            "come above", "on top", "above all tabs", "whole all tab", "front"
        ]):
            QTimer.singleShot(0, self.widget.come_up)
            reply = "I am right here in front of all your tabs, Hammad."
            get_tts().speak(reply)
            safe_q = transcript.replace("'", "\\'")
            safe_r = reply.replace("'", "\\'")
            QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
            ))
        elif any(p in lower_trans for p in [
            "shrink", "make small", "minimize",
            "go small", "collapse", "tiny mode", "orb mode", "round", "circle", "make it round"
        ]):
            QTimer.singleShot(0, self.widget.shrink)
            reply = "Shrinking to orb."
            get_tts().speak(reply)
            safe_q = transcript.replace("'", "\\'")
            safe_r = reply.replace("'", "\\'")
            QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
            ))
        elif any(p in lower_trans for p in [
            "expand", "grow", "full size", "restore", "make big", "open", "card mode"
        ]):
            QTimer.singleShot(0, self.widget.expand)
            reply = "Restoring full interface, Hammad."
            get_tts().speak(reply)
            safe_q = transcript.replace("'", "\\'")
            safe_r = reply.replace("'", "\\'")
            QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
            ))
        elif has_wake or self.widget._is_on_top:
            agent = get_agent()
            reply = agent.process_input(clean_trans or transcript)
            get_tts().speak(reply)
            safe_q = (clean_trans or transcript).replace("'", "\\'")
            safe_r = reply.replace("'", "\\'")[:120]
            QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
            ))
        else:
            QTimer.singleShot(0, lambda: self.widget.page().runJavaScript(
                "window.__aurexSetState && window.__aurexSetState('IDLE');"
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

    # Start the continuous background audio listener
    listener = AurexBackgroundListener(widget)
    listener.start()

    widget.show()
    widget.send_to_back()

    logger.info("AUREX widget active — continuous listening active on desktop.")
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_widget()
