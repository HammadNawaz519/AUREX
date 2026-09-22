"""Workspace file explorer view for AUREX approved workspace."""

import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QLineEdit, QFileDialog
)
from PySide6.QtCore import Qt
from app.config.settings import get_settings
from app.tools.base import get_tool_registry
from app.ui.themes import AurexTheme


class FilesView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = get_settings()
        self.current_dir = Path(self.settings.workspace_root)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        # Header with Workspace Safety Badge
        top_row = QHBoxLayout()
        header = QLabel("Workspace File Explorer")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        top_row.addWidget(header)
        top_row.addStretch()

        badge = QLabel("🛡 APPROVED WORKSPACE ONLY")
        badge.setStyleSheet(f"""
            background-color: rgba(16, 185, 129, 0.15);
            color: {AurexTheme.ACCENT_EMERALD};
            font-weight: 700;
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 11px;
        """)
        top_row.addWidget(badge)
        layout.addLayout(top_row)

        # Notice bar
        notice = QLabel("AUREX enforces zero-write policy on C: drive. All file creation and organization occurs inside approved workspace directories.")
        notice.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(notice)

        # Navigation Bar
        nav_box = QHBoxLayout()
        btn_up = QPushButton("⬆ Up")
        btn_up.clicked.connect(self._navigate_up)
        nav_box.addWidget(btn_up)

        self.path_edit = QLineEdit(str(self.current_dir))
        self.path_edit.returnPressed.connect(self._navigate_manual)
        nav_box.addWidget(self.path_edit, 1)

        btn_go = QPushButton("Go")
        btn_go.clicked.connect(self._navigate_manual)
        nav_box.addWidget(btn_go)

        btn_open_exp = QPushButton("Open in Explorer")
        btn_open_exp.clicked.connect(self._open_in_explorer)
        nav_box.addWidget(btn_open_exp)

        layout.addLayout(nav_box)

        # File Table
        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Modified"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.file_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.file_table.cellDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.file_table, 1)

        # Bottom Action Bar
        action_box = QHBoxLayout()
        self.new_folder_input = QLineEdit()
        self.new_folder_input.setPlaceholderText("New folder name...")
        action_box.addWidget(self.new_folder_input)

        btn_new_folder = QPushButton("Create Folder")
        btn_new_folder.clicked.connect(self._create_folder)
        action_box.addWidget(btn_new_folder)

        layout.addLayout(action_box)
        self.load_directory()

    def load_directory(self):
        self.path_edit.setText(str(self.current_dir))
        reg = get_tool_registry()
        res = reg.execute_tool("list_directory", {"path": str(self.current_dir)})

        if not res.success or not isinstance(res.data, list):
            self.file_table.setRowCount(0)
            return

        items = res.data
        self.file_table.setRowCount(len(items))

        for row, item in enumerate(items):
            icon = "📁 " if item["is_dir"] else "📄 "
            name_item = QTableWidgetItem(f"{icon}{item['name']}")
            type_item = QTableWidgetItem("Directory" if item["is_dir"] else "File")

            size_str = "-" if item["is_dir"] else self._format_size(item["size_bytes"])
            size_item = QTableWidgetItem(size_str)
            mod_item = QTableWidgetItem(item["modified"])

            self.file_table.setItem(row, 0, name_item)
            self.file_table.setItem(row, 1, type_item)
            self.file_table.setItem(row, 2, size_item)
            self.file_table.setItem(row, 3, mod_item)

    def _format_size(self, b: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    def _on_item_double_clicked(self, row: int, col: int):
        name_with_icon = self.file_table.item(row, 0).text()
        name = name_with_icon.replace("📁 ", "").replace("📄 ", "")
        target = self.current_dir / name
        if target.is_dir():
            self.current_dir = target
            self.load_directory()
        else:
            # Open file with default viewer
            try:
                os.startfile(str(target))
            except Exception:
                pass

    def _navigate_up(self):
        parent = self.current_dir.parent
        if parent != self.current_dir:
            self.current_dir = parent
            self.load_directory()

    def _navigate_manual(self):
        p = Path(self.path_edit.text().strip())
        if p.exists() and p.is_dir():
            self.current_dir = p
            self.load_directory()

    def _open_in_explorer(self):
        try:
            os.startfile(str(self.current_dir))
        except Exception:
            pass

    def _create_folder(self):
        name = self.new_folder_input.text().strip()
        if name:
            target = self.current_dir / name
            reg = get_tool_registry()
            reg.execute_tool("create_folder", {"path": str(target)})
            self.new_folder_input.clear()
            self.load_directory()
