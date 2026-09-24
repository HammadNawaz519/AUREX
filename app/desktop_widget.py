"""AUREX Floating Desktop Widget (UI Viewport & Push-To-Talk Voice Controller).

Responsibilities:
  - Frameless translucent floating window on top-right of desktop
  - WebEngine rendering of dynamic HTML/CSS/JS interface
  - Reliable push-to-talk via Space bar and microphone button
  - Immediate user transcript rendering before agent execution
  - Clean pill/box shrink and expand transitions
"""

from __future__ import annotations
import logging
import sys
import threading
import time
from typing import Optional
from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QPlainTextEdit
from PySide6.QtCore import Qt, QUrl, QTimer, QObject, QEvent
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from app.server import run_server, set_widget_action_handler
from app.voice.controller import VoiceController, get_voice_controller

logger = logging.getLogger("AurexDesktopWidget")

CARD_W   = 384
CARD_H   = 195
SHRINK_W = 180
SHRINK_H = 54


class GlobalKeyFilter(QObject):
    """Application-wide key filter ensuring Space bar activates push-to-talk reliably."""

    def __init__(self, widget: 'FramelessDesktopWidget'):
        super().__init__()
        self.widget = widget
        self.is_space_down = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space and not event.isAutoRepeat():
            # If typing inside a standard desktop text input, do NOT hijack Space
            focused = QApplication.focusWidget()
            if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
                return False

            if self.widget.controller:
                self.is_space_down = True
                self.widget.controller.start_recording()
                return True

        elif event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Space and not event.isAutoRepeat():
            focused = QApplication.focusWidget()
            if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
                return False

            if self.widget.controller and self.is_space_down:
                self.is_space_down = False
                self.widget.controller.stop_recording()
                return True

        return super().eventFilter(watched, event)


class FramelessDesktopWidget(QWebEngineView):
    """Frameless transparent floating widget hosting the AUREX interface."""

    def __init__(self, url: str = "http://127.0.0.1:8765/"):
        super().__init__()
        self._drag_pos = None
        self._is_on_top = True
        self._shrunken  = False
        self.controller: Optional[VoiceController] = None

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
        """Pin widget behind active windows directly on desktop wallpaper."""
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

    def set_ui_user_message(self, text: str):
        """Show user transcript immediately on UI before agent finishes."""
        safe_t = text.replace("'", "\\'")
        js = f"window.__aurexSetUserMessage && window.__aurexSetUserMessage('{safe_t}');"
        QTimer.singleShot(0, lambda: self.page().runJavaScript(js))

    def set_ui_assistant_message(self, text: str):
        """Show agent response on UI."""
        safe_t = text.replace("'", "\\'")[:140]
        js = f"window.__aurexSetAssistantMessage && window.__aurexSetAssistantMessage('{safe_t}');"
        QTimer.singleShot(0, lambda: self.page().runJavaScript(js))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # If speaking, clicking widget immediately cuts off speech
            if self.controller and self.controller.tts.is_speaking:
                self.controller.tts.stop()

            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # If shrunken into pill shape, clicking expands to full card
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


def launch_widget(port: int = 8765):
    """Main application entry point initializing GUI and clean push-to-talk voice subsystem."""
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

    # Initialize Push-To-Talk Voice Controller
    ctrl = get_voice_controller()
    widget.controller = ctrl
    ctrl.set_ui_action_handler(widget.handle_action)

    # Bind UI events
    ctrl.on("state", lambda state, text: widget.set_ui_state(state, text))
    ctrl.on("user_transcript", lambda text: widget.set_ui_user_message(text))
    ctrl.on("assistant_response", lambda text: widget.set_ui_assistant_message(text))

    # Install application-wide event filter for Space bar push-to-talk
    key_filter = GlobalKeyFilter(widget)
    app.installEventFilter(key_filter)

    # Widget starts VISIBLE on top-right, pinned above all apps
    widget.show()
    widget.come_up()

    logger.info("AUREX Push-To-Talk Voice System active on desktop.")
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_widget()
