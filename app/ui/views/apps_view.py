"""Applications manager view for discovering, launching, and terminating desktop apps."""

import psutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QTimer
from app.tools.base import get_tool_registry
from app.tools.applications import COMMON_APP_PATHS
from app.ui.themes import AurexTheme


class AppsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_status()
        if not self.timer.isActive():
            self.timer.start(5000)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.timer.isActive():
            self.timer.stop()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Header
        top_row = QHBoxLayout()
        header = QLabel("Application Hub")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        top_row.addWidget(header)
        top_row.addStretch()

        btn_refresh = QPushButton("Refresh Status")
        btn_refresh.clicked.connect(self.refresh_status)
        top_row.addWidget(btn_refresh)
        layout.addLayout(top_row)

        desc = QLabel("Discover, launch, and monitor active desktop applications.")
        desc.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        # Scroll area with app cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background-color: transparent; border: none;")

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background-color: transparent;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(16)

        scroll.setWidget(self.grid_container)
        layout.addWidget(scroll, 1)

        self.app_cards = {}
        self.populate_apps()

    def populate_apps(self):
        apps = [
            ("Google Chrome", "chrome", "🌐"),
            ("Visual Studio Code", "code", "💻"),
            ("Windows Terminal", "terminal", "⚡"),
            ("Notepad", "notepad", "📝"),
            ("Calculator", "calc", "🔢"),
            ("File Explorer", "explorer", "📁"),
            ("Spotify", "spotify", "🎵"),
            ("Discord", "discord", "💬")
        ]

        row = 0
        col = 0
        for name, cmd, icon in apps:
            card = QFrame()
            card.setObjectName("cardFrame")
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(16, 16, 16, 16)
            c_layout.setSpacing(12)

            top_h = QHBoxLayout()
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet("font-size: 24px;")
            top_h.addWidget(icon_lbl)

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-size: 14px; font-weight: 600;")
            top_h.addWidget(name_lbl)
            top_h.addStretch()

            status_badge = QLabel("Not Running")
            status_badge.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-size: 11px;")
            top_h.addWidget(status_badge)
            c_layout.addLayout(top_h)

            btn_box = QHBoxLayout()
            btn_launch = QPushButton("Launch")
            btn_launch.setObjectName("primaryButton")
            btn_launch.clicked.connect(lambda _, c=cmd: self._launch_app(c))
            btn_box.addWidget(btn_launch)

            btn_close = QPushButton("Close")
            btn_close.setObjectName("dangerButton")
            btn_close.clicked.connect(lambda _, c=cmd: self._close_app(c))
            btn_box.addWidget(btn_close)

            c_layout.addLayout(btn_box)

            self.grid_layout.addWidget(card, row, col)
            self.app_cards[cmd] = status_badge

            col += 1
            if col > 1:
                col = 0
                row += 1

        self.refresh_status()

    def refresh_status(self):
        running_names = set()
        for p in psutil.process_iter(['name']):
            try:
                running_names.add(p.info['name'].lower().replace(".exe", ""))
            except Exception:
                continue

        for cmd, badge in self.app_cards.items():
            is_running = any(cmd in r for r in running_names)
            if is_running:
                badge.setText("● Active")
                badge.setStyleSheet(f"color: {AurexTheme.ACCENT_EMERALD}; font-weight: 600; font-size: 11px;")
            else:
                badge.setText("Not Running")
                badge.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-size: 11px;")

    def _launch_app(self, cmd: str):
        reg = get_tool_registry()
        reg.execute_tool("open_application", {"name": cmd})
        QTimer.singleShot(1500, self.refresh_status)

    def _close_app(self, cmd: str):
        reg = get_tool_registry()
        reg.execute_tool("close_application", {"name": cmd})
        QTimer.singleShot(1000, self.refresh_status)
