"""Settings view for configuring AI providers, API keys, workspaces, and startup behavior."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QFrame, QListWidget,
    QFileDialog, QMessageBox, QScrollArea
)
from PySide6.QtCore import Qt
from app.config.settings import get_settings
from app.ai import get_ai_provider
from app.voice.tts import get_tts
from app.ui.themes import AurexTheme


class SettingsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = get_settings()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(16)

        # Header
        top_row = QHBoxLayout()
        header = QLabel("AUREX System Configuration")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        top_row.addWidget(header)
        top_row.addStretch()

        btn_save = QPushButton("Save Changes")
        btn_save.setObjectName("primaryButton")
        btn_save.clicked.connect(self.save_settings)
        top_row.addWidget(btn_save)
        main_layout.addLayout(top_row)

        # Scroll area for clean settings layout
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: transparent; border: none;")

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(20)

        # 1. AI Provider Section
        ai_card = QFrame()
        ai_card.setObjectName("cardFrame")
        ai_layout = QVBoxLayout(ai_card)
        ai_layout.setContentsMargins(18, 18, 18, 18)
        ai_layout.setSpacing(12)

        ai_title = QLabel("AI Engine & LLM Provider")
        ai_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        ai_layout.addWidget(ai_title)

        # Provider Selector
        prov_row = QHBoxLayout()
        prov_lbl = QLabel("Active Provider:")
        prov_lbl.setFixedWidth(130)
        self.cb_provider = QComboBox()
        self.cb_provider.addItems(["groq", "openai", "gemini", "claude", "local"])
        self.cb_provider.setCurrentText(self.settings.ai_provider)
        self.cb_provider.setStyleSheet(f"background-color: {AurexTheme.BG_SURFACE}; padding: 6px;")
        prov_row.addWidget(prov_lbl)
        prov_row.addWidget(self.cb_provider, 1)
        ai_layout.addLayout(prov_row)

        # Groq API Key
        groq_row = QHBoxLayout()
        groq_lbl = QLabel("Groq API Key:")
        groq_lbl.setFixedWidth(130)
        self.in_groq_key = QLineEdit(self.settings.groq_api_key)
        self.in_groq_key.setEchoMode(QLineEdit.Password)
        btn_toggle_key = QPushButton("👁")
        btn_toggle_key.setFixedWidth(36)
        btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        btn_test_groq = QPushButton("Test Connection")
        btn_test_groq.clicked.connect(self._test_groq)

        groq_row.addWidget(groq_lbl)
        groq_row.addWidget(self.in_groq_key, 1)
        groq_row.addWidget(btn_toggle_key)
        groq_row.addWidget(btn_test_groq)
        ai_layout.addLayout(groq_row)

        # Groq Model
        model_row = QHBoxLayout()
        model_lbl = QLabel("Groq Model:")
        model_lbl.setFixedWidth(130)
        self.in_groq_model = QLineEdit(self.settings.groq_model)
        model_row.addWidget(model_lbl)
        model_row.addWidget(self.in_groq_model, 1)
        ai_layout.addLayout(model_row)

        c_layout.addWidget(ai_card)

        # 2. Privacy & Local-First Intelligence Section
        priv_card = QFrame()
        priv_card.setObjectName("cardFrame")
        priv_layout = QVBoxLayout(priv_card)
        priv_layout.setContentsMargins(18, 18, 18, 18)
        priv_layout.setSpacing(12)

        priv_title = QLabel("🔒  Privacy & Local-First Intelligence")
        priv_title.setStyleSheet("font-size: 15px; font-weight: 700; color: " + AurexTheme.ACCENT_CYAN + ";")
        priv_layout.addWidget(priv_title)

        # Privacy Mode Selector
        pm_row = QHBoxLayout()
        pm_lbl = QLabel("Privacy Mode:")
        pm_lbl.setFixedWidth(130)
        self.cb_privacy_mode = QComboBox()
        self.cb_privacy_mode.addItems(["balanced", "private", "connected"])
        self.cb_privacy_mode.setCurrentText(self.settings.privacy_mode)
        self.cb_privacy_mode.setStyleSheet(f"background-color: {AurexTheme.BG_SURFACE}; padding: 6px;")
        pm_row.addWidget(pm_lbl)
        pm_row.addWidget(self.cb_privacy_mode, 1)
        priv_layout.addLayout(pm_row)

        pm_desc = QLabel(
            "• balanced: Zero cloud calls for local tasks, apps, and files. Groq used only for complex reasoning.\n"
            "• private: 100% Offline. Zero external cloud requests or API calls.\n"
            "• connected: Local intelligence + Groq + full web searches allowed."
        )
        pm_desc.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-size: 11px;")
        priv_layout.addWidget(pm_desc)

        # Checkboxes for learning and local model
        self.chk_learning = QCheckBox("Enable Continuous Learning & Pattern Detection")
        self.chk_learning.setChecked(self.settings.learning_enabled)
        priv_layout.addWidget(self.chk_learning)

        self.chk_local_model = QCheckBox("Enable Local LLM Support (Ollama / offline small model)")
        self.chk_local_model.setChecked(self.settings.local_model_enabled)
        priv_layout.addWidget(self.chk_local_model)

        # Knowledge Directories
        kdirs_lbl = QLabel("Knowledge Indexing Directories (Locally indexed for semantic search):")
        kdirs_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-size: 12px; font-weight: 600; margin-top: 6px;")
        priv_layout.addWidget(kdirs_lbl)

        self.kdirs_list = QListWidget()
        self.kdirs_list.setFixedHeight(85)
        for kd in self.settings.knowledge_directories:
            self.kdirs_list.addItem(kd)
        priv_layout.addWidget(self.kdirs_list)

        kdir_btn_box = QHBoxLayout()
        btn_add_kdir = QPushButton("+ Add Knowledge Dir")
        btn_add_kdir.clicked.connect(self._add_knowledge_directory)
        btn_rem_kdir = QPushButton("- Remove Selected")
        btn_rem_kdir.setObjectName("dangerButton")
        btn_rem_kdir.clicked.connect(self._remove_knowledge_directory)
        btn_reindex = QPushButton("⚡ Index Now")
        btn_reindex.clicked.connect(self._reindex_knowledge)
        kdir_btn_box.addWidget(btn_add_kdir)
        kdir_btn_box.addWidget(btn_rem_kdir)
        kdir_btn_box.addWidget(btn_reindex)
        kdir_btn_box.addStretch()
        priv_layout.addLayout(kdir_btn_box)

        c_layout.addWidget(priv_card)

        # 2. Workspace & Allowed Directories Section
        ws_card = QFrame()
        ws_card.setObjectName("cardFrame")
        ws_layout = QVBoxLayout(ws_card)
        ws_layout.setContentsMargins(18, 18, 18, 18)
        ws_layout.setSpacing(12)

        ws_title = QLabel("Approved Filesystem Workspace (C: Drive is Hard Protected)")
        ws_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        ws_layout.addWidget(ws_title)

        ws_row = QHBoxLayout()
        ws_lbl = QLabel("Primary Workspace:")
        ws_lbl.setFixedWidth(130)
        self.in_ws_root = QLineEdit(self.settings.workspace_root)
        ws_row.addWidget(ws_lbl)
        ws_row.addWidget(self.in_ws_root, 1)
        ws_layout.addLayout(ws_row)

        dirs_lbl = QLabel("Approved Write Locations (Modifications outside these paths are rejected):")
        dirs_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-size: 12px;")
        ws_layout.addWidget(dirs_lbl)

        self.dirs_list = QListWidget()
        self.dirs_list.setFixedHeight(100)
        for d in self.settings.allowed_directories:
            self.dirs_list.addItem(d)
        ws_layout.addWidget(self.dirs_list)

        dir_btn_box = QHBoxLayout()
        btn_add_dir = QPushButton("+ Add Directory")
        btn_add_dir.clicked.connect(self._add_allowed_directory)
        btn_rem_dir = QPushButton("- Remove Selected")
        btn_rem_dir.setObjectName("dangerButton")
        btn_rem_dir.clicked.connect(self._remove_allowed_directory)
        dir_btn_box.addWidget(btn_add_dir)
        dir_btn_box.addWidget(btn_rem_dir)
        dir_btn_box.addStretch()
        ws_layout.addLayout(dir_btn_box)

        c_layout.addWidget(ws_card)

        # 3. Voice & Speech Section
        voice_card = QFrame()
        voice_card.setObjectName("cardFrame")
        v_layout = QVBoxLayout(voice_card)
        v_layout.setContentsMargins(18, 18, 18, 18)
        v_layout.setSpacing(12)

        v_title = QLabel("Voice & Natural Speech Settings")
        v_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        v_layout.addWidget(v_title)

        wake_row = QHBoxLayout()
        wake_lbl = QLabel("Wake Phrase:")
        wake_lbl.setFixedWidth(130)
        self.in_wake = QLineEdit(self.settings.wake_word)
        wake_row.addWidget(wake_lbl)
        wake_row.addWidget(self.in_wake, 1)
        v_layout.addLayout(wake_row)

        tts_row = QHBoxLayout()
        tts_lbl = QLabel("TTS Voice:")
        tts_lbl.setFixedWidth(130)
        self.cb_voice = QComboBox()
        self.cb_voice.addItems([
            "en-US-JennyNeural",
            "en-US-GuyNeural",
            "en-US-AriaNeural",
            "en-GB-SoniaNeural",
            "en-AU-NatashaNeural"
        ])
        self.cb_voice.setCurrentText(self.settings.tts_voice)
        self.cb_voice.setStyleSheet(f"background-color: {AurexTheme.BG_SURFACE}; padding: 6px;")
        btn_test_voice = QPushButton("Test Voice")
        btn_test_voice.clicked.connect(self._test_voice)
        tts_row.addWidget(tts_lbl)
        tts_row.addWidget(self.cb_voice, 1)
        tts_row.addWidget(btn_test_voice)
        v_layout.addLayout(tts_row)

        c_layout.addWidget(voice_card)

        # 4. Windows Startup
        start_card = QFrame()
        start_card.setObjectName("cardFrame")
        s_layout = QVBoxLayout(start_card)
        s_layout.setContentsMargins(18, 18, 18, 18)

        self.chk_startup = QCheckBox("Launch AUREX automatically when Windows starts (User Registry Run key)")
        self.chk_startup.setChecked(self.settings.startup_enabled)
        self.chk_startup.setStyleSheet("font-size: 13px; font-weight: 500;")
        s_layout.addWidget(self.chk_startup)

        c_layout.addWidget(start_card)

        scroll.setWidget(container)
        main_layout.addWidget(scroll, 1)

    def _toggle_key_visibility(self):
        if self.in_groq_key.echoMode() == QLineEdit.Password:
            self.in_groq_key.setEchoMode(QLineEdit.Normal)
        else:
            self.in_groq_key.setEchoMode(QLineEdit.Password)

    def _test_groq(self):
        key = self.in_groq_key.text().strip()
        from app.ai.groq_provider import GroqProvider
        provider = GroqProvider(api_key=key)
        if provider.health_check():
            QMessageBox.information(self, "Groq Connection", "Connection successful! Groq API is active.")
        else:
            QMessageBox.warning(self, "Groq Connection", "Could not connect to Groq with the provided key.")

    def _test_voice(self):
        tts = get_tts()
        tts.speak("AUREX voice output system online. Standing by.")

    def _add_allowed_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Approved Directory")
        if dir_path:
            # Check C: drive protection
            if dir_path.upper().startswith("C:"):
                QMessageBox.warning(self, "Security Policy", "ACCESS DENIED: The C: drive cannot be added to allowed write directories.")
                return
            self.dirs_list.addItem(dir_path)

    def _remove_allowed_directory(self):
        row = self.dirs_list.currentRow()
        if row >= 0:
            item = self.dirs_list.takeItem(row)
            del item

    def _add_knowledge_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Knowledge Indexing Directory")
        if dir_path:
            self.kdirs_list.addItem(dir_path)

    def _remove_knowledge_directory(self):
        row = self.kdirs_list.currentRow()
        if row >= 0:
            item = self.kdirs_list.takeItem(row)
            del item

    def _reindex_knowledge(self):
        try:
            from app.knowledge.indexer import get_indexer
            indexer = get_indexer()
            count = indexer.index_all()
            QMessageBox.information(
                self,
                "Knowledge Base Indexing",
                f"Successfully indexed {count} local documents and code files into AUREX semantic memory."
            )
        except Exception as e:
            QMessageBox.critical(self, "Indexing Error", f"Error indexing documents: {e}")

    def save_settings(self):
        self.settings.set("ai_provider", self.cb_provider.currentText())
        self.settings.set("groq_api_key", self.in_groq_key.text().strip())
        self.settings.set("groq_model", self.in_groq_model.text().strip())
        self.settings.set("workspace_root", self.in_ws_root.text().strip())
        self.settings.set("wake_word", self.in_wake.text().strip())
        self.settings.set("tts_voice", self.cb_voice.currentText())

        # Privacy and learning settings
        self.settings.set("privacy_mode", self.cb_privacy_mode.currentText())
        self.settings.set("learning_enabled", self.chk_learning.isChecked())
        self.settings.set("local_model_enabled", self.chk_local_model.isChecked())

        kdirs = [self.kdirs_list.item(i).text() for i in range(self.kdirs_list.count())]
        self.settings.set("knowledge_directories", kdirs)

        dirs = [self.dirs_list.item(i).text() for i in range(self.dirs_list.count())]
        self.settings.set("allowed_directories", dirs)

        startup = self.chk_startup.isChecked()
        self.settings.set("startup_enabled", startup)

        # Update Windows Registry Run key
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as reg_key:
                if startup:
                    import sys
                    from pathlib import Path
                    bat_path = Path(__file__).resolve().parent.parent.parent.parent / "run_aurex.bat"
                    winreg.SetValueEx(reg_key, "AUREX_Assistant", 0, winreg.REG_SZ, str(bat_path))
                else:
                    try:
                        winreg.DeleteValue(reg_key, "AUREX_Assistant")
                    except Exception:
                        pass
        except Exception:
            pass

        QMessageBox.information(self, "Settings Saved", "AUREX configuration has been updated successfully.")
