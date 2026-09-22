"""Learning Dashboard View ("WHAT I'VE LEARNED") for AUREX.

Displays learned preferences, habits, candidate routines with confidence scores,
locations, corrections, and transparency reasoning ("Why did I learn this?").
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QTabWidget,
    QFrame, QScrollArea, QMessageBox
)
from PySide6.QtCore import Qt
from app.memory.memory_manager import get_memory_manager
from app.ui.themes import AurexTheme


class LearningView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.memory = get_memory_manager()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(16)

        # Header
        top_row = QHBoxLayout()
        header = QLabel("What I've Learned • Self-Learning Engine")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        top_row.addWidget(header)
        top_row.addStretch()

        btn_refresh = QPushButton("Refresh Learning")
        btn_refresh.clicked.connect(self.load_all)
        top_row.addWidget(btn_refresh)
        main_layout.addLayout(top_row)

        desc = QLabel("AUREX learns your workflows, project paths, and preferences locally over time. Every item includes full transparency reasoning.")
        desc.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-size: 13px;")
        main_layout.addWidget(desc)

        # Tabs for Learning Categories
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
                padding: 8px 18px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {AurexTheme.BG_CARD};
                color: {AurexTheme.ACCENT_CYAN};
                font-weight: 600;
            }}
        """)

        # Tab 1: Routines
        routines_tab = QWidget()
        r_layout = QVBoxLayout(routines_tab)
        self.routine_table = QTableWidget(0, 5)
        self.routine_table.setHorizontalHeaderLabels(["Routine Name", "Actions Chain", "Confidence", "Why Learned?", "Actions"])
        self.routine_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.routine_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.routine_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.routine_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.routine_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        r_layout.addWidget(self.routine_table)
        self.tabs.addTab(routines_tab, "⚡ Routines & Workflows")

        # Tab 2: Habits
        habits_tab = QWidget()
        h_layout = QVBoxLayout(habits_tab)
        self.habit_table = QTableWidget(0, 5)
        self.habit_table.setHorizontalHeaderLabels(["Habit Name", "Time Window", "Frequency", "Confidence", "Why Learned?"])
        self.habit_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.habit_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.habit_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.habit_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.habit_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        h_layout.addWidget(self.habit_table)
        self.tabs.addTab(habits_tab, "🕒 Habits & Frequency")

        # Tab 3: Project Locations
        locations_tab = QWidget()
        loc_layout = QVBoxLayout(locations_tab)
        self.location_table = QTableWidget(0, 4)
        self.location_table.setHorizontalHeaderLabels(["Natural Phrase", "Mapped Directory", "Confidence", "Why Learned?"])
        self.location_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.location_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.location_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.location_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        loc_layout.addWidget(self.location_table)
        self.tabs.addTab(locations_tab, "📁 Project Locations")

        # Tab 4: Corrections History
        corrections_tab = QWidget()
        c_layout = QVBoxLayout(corrections_tab)
        self.correction_table = QTableWidget(0, 4)
        self.correction_table.setHorizontalHeaderLabels(["Topic Phrase", "Previous (Mistake)", "Corrected Target", "Confidence"])
        self.correction_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.correction_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.correction_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.correction_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        c_layout.addWidget(self.correction_table)
        self.tabs.addTab(corrections_tab, "🔧 Corrections")

        main_layout.addWidget(self.tabs, 1)
        self.load_all()

    def load_all(self):
        self.load_routines()
        self.load_habits()
        self.load_locations()
        self.load_corrections()

    def load_routines(self):
        routines = self.memory.list_routines()
        self.routine_table.setRowCount(len(routines))

        for row, r in enumerate(routines):
            name_item = QTableWidgetItem(r["name"])
            actions_str = " ➔ ".join(r.get("actions", []))
            act_item = QTableWidgetItem(actions_str)

            conf_pct = int(r.get("confidence", 0.1) * 100)
            badge_color = AurexTheme.ACCENT_EMERALD if conf_pct >= 70 else (AurexTheme.ACCENT_AMBER if conf_pct >= 40 else AurexTheme.TEXT_MUTED)
            conf_item = QTableWidgetItem(f"{conf_pct}% ({r.get('status', 'PROPOSED')})")
            conf_item.setForeground(Qt.GlobalColor.white)

            why_item = QTableWidgetItem(r.get("why_learned") or "Observed repeated workflow")

            self.routine_table.setItem(row, 0, name_item)
            self.routine_table.setItem(row, 1, act_item)
            self.routine_table.setItem(row, 2, conf_item)
            self.routine_table.setItem(row, 3, why_item)

            # Action controls
            act_box = QWidget()
            h = QHBoxLayout(act_box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)

            if r.get("status") == "PROPOSED":
                btn_approve = QPushButton("Approve")
                btn_approve.setObjectName("primaryButton")
                btn_approve.clicked.connect(lambda _, name=r["name"]: self._approve_routine(name))
                h.addWidget(btn_approve)

            btn_del = QPushButton("Delete")
            btn_del.setObjectName("dangerButton")
            btn_del.clicked.connect(lambda _, name=r["name"]: self._delete_routine(name))
            h.addWidget(btn_del)

            self.routine_table.setCellWidget(row, 4, act_box)

    def load_habits(self):
        habits = self.memory.list_habits()
        self.habit_table.setRowCount(len(habits))

        for row, h in enumerate(habits):
            self.habit_table.setItem(row, 0, QTableWidgetItem(h["habit_name"]))
            self.habit_table.setItem(row, 1, QTableWidgetItem(h.get("time_window") or "-"))
            self.habit_table.setItem(row, 2, QTableWidgetItem(f"{h.get('frequency', 1)} times"))
            conf_pct = int(h.get("confidence", 0.1) * 100)
            self.habit_table.setItem(row, 3, QTableWidgetItem(f"{conf_pct}%"))
            self.habit_table.setItem(row, 4, QTableWidgetItem(h.get("why_learned") or "Frequent usage pattern"))

    def load_locations(self):
        locations = self.memory.list_location_mappings()
        self.location_table.setRowCount(len(locations))

        for row, loc in enumerate(locations):
            self.location_table.setItem(row, 0, QTableWidgetItem(loc["natural_name"]))
            self.location_table.setItem(row, 1, QTableWidgetItem(loc["resolved_path"]))
            conf_pct = int(loc.get("confidence", 0.5) * 100)
            self.location_table.setItem(row, 2, QTableWidgetItem(f"{conf_pct}%"))
            self.location_table.setItem(row, 3, QTableWidgetItem(loc.get("why_learned") or "User referenced project"))

    def load_corrections(self):
        corrections = self.memory.list_corrections()
        self.correction_table.setRowCount(len(corrections))

        for row, c in enumerate(corrections):
            self.correction_table.setItem(row, 0, QTableWidgetItem(c["trigger_phrase"]))
            self.correction_table.setItem(row, 1, QTableWidgetItem(c["wrong_target"]))
            self.correction_table.setItem(row, 2, QTableWidgetItem(c["correct_target"]))
            conf_pct = int(c.get("confidence", 0.9) * 100)
            self.correction_table.setItem(row, 3, QTableWidgetItem(f"{conf_pct}%"))

    def _approve_routine(self, name: str):
        self.memory.set_routine_status(name, "APPROVED")
        QMessageBox.information(self, "Routine Approved", f"Routine '{name}' is now approved and ready for automated execution.")
        self.load_routines()

    def _delete_routine(self, name: str):
        self.memory.delete_routine(name)
        self.load_routines()
