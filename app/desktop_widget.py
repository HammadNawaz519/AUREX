"""AUREX Floating Desktop Widget (UI Viewport & Voice Engine Binding).

Responsibilities:
  - Frameless translucent floating window on top-right of desktop
  - WebEngine rendering of dynamic HTML/CSS/JS interface
  - Connect PySide6 UI cleanly to the AUREX ConversationManager
  - Zero internal audio loops or competing microphone streams
"""

from __future__ import annotations
import logging
import sys
import threading
import time
from typing import Optional
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from app.server import run_server, set_widget_action_handler
from app.voice.conversation import ConversationManager, get_conversation_manager
from app.voice.voice_state import VoiceState

logger = logging.getLogger("AurexDesktopWidget")

CARD_W   = 384
CARD_H   = 195
SHRINK_W = 180
SHRINK_H = 54


class FramelessDesktopWidget(QWebEngineView):
    """Frameless transparent floating widget hosting the AUREX interface."""

    def __init__(self, url: str = "http://127.0.0.1:8765/"):
        super().__init__()
        self._drag_pos = None
        self._is_on_top = True
        self._shrunken  = False
        self.conversation_manager: Optional[ConversationManager] = None

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

    def set_ui_state(self, state_str: str, text: str):
        safe_t = text.replace("'", "\\'")
        js = f"window.__aurexSetState && window.__aurexSetState('{state_str}', '{safe_t}');"
        QTimer.singleShot(0, lambda: self.page().runJavaScript(js))

    def set_ui_transcript(self, query: str, reply: str):
        safe_q = query.replace("'", "\\'")
        safe_r = reply.replace("'", "\\'")[:140]
        js = f"window.__aurexOnTranscript && window.__aurexOnTranscript('{safe_q}', '{safe_r}');"
        QTimer.singleShot(0, lambda: self.page().runJavaScript(js))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.conversation_manager and self.conversation_manager.tts.is_speaking:
                self.conversation_manager.tts.stop()
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
            if self.conversation_manager:
                if self.conversation_manager.tts.is_speaking:
                    logger.info("Interruption triggered via Space bar.")
                    self.conversation_manager.tts.stop()
                else:
                    logger.info("Push-to-talk triggered via Space bar.")
                    self.conversation_manager.activate_conversation(greeting="")
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            event.accept()
            return
        super().keyReleaseEvent(event)


def launch_widget(port: int = 8765):
    """Main application entry point initializing GUI and clean voice subsystem."""
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

    # Initialize the Single Voice Architecture
    cm = get_conversation_manager()
    widget.conversation_manager = cm
    cm.router.set_ui_action_handler(widget.handle_action)

    # Bind UI state notifications to WebEngineView
    def on_state_changed(state: VoiceState, text: str):
        # Map state to UI representation
        ui_state = "IDLE"
        if state in (VoiceState.LISTENING, VoiceState.RECORDING):
            ui_state = "LISTENING"
        elif state in (VoiceState.THINKING, VoiceState.TRANSCRIBING):
            ui_state = "THINKING"
        elif state == VoiceState.SPEAKING:
            ui_state = "SPEAKING"
        elif state == VoiceState.ERROR:
            ui_state = "ERROR"

        widget.set_ui_state(ui_state, text)

    cm.on("state_changed", on_state_changed)
    cm.on("wake_detected", lambda trigger: QTimer.singleShot(0, widget.come_up))
    cm.on("response", lambda q, r: widget.set_ui_transcript(q, r))
    cm.on("mic_status", lambda online, dev: None if online else widget.set_ui_state("ERROR", "MIC OFFLINE"))

    # Start the clean voice pipeline
    cm.start()

    # Widget starts VISIBLE on top-right, pinned above all apps
    widget.show()
    widget.come_up()

    logger.info("AUREX Clean Voice System active on desktop.")
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_widget()
