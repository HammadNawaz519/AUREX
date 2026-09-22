"""Collapsible navigation sidebar for AUREX."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QFrame, QHBoxLayout
)
from PySide6.QtCore import Qt, Signal
from app.ui.themes import AurexTheme


class AurexSidebar(QWidget):
    navigation_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_collapsed = False
        self.buttons = {}
        self.active_section = "HOME"
        self.setFixedWidth(210)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 20)
        layout.setSpacing(8)

        # Header with Logo and Collapse Toggle
        top_layout = QHBoxLayout()
        self.logo_label = QLabel("A U R E X")
        self.logo_label.setStyleSheet(
            f"font-size: 16px; font-weight: 800; letter-spacing: 4px; color: {AurexTheme.ACCENT_CYAN}; padding-left: 6px;"
        )
        top_layout.addWidget(self.logo_label)
        top_layout.addStretch()

        self.btn_toggle = QPushButton("◀")
        self.btn_toggle.setFixedSize(30, 30)
        self.btn_toggle.setStyleSheet("padding: 2px; border-radius: 6px;")
        self.btn_toggle.clicked.connect(self.toggle_collapse)
        top_layout.addWidget(self.btn_toggle)

        layout.addLayout(top_layout)

        # Subtle separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"border-top: 1px solid {AurexTheme.BORDER_SUBTLE}; margin: 10px 0;")
        layout.addWidget(sep)

        # Navigation items
        items = [
            ("HOME", "⌂  Home"),
            ("TASKS", "⚡  Tasks"),
            ("LEARNING", "🧠  Learning"),
            ("MEMORY", "💾  Memory"),
            ("FILES", "📁  Files"),
            ("APPLICATIONS", "🗔  Apps"),
            ("SYSTEM", "📊  System"),
            ("AUTOMATIONS", "⏱  Automations"),
            ("SETTINGS", "⚙  Settings")
        ]

        for key, label in items:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(self._get_button_style(is_active=(key == self.active_section)))
            btn.clicked.connect(lambda checked, k=key: self._on_btn_clicked(k))
            layout.addWidget(btn)
            self.buttons[key] = (btn, label)

        layout.addStretch()

        # Footer version label
        self.ver_label = QLabel("v1.0 • Groq Turbo")
        self.ver_label.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-size: 11px; padding-left: 8px;")
        layout.addWidget(self.ver_label)

    def _on_btn_clicked(self, key: str):
        self.set_active_section(key)
        self.navigation_requested.emit(key)

    def set_active_section(self, key: str):
        self.active_section = key
        for k, (btn, label) in self.buttons.items():
            btn.setChecked(k == key)
            btn.setStyleSheet(self._get_button_style(is_active=(k == key)))

    def _get_button_style(self, is_active: bool) -> str:
        if is_active:
            return f"""
                QPushButton {{
                    background-color: rgba(0, 229, 255, 0.15);
                    color: {AurexTheme.ACCENT_CYAN};
                    border: 1px solid {AurexTheme.ACCENT_CYAN};
                    border-radius: 8px;
                    padding: 10px 14px;
                    text-align: left;
                    font-weight: 600;
                }}
            """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {AurexTheme.TEXT_SECONDARY};
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 10px 14px;
                text-align: left;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {AurexTheme.BG_SURFACE};
                color: {AurexTheme.TEXT_PRIMARY};
                border: 1px solid {AurexTheme.BORDER_SUBTLE};
            }}
        """

    def toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.setFixedWidth(64)
            self.logo_label.setVisible(False)
            self.ver_label.setVisible(False)
            self.btn_toggle.setText("▶")
            for k, (btn, label) in self.buttons.items():
                btn.setText(label.split()[0])
        else:
            self.setFixedWidth(210)
            self.logo_label.setVisible(True)
            self.ver_label.setVisible(True)
            self.btn_toggle.setText("◀")
            for k, (btn, label) in self.buttons.items():
                btn.setText(label)
