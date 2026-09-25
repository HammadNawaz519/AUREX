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
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import threading
import time
from typing import Optional
from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QPlainTextEdit
from PySide6.QtCore import Qt, QUrl, QTimer, QObject, QEvent, Signal
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from app.server import run_server, set_widget_action_handler
from app.voice.controller import VoiceController, get_voice_controller

logger = logging.getLogger("AurexDesktopWidget")

CARD_W   = 384
CARD_H   = 180
SHRINK_W = 184
SHRINK_H = 56


class BridgeDispatcher(QObject):
    """Thread-safe signal dispatcher ensuring voice worker threads post events to the Qt GUI main thread."""
    action_requested = Signal(str)
    state_changed = Signal(str, str)
    user_transcript_received = Signal(str)
    assistant_response_received = Signal(str)


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

            if self.widget.controller and not self.is_space_down:
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

        # Thread-safe Qt Signal Dispatcher
        self.dispatcher = BridgeDispatcher()
        self.dispatcher.action_requested.connect(self._handle_action_main_thread)
        self.dispatcher.state_changed.connect(self._handle_state_main_thread)
        self.dispatcher.user_transcript_received.connect(self._handle_user_transcript_main_thread)
        self.dispatcher.assistant_response_received.connect(self._handle_assistant_response_main_thread)

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
        self.setFixedSize(CARD_W, CARD_H)
        self.move(x, y)

    def _position_shrink(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - SHRINK_W - 20
        y = screen.y() + 20
        self.setFixedSize(SHRINK_W, SHRINK_H)
        self.move(x, y)

    def come_up(self):
        """Bring widget above ALL applications (Chrome, VS Code, full-screen tabs)."""
        self._is_on_top = True
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            HWND_TOPMOST = -1
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOPMOST)
            ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040 | 0x0020)
        except Exception as e:
            logger.debug(f"Win32 come_up error: {e}")
        self.show()
        self.raise_()
        self.activateWindow()

    def send_to_back(self):
        """Pin widget behind active windows directly on desktop wallpaper."""
        self._is_on_top = False
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            HWND_NOTOPMOST = -2
            HWND_BOTTOM = 1
            # Remove topmost style so it can actually sit behind normal windows
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TOPMOST)
            ctypes.windll.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020)
            ctypes.windll.user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020)
        except Exception as e:
            logger.debug(f"Win32 send_to_back error: {e}")
        self.lower()

    def shrink(self):
        """Collapse to compact pill badge."""
        self._shrunken = True
        self._position_shrink()
        self.page().runJavaScript("if (window.__aurexShrink) { window.__aurexShrink(); }")
        logger.info("[DESKTOP] Widget shrunken to pill badge.")

    def expand(self):
        """Restore full card."""
        self._shrunken = False
        self._position_card()
        self.page().runJavaScript("if (window.__aurexExpand) { window.__aurexExpand(); }")
        logger.info("[DESKTOP] Widget expanded to full card.")

    # ─── Thread-Safe Handlers Called via Signals ─────────────────────────────

    def _handle_action_main_thread(self, action: str):
        logger.info(f"[DESKTOP] Processing action on GUI thread: {action}")
        if action == "come_up":
            self.come_up()
        elif action == "go_back":
            self.send_to_back()
        elif action == "shrink":
            self.shrink()
        elif action == "expand":
            self.expand()

    def _handle_state_main_thread(self, state_str: str, text: str):
        safe_t = text.replace("'", "\\'")
        js = f"window.__aurexSetState && window.__aurexSetState('{state_str}', '{safe_t}');"
        self.page().runJavaScript(js)

    def _handle_user_transcript_main_thread(self, text: str):
        safe_t = text.replace("'", "\\'")
        js = f"window.__aurexSetUserMessage && window.__aurexSetUserMessage('{safe_t}');"
        self.page().runJavaScript(js)

    def _handle_assistant_response_main_thread(self, text: str):
        safe_t = text.replace("'", "\\'")[:140]
        js = f"window.__aurexSetAssistantMessage && window.__aurexSetAssistantMessage('{safe_t}');"
        self.page().runJavaScript(js)

    # ─── Public API (Invoked from any thread) ────────────────────────────────

    def handle_action(self, action: str):
        self.dispatcher.action_requested.emit(action)

    def set_ui_state(self, state_str: str, text: str):
        self.dispatcher.state_changed.emit(state_str, text)

    def set_ui_user_message(self, text: str):
        self.dispatcher.user_transcript_received.emit(text)

    def set_ui_assistant_message(self, text: str):
        self.dispatcher.assistant_response_received.emit(text)

    def mouseDoubleClickEvent(self, event):
        """Double click anywhere on the widget to toggle between pill and box mode."""
        if self._shrunken:
            self.expand()
        else:
            self.shrink()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # If speaking, clicking widget immediately cuts off speech
            if self.controller and self.controller.tts.is_speaking:
                self.controller.tts.stop()

            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # If shrunken into pill shape, clicking expands to full card
            if self._shrunken:
                self.expand()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


def _kill_previous_instances(port: int = 8765):
    """Ensure no duplicate AUREX desktop widgets or port holders are lingering."""
    import os
    current_pid = os.getpid()

    # 1. Free target port if occupied by previous run
    try:
        import psutil
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == port and conn.pid and conn.pid != current_pid:
                try:
                    p = psutil.Process(conn.pid)
                    logger.info(f"Terminating lingering port {port} holder (PID {conn.pid})")
                    p.kill()
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Port connection check: {e}")

    # 2. Terminate any previous python process running desktop_widget
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid and 'python' in (proc.info['name'] or '').lower():
                    cmd = " ".join(proc.info['cmdline'] or [])
                    if "desktop_widget" in cmd:
                        logger.info(f"Stopping previous AUREX instance (PID {proc.info['pid']})")
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        logger.debug(f"Process cleanup check: {e}")


def launch_widget(port: int = 8765):
    """Main application entry point initializing GUI and clean push-to-talk voice subsystem."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Clean up any zombie instances first
    _kill_previous_instances(port=port)

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

    # Bind UI events thread-safely
    ctrl.on("state", lambda state, text: widget.set_ui_state(state, text))
    ctrl.on("user_transcript", lambda text: widget.set_ui_user_message(text))
    ctrl.on("assistant_response", lambda text: widget.set_ui_assistant_message(text))

    # Install application-wide event filter for Space bar push-to-talk
    key_filter = GlobalKeyFilter(widget)
    app.installEventFilter(key_filter)

    # Widget starts VISIBLE on top-right, pinned above all apps
    widget.show()
    widget.come_up()

    app.aboutToQuit.connect(ctrl.shutdown)
    logger.info("AUREX Voice System (Push-to-Talk + Double-Clap) active on desktop.")
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_widget()
