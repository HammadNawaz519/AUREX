"""Security confirmation modal dialog for AUREX."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QScrollArea, QWidget
)
from PySide6.QtCore import Qt
from app.core.permissions import ActionRequest, ActionLevel
from app.ui.themes import AurexTheme


class ConfirmationDialog(QDialog):
    def __init__(self, request: ActionRequest, parent=None):
        super().__init__(parent)
        self.request = request
        self.setWindowTitle("AUREX Security Authorization")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setStyleSheet(AurexTheme.get_main_stylesheet())

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Header with icon and status
        header_layout = QHBoxLayout()
        title_label = QLabel("Security Confirmation Required")
        title_label.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        badge = QLabel(self.request.level.value)
        badge_bg = "rgba(245, 158, 11, 0.2)" if self.request.level == ActionLevel.CONFIRM else "rgba(244, 63, 94, 0.2)"
        badge_fg = AurexTheme.ACCENT_AMBER if self.request.level == ActionLevel.CONFIRM else AurexTheme.ACCENT_ROSE
        badge.setStyleSheet(f"background-color: {badge_bg}; color: {badge_fg}; font-weight: 700; padding: 4px 10px; border-radius: 6px;")
        header_layout.addWidget(badge)
        layout.addLayout(header_layout)

        # Action description
        desc_label = QLabel(self.request.description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 14px; line-height: 1.4;")
        layout.addWidget(desc_label)

        # Target paths or parameters card
        if self.request.target_paths:
            paths_card = QFrame()
            paths_card.setObjectName("cardFrame")
            paths_layout = QVBoxLayout(paths_card)
            paths_layout.setContentsMargins(12, 12, 12, 12)

            paths_title = QLabel("Target Paths Affected:")
            paths_title.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-weight: 600;")
            paths_layout.addWidget(paths_title)

            paths_text = QTextEdit()
            paths_text.setReadOnly(True)
            paths_text.setPlainText("\n".join(self.request.target_paths))
            paths_text.setMaximumHeight(100)
            paths_text.setStyleSheet(f"background-color: {AurexTheme.BG_SURFACE}; border: none; font-family: monospace; font-size: 12px;")
            paths_layout.addWidget(paths_text)

            layout.addWidget(paths_card)

        # Reason or warning text
        if self.request.reason:
            reason_label = QLabel(f"Note: {self.request.reason}")
            reason_label.setStyleSheet(f"color: {AurexTheme.ACCENT_AMBER}; font-style: italic;")
            layout.addWidget(reason_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(110)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_allow = QPushButton("Allow Action")
        btn_allow.setObjectName("primaryButton")
        btn_allow.setFixedWidth(130)
        btn_allow.clicked.connect(self.accept)
        btn_layout.addWidget(btn_allow)

        layout.addLayout(btn_layout)


def show_confirmation_modal(request: ActionRequest, parent=None) -> bool:
    """Helper to display confirmation modal and return user choice."""
    dlg = ConfirmationDialog(request, parent=parent)
    return dlg.exec() == QDialog.Accepted
