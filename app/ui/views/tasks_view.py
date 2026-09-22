"""Tasks view showing active task plan, progress steps, tool calls, and results."""

import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QProgressBar, QTextEdit, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer
from app.core.events import get_event_bus
from app.ui.themes import AurexTheme


class TasksView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_time = 0.0
        self.is_running = False
        self.init_ui()

        bus = get_event_bus()
        bus.subscribe("task_started", self._on_task_started)
        bus.subscribe("task_step", self._on_task_step)
        bus.subscribe("task_completed", self._on_task_completed)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_timer)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        # Header
        header = QLabel("Task Execution Monitor")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        layout.addWidget(header)

        # Task Card
        self.card = QFrame()
        self.card.setObjectName("cardFrame")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)

        # Top row: Task Title + Elapsed Time
        top_row = QHBoxLayout()
        self.task_title = QLabel("No active task. Standing by.")
        self.task_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        top_row.addWidget(self.task_title)
        top_row.addStretch()

        self.time_label = QLabel("Elapsed: 0s")
        self.time_label.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-size: 13px;")
        top_row.addWidget(self.time_label)
        card_layout.addLayout(top_row)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {AurexTheme.BG_SURFACE};
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {AurexTheme.ACCENT_CYAN};
                border-radius: 3px;
            }}
        """)
        card_layout.addWidget(self.progress_bar)

        # Steps Breakdown List
        steps_lbl = QLabel("Execution Steps & Tools:")
        steps_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-weight: 600;")
        card_layout.addWidget(steps_lbl)

        self.steps_list = QListWidget()
        self.steps_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {AurexTheme.BG_SURFACE};
                border: 1px solid {AurexTheme.BORDER_SUBTLE};
                border-radius: 8px;
                font-family: monospace;
                font-size: 13px;
                padding: 10px;
            }}
        """)
        card_layout.addWidget(self.steps_list, 1)

        # Final Outcome / Result
        result_lbl = QLabel("Task Result:")
        result_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-weight: 600;")
        card_layout.addWidget(result_lbl)

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("Results will appear here upon completion...")
        self.result_box.setFixedHeight(120)
        self.result_box.setStyleSheet(f"""
            QTextEdit {{
                background-color: {AurexTheme.BG_SURFACE};
                border: 1px solid {AurexTheme.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
            }}
        """)
        card_layout.addWidget(self.result_box)

        layout.addWidget(self.card, 1)

    def _on_task_started(self, task: str):
        self.is_running = True
        self.start_time = time.time()
        self.task_title.setText(f"Task: \"{task}\"")
        self.progress_bar.setValue(20)
        self.steps_list.clear()
        self.steps_list.addItem(f"[{time.strftime('%H:%M:%S')}] Planning & analyzing request...")
        self.result_box.clear()
        if not self.timer.isActive():
            self.timer.start(1000)

    def _on_task_step(self, step: str):
        curr = self.progress_bar.value()
        self.progress_bar.setValue(min(90, curr + 25))
        self.steps_list.addItem(f"[{time.strftime('%H:%M:%S')}] {step}")
        self.steps_list.scrollToBottom()

    def _on_task_completed(self, task: str, result: str):
        self.is_running = False
        if self.timer.isActive():
            self.timer.stop()
        self.progress_bar.setValue(100)
        self.steps_list.addItem(f"[{time.strftime('%H:%M:%S')}] Completed successfully.")
        self.steps_list.scrollToBottom()
        self.result_box.setPlainText(result)

    def _update_timer(self):
        if self.is_running:
            elapsed = int(time.time() - self.start_time)
            self.time_label.setText(f"Elapsed: {elapsed}s")
