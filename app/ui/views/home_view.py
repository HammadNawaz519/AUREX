"""Main Home view with animated AI Core (Orb), prompt controls, and quick action chips."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from app.ui.voice_surface import VoiceInteractionSurface
from app.ui.activity import ActivityFeedWidget
from app.ui.themes import AurexTheme
from app.core.events import AgentState, get_event_bus


class HomeView(QWidget):
    command_submitted = Signal(str)
    mic_pressed = Signal()
    mic_released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        get_event_bus().subscribe("state_changed", self._on_state_changed)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 30, 40, 30)
        main_layout.setSpacing(20)

        # Top Spacer
        main_layout.addStretch(1)

        # Center Header
        title = QLabel("A U R E X")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            font-size: 28px;
            font-weight: 800;
            letter-spacing: 12px;
            color: {AurexTheme.TEXT_PRIMARY};
        """)
        main_layout.addWidget(title)

        # Voice Interaction Surface Card
        surface_card = QFrame()
        surface_card.setObjectName("cardFrame")
        surface_card.setStyleSheet(f"""
            QFrame#cardFrame {{
                background-color: {AurexTheme.BG_CARD};
                border: 1px solid {AurexTheme.BORDER_SUBTLE};
                border-radius: 16px;
                padding: 24px;
            }}
        """)
        card_layout = QVBoxLayout(surface_card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(6)

        surface_title = QLabel("VOICE INTERACTION SURFACE")
        surface_title.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 1.5px;
            color: {AurexTheme.TEXT_PRIMARY};
        """)
        card_layout.addWidget(surface_title)

        surface_subtitle = QLabel("Inspired by sound waves and voice flow, creating a calm and responsive experience.")
        surface_subtitle.setStyleSheet(f"""
            font-size: 12px;
            color: {AurexTheme.TEXT_SECONDARY};
            margin-bottom: 12px;
        """)
        card_layout.addWidget(surface_subtitle)

        # Voice Visualizer Surface
        self.orb = VoiceInteractionSurface()
        self.orb.setFixedHeight(140)
        card_layout.addWidget(self.orb)

        # Status Label inside surface
        self.status_label = QLabel('"Standing by. I am listening."')
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 500;
            color: {AurexTheme.ACCENT_CYAN};
            font-style: italic;
            margin-top: 8px;
        """)
        card_layout.addWidget(self.status_label)

        main_layout.addWidget(surface_card)

        # Quick Action Chips
        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(10)
        chips_layout.addStretch()

        chips = [
            "Open Chrome",
            "What's using CPU?",
            "Take a screenshot",
            "Open VS Code",
            "Search the web for Python 3.12"
        ]
        for c in chips:
            btn = QPushButton(c)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {AurexTheme.BG_CARD};
                    color: {AurexTheme.TEXT_SECONDARY};
                    border: 1px solid {AurexTheme.BORDER_SUBTLE};
                    border-radius: 14px;
                    padding: 6px 14px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    border: 1px solid {AurexTheme.ACCENT_CYAN};
                    color: {AurexTheme.TEXT_PRIMARY};
                }}
            """)
            btn.clicked.connect(lambda ch, text=c: self._on_chip_clicked(text))
            chips_layout.addWidget(btn)

        chips_layout.addStretch()
        main_layout.addLayout(chips_layout)

        # Center-bottom Spacer
        main_layout.addStretch(1)

        # Bottom Controls: [ Mic Button ] [ Command Input ] [ Submit Button ]
        bottom_box = QHBoxLayout()
        bottom_box.setSpacing(12)

        # Microphone Push-To-Talk Button
        self.mic_btn = QPushButton("🎙")
        self.mic_btn.setFixedSize(48, 48)
        self.mic_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {AurexTheme.BG_CARD};
                color: {AurexTheme.ACCENT_CYAN};
                border: 1px solid {AurexTheme.ACCENT_CYAN};
                border-radius: 24px;
                font-size: 20px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 229, 255, 0.2);
            }}
            QPushButton:pressed {{
                background-color: {AurexTheme.ACCENT_CYAN};
                color: #040810;
            }}
        """)
        self.mic_btn.pressed.connect(self.mic_pressed.emit)
        self.mic_btn.released.connect(self.mic_released.emit)
        bottom_box.addWidget(self.mic_btn)

        # Command Input
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Speak or type a command... (e.g. 'Open VS Code and check RAM')")
        self.input_field.returnPressed.connect(self._on_submit)
        bottom_box.addWidget(self.input_field, 1)

        # Submit Button
        self.submit_btn = QPushButton("➔")
        self.submit_btn.setFixedSize(48, 48)
        self.submit_btn.setObjectName("primaryButton")
        self.submit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {AurexTheme.ACCENT_CYAN};
                color: #040810;
                border-radius: 24px;
                font-size: 18px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: #33ecff;
            }}
        """)
        self.submit_btn.clicked.connect(self._on_submit)
        bottom_box.addWidget(self.submit_btn)

        main_layout.addLayout(bottom_box)

        # Recent Activity Bar
        self.activity_feed = ActivityFeedWidget()
        main_layout.addWidget(self.activity_feed)

    def _on_chip_clicked(self, prompt: str):
        self.input_field.setText(prompt)
        self._on_submit()

    def _on_submit(self):
        text = self.input_field.text().strip()
        if text:
            self.input_field.clear()
            self.command_submitted.emit(text)

    def _on_state_changed(self, state: AgentState):
        self.orb.set_state(state)
        captions = {
            AgentState.IDLE: '"Standing by. I am listening."',
            AgentState.LISTENING: '"Listening..."',
            AgentState.THINKING: '"Thinking..."',
            AgentState.EXECUTING: '"Executing task..."',
            AgentState.SPEAKING: '"Speaking..."',
            AgentState.ERROR: '"Notice: An action requires attention."'
        }
        self.status_label.setText(captions.get(state, '""'))
