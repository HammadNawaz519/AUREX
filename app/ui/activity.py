"""Recent activity feed widget for AUREX.

Event-driven reactive architecture with zero continuous polling timers.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QHBoxLayout
)
from PySide6.QtCore import Qt
from app.memory.memory_manager import get_memory_manager
from app.ui.themes import AurexTheme
from app.core.events import get_event_bus


class ActivityFeedWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.memory = get_memory_manager()
        self._last_signatures = []
        self.init_ui()

        # Reactively listen for completed actions instead of continuous polling
        get_event_bus().subscribe("task_completed", self._on_task_event)

    def _on_task_event(self, *args, **kwargs):
        self.load_activities()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)

        # Header
        title = QLabel("Recent Activity")
        title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {AurexTheme.TEXT_SECONDARY}; letter-spacing: 1px;")
        self.layout.addWidget(title)

        # Container inside card
        self.card = QFrame()
        self.card.setObjectName("cardFrame")
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(12, 12, 12, 12)
        self.card_layout.setSpacing(6)

        self.layout.addWidget(self.card)
        self.load_activities()

    def load_activities(self):
        activities = self.memory.get_recent_activities(limit=5)
        # Check if contents have changed to avoid unnecessary widget rebuilding
        current_signatures = [f"{a.get('timestamp')}_{a.get('status')}_{a.get('summary')}" for a in activities]
        if current_signatures == self._last_signatures and self.card_layout.count() > 0:
            return
        self._last_signatures = current_signatures

        # Clear existing
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not activities:
            empty_lbl = QLabel("No recent activity. Standing by for commands.")
            empty_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-style: italic; font-size: 12px;")
            self.card_layout.addWidget(empty_lbl)
            return

        for act in activities:
            row = QHBoxLayout()
            row.setSpacing(10)

            # Status dot
            is_ok = (act["status"] == "SUCCESS")
            dot_color = AurexTheme.ACCENT_EMERALD if is_ok else AurexTheme.ACCENT_ROSE
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {dot_color}; font-size: 10px;")
            row.addWidget(dot)

            # Summary text
            text_lbl = QLabel(act["summary"])
            text_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_PRIMARY}; font-size: 12px;")
            row.addWidget(text_lbl)
            row.addStretch()

            # Timestamp
            ts_str = act["timestamp"].split()[-1] if " " in act["timestamp"] else act["timestamp"]
            ts_lbl = QLabel(ts_str)
            ts_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-size: 11px;")
            row.addWidget(ts_lbl)

            self.card_layout.addLayout(row)
