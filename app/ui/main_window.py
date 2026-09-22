"""Main Desktop Application Window for AUREX.

Dedicated Voice Interaction Surface - Pure voice command system.
"""

import sys
import threading
import logging

logger = logging.getLogger(__name__)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from app.ui.voice_surface import VoiceInteractionSurface
from app.ui.dialogs import show_confirmation_modal
from app.ui.themes import AurexTheme
from app.core.events import AgentState, get_event_bus
from app.core.agent import get_agent
from app.core.permissions import get_permission_manager, ActionRequest
from app.voice.microphone import get_microphone
from app.voice.speech import get_recognizer
from app.voice.tts import get_tts
from app.automation.scheduler import get_scheduler

# Lazy imports for backwards compatibility with tests
from app.ui.views.home_view import HomeView
from app.ui.views.tasks_view import TasksView
from app.ui.views.learning_view import LearningView
from app.ui.views.memory_view import MemoryView
from app.ui.views.files_view import FilesView
from app.ui.views.apps_view import AppsView
from app.ui.views.system_view import SystemView
from app.ui.views.automations_view import AutomationsView
from app.ui.views.settings_view import SettingsView


class AgentWorker(QThread):
    finished_signal = Signal(str)

    def __init__(self, command: str):
        super().__init__()
        self.command = command

    def run(self):
        try:
            agent = get_agent()
            result = agent.process_input(self.command)
            self.finished_signal.emit(result)
        except Exception as e:
            logger.error(f"AgentWorker execution error: {e}", exc_info=True)
            self.finished_signal.emit(f"Error processing command: {e}")


class VoiceTranscribeWorker(QThread):
    transcription_ready = Signal(str)

    def __init__(self, wav_bytes: bytes):
        super().__init__()
        self.wav_bytes = wav_bytes

    def run(self):
        try:
            rec = get_recognizer()
            text = rec.transcribe(self.wav_bytes)
            self.transcription_ready.emit(text or "")
        except Exception as e:
            logger.error(f"VoiceTranscribeWorker error: {e}", exc_info=True)
            self.transcription_ready.emit("")


class AurexMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AUREX • Voice Interaction System")
        self.resize(860, 560)
        self.setMinimumSize(640, 440)
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {AurexTheme.BG_DARK};
            }}
            {AurexTheme.get_main_stylesheet()}
        """)

        self.agent_worker = None
        self.transcribe_worker = None
        self.is_mic_held = False

        # Support backward-compatible test fixtures
        self.views_instances = {}
        self.views_classes = {
            "HOME": HomeView,
            "TASKS": TasksView,
            "LEARNING": LearningView,
            "MEMORY": MemoryView,
            "FILES": FilesView,
            "APPLICATIONS": AppsView,
            "SYSTEM": SystemView,
            "AUTOMATIONS": AutomationsView,
            "SETTINGS": SettingsView
        }

        # Wire up permission manager GUI callback
        get_permission_manager().set_confirmation_handler(self._on_confirmation_requested)

        self.init_ui()
        self.init_background_services()

        # Subscribe to agent state changes
        get_event_bus().subscribe("state_changed", self._on_state_changed)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(36, 28, 36, 28)
        main_layout.setSpacing(0)

        # Centered Voice Interaction Surface Card (Matches User Reference Image)
        self.surface_card = QFrame()
        self.surface_card.setObjectName("voiceSurfaceCard")
        self.surface_card.setStyleSheet(f"""
            QFrame#voiceSurfaceCard {{
                background-color: rgba(18, 24, 38, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 20px;
            }}
        """)

        card_layout = QVBoxLayout(self.surface_card)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(14)

        # 1. Header Section
        header_box = QVBoxLayout()
        header_box.setSpacing(4)

        title_lbl = QLabel("VOICE INTERACTION SURFACE")
        title_lbl.setStyleSheet("""
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 2px;
            color: #FFFFFF;
        """)
        header_box.addWidget(title_lbl)

        sub_lbl = QLabel("Inspired by sound waves and voice flow, creating a calm and responsive experience.")
        sub_lbl.setStyleSheet(f"""
            font-size: 12px;
            color: {AurexTheme.TEXT_SECONDARY};
        """)
        header_box.addWidget(sub_lbl)
        card_layout.addLayout(header_box)

        card_layout.addSpacing(6)

        # 2. Sound Wave Visualization Surface
        self.voice_wave = VoiceInteractionSurface()
        self.voice_wave.setFixedHeight(170)
        card_layout.addWidget(self.voice_wave)

        # 3. Live Status & Response Area
        status_box = QVBoxLayout()
        status_box.setSpacing(6)

        self.status_badge = QLabel("● Standing by")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setStyleSheet(f"""
            color: {AurexTheme.ACCENT_EMERALD};
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.5px;
        """)
        status_box.addWidget(self.status_badge)

        self.transcript_lbl = QLabel("")
        self.transcript_lbl.setAlignment(Qt.AlignCenter)
        self.transcript_lbl.setWordWrap(True)
        self.transcript_lbl.setStyleSheet(f"""
            color: {AurexTheme.TEXT_PRIMARY};
            font-size: 14px;
            font-weight: 500;
            padding: 4px 12px;
        """)
        status_box.addWidget(self.transcript_lbl)

        card_layout.addLayout(status_box)
        card_layout.addSpacing(8)

        # 4. Controls: Push-to-talk button & typed fallback
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(12)

        # Microphone Button
        self.btn_mic = QPushButton("🎙  Hold to Speak (or Spacebar)")
        self.btn_mic.setFixedHeight(44)
        self.btn_mic.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(236, 72, 153, 0.15);
                color: #F472B6;
                border: 1px solid rgba(236, 72, 153, 0.4);
                border-radius: 22px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: rgba(236, 72, 153, 0.28);
                border: 1px solid #EC4899;
                color: #FFFFFF;
            }}
            QPushButton:pressed {{
                background-color: #EC4899;
                color: #040810;
            }}
        """)
        self.btn_mic.pressed.connect(self._on_mic_pressed)
        self.btn_mic.released.connect(self._on_mic_released)
        ctrl_layout.addWidget(self.btn_mic, 2)

        # Quick typed command input
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Or type command... (e.g. 'Open Chrome', 'What's using CPU?')")
        self.input_field.setFixedHeight(44)
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background-color: {AurexTheme.BG_SURFACE};
                color: {AurexTheme.TEXT_PRIMARY};
                border: 1px solid {AurexTheme.BORDER_SUBTLE};
                border-radius: 22px;
                padding: 0 16px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1px solid {AurexTheme.ACCENT_CYAN};
            }}
        """)
        self.input_field.returnPressed.connect(self._on_submit_typed)
        ctrl_layout.addWidget(self.input_field, 3)

        self.btn_submit = QPushButton("➔")
        self.btn_submit.setFixedSize(44, 44)
        self.btn_submit.setStyleSheet(f"""
            QPushButton {{
                background-color: {AurexTheme.ACCENT_CYAN};
                color: #040810;
                border-radius: 22px;
                font-size: 16px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: #33ecff;
            }}
        """)
        self.btn_submit.clicked.connect(self._on_submit_typed)
        ctrl_layout.addWidget(self.btn_submit)

        card_layout.addLayout(ctrl_layout)

        main_layout.addWidget(self.surface_card)

        # Initialize default HOME instance for test compatibility
        self.views_instances["HOME"] = self.surface_card

    def init_background_services(self):
        scheduler = get_scheduler()
        scheduler.set_runner(self.execute_command)
        scheduler.start()
        scheduler.trigger_startup()

    def keyPressEvent(self, event):
        # Spacebar activates microphone unless user is actively typing in the text input
        if event.key() == Qt.Key_Space and not self.input_field.hasFocus():
            if not self.is_mic_held:
                self.is_mic_held = True
                self._on_mic_pressed()
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not self.input_field.hasFocus():
            if self.is_mic_held:
                self.is_mic_held = False
                self._on_mic_released()
                event.accept()
                return
        super().keyReleaseEvent(event)

    def _on_state_changed(self, state: AgentState):
        self.voice_wave.set_state(state)
        badges = {
            AgentState.IDLE: ("● Standing by", AurexTheme.ACCENT_EMERALD),
            AgentState.LISTENING: ("● Listening...", "#F472B6"),
            AgentState.THINKING: ("● Thinking & planning...", "#C084FC"),
            AgentState.EXECUTING: ("● Executing action...", "#FBBF24"),
            AgentState.SPEAKING: ("● Speaking...", "#38BDF8"),
            AgentState.ERROR: ("● Attention required", AurexTheme.ACCENT_ROSE)
        }
        text, color = badges.get(state, ("● Active", AurexTheme.ACCENT_CYAN))
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600;")

    def _on_submit_typed(self):
        text = self.input_field.text().strip()
        if text:
            self.input_field.clear()
            self.transcript_lbl.setText(f'"{text}"')
            self.execute_command(text)

    def execute_command(self, command_text: str):
        if not command_text.strip():
            return
        self.transcript_lbl.setText(f'"{command_text}"')
        self.agent_worker = AgentWorker(command_text)
        self.agent_worker.finished_signal.connect(self._on_agent_finished)
        self.agent_worker.start()

    def _on_agent_finished(self, response_text: str):
        self.transcript_lbl.setText(response_text)
        tts = get_tts()
        tts.speak(response_text)

    def _on_mic_pressed(self):
        self.btn_mic.setText("🎙  Listening...")
        self.btn_mic.setStyleSheet(f"""
            QPushButton {{
                background-color: #EC4899;
                color: #040810;
                border: 1px solid #EC4899;
                border-radius: 22px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: 700;
            }}
        """)
        mic = get_microphone()
        mic.start_push_to_talk()

    def _on_mic_released(self):
        self.btn_mic.setText("🎙  Hold to Speak (or Spacebar)")
        self.btn_mic.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(236, 72, 153, 0.15);
                color: #F472B6;
                border: 1px solid rgba(236, 72, 153, 0.4);
                border-radius: 22px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: rgba(236, 72, 153, 0.28);
                border: 1px solid #EC4899;
                color: #FFFFFF;
            }}
        """)
        mic = get_microphone()
        wav_bytes = mic.stop_push_to_talk()
        if wav_bytes:
            self.transcribe_worker = VoiceTranscribeWorker(wav_bytes)
            self.transcribe_worker.transcription_ready.connect(self._on_voice_transcribed)
            self.transcribe_worker.start()
        else:
            get_event_bus().publish("state_changed", state=AgentState.IDLE)
            self.status_badge.setText("● Standing by")

    def _on_voice_transcribed(self, text: str):
        if text and text.strip():
            self.transcript_lbl.setText(f'"{text}"')
            self.execute_command(text)
        else:
            get_event_bus().publish("state_changed", state=AgentState.IDLE)
            self.status_badge.setText("● Standing by")

    def _on_confirmation_requested(self, request: ActionRequest) -> bool:
        return show_confirmation_modal(request, parent=self)

    # Backward compatibility helpers for test suite
    def _on_navigate(self, section_name: str):
        # Hide previous secondary views
        for k, v in self.views_instances.items():
            if k != section_name and hasattr(v, "hide") and k != "HOME":
                v.hide()

        if section_name not in self.views_instances:
            cls = self.views_classes.get(section_name)
            if cls:
                self.views_instances[section_name] = cls()

        target = self.views_instances.get(section_name)
        if target and hasattr(target, "show") and section_name != "HOME":
            target.show()

    @property
    def tasks_view(self):
        if "TASKS" not in self.views_instances:
            self._on_navigate("TASKS")
        return self.views_instances.get("TASKS")

    @property
    def learning_view(self):
        if "LEARNING" not in self.views_instances:
            self._on_navigate("LEARNING")
        return self.views_instances.get("LEARNING")
