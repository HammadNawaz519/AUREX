"""AUREX Floating Desktop Wallpaper Widget.

Fixed to the top right of the desktop wallpaper.
Pinned behind active windows by default (Z-back layer).
Brings itself to front when user says "AUREX come up".
Sends itself to back when user says "AUREX go back".
Frameless (no cross, no window borders), transparent, light theme, always listening.
"""

import sys
import os
import threading
import time
import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from app.server import run_server, set_widget_action_handler

logger = logging.getLogger("AurexDesktopWidget")


class FramelessDesktopWidget(QWebEngineView):
    def __init__(self, url: str = "http://127.0.0.1:8765/"):
        super().__init__()
        self._drag_pos = None
        self._is_on_top = False

        # 1. Desktop Tool Widget: No Window in taskbar / nav bar, No Cross, No Titlebar
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool
        )

        # 2. Transparent background so light frosted glass card floats over wallpaper
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.page().setBackgroundColor(Qt.transparent)

        # 3. Audio & Javascript Permissions
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

        def on_permission_requested(security_origin, feature):
            if feature == QWebEnginePage.Feature.MediaAudioCapture:
                self.page().setFeaturePermission(
                    security_origin,
                    feature,
                    QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
                )

        self.page().featurePermissionRequested.connect(on_permission_requested)

        # 4. Position fixed to top right of wallpaper
        screen = QApplication.primaryScreen().availableGeometry()
        width = 374
        height = 160
        x = screen.x() + screen.width() - width - 18
        y = screen.y() + 18
        self.setGeometry(x, y, width, height)
        self.setFixedSize(width, height)

        # 5. Load Voice Surface UI
        self.load(QUrl(url))

        # 6. Default: Pinned behind active windows (Z-back layer)
        self.send_to_back()

    def come_up(self):
        """Bring widget to foreground on top of all active apps."""
        self._is_on_top = True
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()
        self.raise_()
        self.activateWindow()
        logger.info("AUREX widget brought forward to front.")

    def send_to_back(self):
        """Send widget back down to wallpaper level behind active apps."""
        self._is_on_top = False
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()
        self.lower()
        logger.info("AUREX widget pinned to wallpaper level (Z-back).")

    def handle_action(self, action: str):
        """Thread-safe trigger for widget actions."""
        if action == "come_up":
            QTimer.singleShot(0, self.come_up)
        elif action == "go_back":
            QTimer.singleShot(0, self.send_to_back)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

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


def launch_widget(port: int = 8765):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Start API & static server in background thread if not already active
    server_thread = threading.Thread(
        target=run_server,
        kwargs={"port": port, "open_browser": False},
        daemon=True,
        name="AurexServerThread"
    )
    server_thread.start()

    time.sleep(0.4)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AUREX")

    widget = FramelessDesktopWidget(url=f"http://127.0.0.1:{port}/")
    set_widget_action_handler(widget.handle_action)

    widget.show()
    widget.send_to_back()

    logger.info("AUREX Top-Right Desktop Widget active (Light Theme, Z-back wallpaper pinned).")
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_widget()
