"""Memory view for inspecting, editing, and deleting persistent preferences and aliases."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QLineEdit, QTabWidget
)
from PySide6.QtCore import Qt
from app.memory.memory_manager import get_memory_manager
from app.ui.themes import AurexTheme


class MemoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.memory = get_memory_manager()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        # Header
        top_row = QHBoxLayout()
        header = QLabel("AUREX Memory & Knowledge")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        top_row.addWidget(header)
        top_row.addStretch()

        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.load_data)
        top_row.addWidget(btn_refresh)
        layout.addLayout(top_row)

        desc = QLabel("Inspect and manage remembered preferences, project paths, and voice aliases.")
        desc.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        # Tabs for Preferences and Aliases
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {AurexTheme.BORDER_SUBTLE};
                border-radius: 8px;
                background-color: {AurexTheme.BG_CARD};
            }}
            QTabBar::tab {{
                background-color: {AurexTheme.BG_SURFACE};
                color: {AurexTheme.TEXT_SECONDARY};
                padding: 8px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {AurexTheme.BG_CARD};
                color: {AurexTheme.ACCENT_CYAN};
                font-weight: 600;
            }}
        """)

        # Tab 1: Preferences
        pref_tab = QWidget()
        pref_layout = QVBoxLayout(pref_tab)
        self.pref_table = QTableWidget(0, 3)
        self.pref_table.setHorizontalHeaderLabels(["Key", "Value", "Action"])
        self.pref_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.pref_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.pref_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        pref_layout.addWidget(self.pref_table)

        # Add Preference Row
        add_pref_box = QHBoxLayout()
        self.in_pref_key = QLineEdit()
        self.in_pref_key.setPlaceholderText("Preference key (e.g. default_browser)")
        self.in_pref_val = QLineEdit()
        self.in_pref_val.setPlaceholderText("Value (e.g. Chrome)")
        btn_add_pref = QPushButton("Save Preference")
        btn_add_pref.clicked.connect(self._add_preference)
        add_pref_box.addWidget(self.in_pref_key)
        add_pref_box.addWidget(self.in_pref_val)
        add_pref_box.addWidget(btn_add_pref)
        pref_layout.addLayout(add_pref_box)

        self.tabs.addTab(pref_tab, "Preferences")

        # Tab 2: Aliases
        alias_tab = QWidget()
        alias_layout = QVBoxLayout(alias_tab)
        self.alias_table = QTableWidget(0, 3)
        self.alias_table.setHorizontalHeaderLabels(["Voice Trigger", "Action Command", "Action"])
        self.alias_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.alias_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.alias_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        alias_layout.addWidget(self.alias_table)

        # Add Alias Row
        add_alias_box = QHBoxLayout()
        self.in_alias_trig = QLineEdit()
        self.in_alias_trig.setPlaceholderText("Voice trigger (e.g. coding)")
        self.in_alias_action = QLineEdit()
        self.in_alias_action.setPlaceholderText("Target action (e.g. open VS Code and D:\\Projects)")
        btn_add_alias = QPushButton("Add Alias")
        btn_add_alias.clicked.connect(self._add_alias)
        add_alias_box.addWidget(self.in_alias_trig)
        add_alias_box.addWidget(self.in_alias_action)
        add_alias_box.addWidget(btn_add_alias)
        alias_layout.addLayout(add_alias_box)

        self.tabs.addTab(alias_tab, "Voice Aliases")

        layout.addWidget(self.tabs, 1)
        self.load_data()

    def load_data(self):
        # Load preferences
        prefs = self.memory.list_preferences()
        self.pref_table.setRowCount(len(prefs))
        for row, p in enumerate(prefs):
            self.pref_table.setItem(row, 0, QTableWidgetItem(str(p["key"])))
            self.pref_table.setItem(row, 1, QTableWidgetItem(str(p["value"])))

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("dangerButton")
            del_btn.clicked.connect(lambda _, k=p["key"]: self._delete_preference(k))
            self.pref_table.setCellWidget(row, 2, del_btn)

        # Load aliases
        aliases = self.memory.list_aliases()
        self.alias_table.setRowCount(len(aliases))
        for row, a in enumerate(aliases):
            self.alias_table.setItem(row, 0, QTableWidgetItem(str(a["alias"])))
            self.alias_table.setItem(row, 1, QTableWidgetItem(str(a["action"])))

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("dangerButton")
            del_btn.clicked.connect(lambda _, k=a["alias"]: self._delete_alias(k))
            self.alias_table.setCellWidget(row, 2, del_btn)

    def _add_preference(self):
        k = self.in_pref_key.text().strip()
        v = self.in_pref_val.text().strip()
        if k and v:
            self.memory.set_preference(k, v)
            self.in_pref_key.clear()
            self.in_pref_val.clear()
            self.load_data()

    def _delete_preference(self, key: str):
        self.memory.delete_preference(key)
        self.load_data()

    def _add_alias(self, alias: str = ""):
        a = self.in_alias_trig.text().strip()
        cmd = self.in_alias_action.text().strip()
        if a and cmd:
            self.memory.add_alias(a, cmd)
            self.in_alias_trig.clear()
            self.in_alias_action.clear()
            self.load_data()

    def _delete_alias(self, alias: str):
        self.memory.delete_alias(alias)
        self.load_data()
