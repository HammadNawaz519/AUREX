"""Automations manager view for scheduled computer tasks and triggers."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QLineEdit, QComboBox
)
from PySide6.QtCore import Qt
from app.memory.memory_manager import get_memory_manager
from app.ui.themes import AurexTheme


class AutomationsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.memory = get_memory_manager()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        # Header
        top_row = QHBoxLayout()
        header = QLabel("Task Automations & Scheduler")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        top_row.addWidget(header)
        top_row.addStretch()

        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.load_automations)
        top_row.addWidget(btn_refresh)
        layout.addLayout(top_row)

        desc = QLabel("Configure autonomous triggers that execute at startup or scheduled times of day.")
        desc.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        # Automations Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Title", "Trigger", "Schedule / Time", "Action Command", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        # New Automation Creator
        create_label = QLabel("Create New Scheduled Automation:")
        create_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(create_label)

        create_box = QHBoxLayout()
        self.in_title = QLineEdit()
        self.in_title.setPlaceholderText("Title (e.g. Morning Workspace)")

        self.cb_type = QComboBox()
        self.cb_type.addItems(["Daily", "Startup"])
        self.cb_type.setStyleSheet(f"background-color: {AurexTheme.BG_SURFACE}; padding: 6px; border-radius: 6px;")

        self.in_val = QLineEdit()
        self.in_val.setPlaceholderText("Time HH:MM (e.g. 09:00)")

        self.in_cmd = QLineEdit()
        self.in_cmd.setPlaceholderText("Action command (e.g. open VS Code and Chrome)")

        btn_add = QPushButton("Schedule")
        btn_add.setObjectName("primaryButton")
        btn_add.clicked.connect(self._add_automation)

        create_box.addWidget(self.in_title)
        create_box.addWidget(self.cb_type)
        create_box.addWidget(self.in_val)
        create_box.addWidget(self.in_cmd, 1)
        create_box.addWidget(btn_add)

        layout.addLayout(create_box)
        self.load_automations()

    def load_automations(self):
        autos = self.memory.list_automations()
        self.table.setRowCount(len(autos))

        for row, a in enumerate(autos):
            self.table.setItem(row, 0, QTableWidgetItem(str(a["title"])))
            self.table.setItem(row, 1, QTableWidgetItem(str(a["schedule_type"]).upper()))
            self.table.setItem(row, 2, QTableWidgetItem(str(a["schedule_val"])))
            self.table.setItem(row, 3, QTableWidgetItem(str(a["action_command"])))

            act_box = QWidget()
            h = QHBoxLayout(act_box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)

            toggle_btn = QPushButton("Active" if a["enabled"] else "Disabled")
            toggle_btn.setStyleSheet(
                f"color: {AurexTheme.ACCENT_EMERALD if a['enabled'] else AurexTheme.TEXT_MUTED}; font-weight: 600;"
            )
            toggle_btn.clicked.connect(lambda _, aid=a["id"], cur=a["enabled"]: self._toggle_automation(aid, cur))
            h.addWidget(toggle_btn)

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("dangerButton")
            del_btn.clicked.connect(lambda _, aid=a["id"]: self._delete_automation(aid))
            h.addWidget(del_btn)

            self.table.setCellWidget(row, 4, act_box)

    def _add_automation(self):
        t = self.in_title.text().strip()
        stype = self.cb_type.currentText().lower()
        val = self.in_val.text().strip() or ("startup" if stype == "startup" else "09:00")
        cmd = self.in_cmd.text().strip()

        if t and cmd:
            self.memory.add_automation(t, stype, val, cmd)
            self.in_title.clear()
            self.in_val.clear()
            self.in_cmd.clear()
            self.load_automations()

    def _toggle_automation(self, aid: int, current: bool):
        self.memory.toggle_automation(aid, not current)
        self.load_automations()

    def _delete_automation(self, aid: int):
        self.memory.delete_automation(aid)
        self.load_automations()
