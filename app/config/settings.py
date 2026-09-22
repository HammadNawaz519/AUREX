"""Configuration management for AUREX."""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Dict[str, Any] = {
    "ai_provider": "groq",
    "groq_api_key": "",
    "groq_model": "openai/gpt-oss-120b",
    "openai_api_key": "",
    "openai_model": "gpt-4o",
    "gemini_api_key": "",
    "gemini_model": "gemini-1.5-flash",
    "claude_api_key": "",
    "claude_model": "claude-3-5-sonnet-20241022",
    "local_api_base": "http://localhost:11434/v1",
    "local_model": "llama3",
    "local_model_enabled": False,
    "privacy_mode": "balanced",  # "private" | "balanced" | "connected"
    "learning_enabled": True,
    "workspace_root": r"D:\AUREX",
    "allowed_directories": [
        r"D:\AUREX",
        r"D:\Projects",
        r"D:\OS",
        r"D:\Code"
    ],
    "knowledge_directories": [
        r"D:\AUREX\knowledge",
        r"D:\Projects"
    ],
    "voice_enabled": True,
    "wake_word": "Hey Aurex",
    "wake_word_enabled": True,
    "push_to_talk_key": "Space",
    "tts_voice": "en-US-JennyNeural",
    "tts_rate": "+0%",
    "tts_volume": "+0%",
    "startup_enabled": False,
    "theme": "dark",
    "log_level": "INFO",
    "confirmation_threshold": "CONFIRM"
}

class Settings:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_override: Dict[str, Any] = None):
        if self._initialized:
            if config_override:
                self._data.update(config_override)
            return

        self._data = dict(DEFAULT_CONFIG)
        self._load_from_env()
        self._setup_workspace_paths()
        self._load_from_file()
        if config_override:
            self._data.update(config_override)
        self._initialized = True

    def _load_from_env(self):
        """Load settings from environment variables if present."""
        project_root = Path(__file__).resolve().parent.parent.parent
        env_file = project_root / ".env"
        if env_file.exists():
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip()
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

        env_mappings = {
            "GROQ_API_KEY": "groq_api_key",
            "GROQ_MODEL": "groq_model",
            "OPENAI_API_KEY": "openai_api_key",
            "GEMINI_API_KEY": "gemini_api_key",
            "ANTHROPIC_API_KEY": "claude_api_key",
            "LOCAL_API_BASE": "local_api_base",
            "AUREX_WORKSPACE_ROOT": "workspace_root",
            "WAKE_WORD": "wake_word",
            "TTS_VOICE": "tts_voice"
        }
        for env_var, key in env_mappings.items():
            val = os.environ.get(env_var)
            if val:
                self._data[key] = val

        allowed = os.environ.get("AUREX_ALLOWED_DIRS")
        if allowed:
            dirs = [d.strip() for d in allowed.split(";") if d.strip()]
            for d in dirs:
                if d not in self._data["allowed_directories"]:
                    self._data["allowed_directories"].append(d)

    def _setup_workspace_paths(self):
        """Ensure standard folders exist under the workspace root."""
        root = Path(self.workspace_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
            for sub in ["workspace", "downloads", "generated", "logs", "memory", "screenshots", "temp", "config", "knowledge"]:
                (root / sub).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create default workspace root {root}: {e}")

    @property
    def config_path(self) -> Path:
        root = Path(self.workspace_root)
        config_dir = root / "config"
        if not config_dir.exists():
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                # Fallback to local app config if root not writable
                return Path(__file__).resolve().parent / "config.json"
        return config_dir / "config.json"

    def _load_from_file(self):
        """Load persistent config from config.json."""
        path = self.config_path
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._data.update(saved)
            except Exception as e:
                logger.error(f"Failed to load config from {path}: {e}")

    def save(self):
        """Save settings to config.json."""
        path = self.config_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Never save empty placeholder if we have default key
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config to {path}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any, auto_save: bool = True):
        self._data[key] = value
        if auto_save:
            self.save()

    @property
    def ai_provider(self) -> str:
        return self._data.get("ai_provider", "groq")

    @property
    def groq_api_key(self) -> str:
        return self._data.get("groq_api_key", "")

    @property
    def groq_model(self) -> str:
        return self._data.get("groq_model", "openai/gpt-oss-120b")

    @property
    def workspace_root(self) -> str:
        return self._data.get("workspace_root", r"D:\AUREX")

    @property
    def allowed_directories(self) -> List[str]:
        return self._data.get("allowed_directories", [r"D:\AUREX"])

    @property
    def wake_word(self) -> str:
        return self._data.get("wake_word", "Hey Aurex")

    @property
    def tts_voice(self) -> str:
        return self._data.get("tts_voice", "en-US-JennyNeural")

    @property
    def startup_enabled(self) -> bool:
        return bool(self._data.get("startup_enabled", False))

    @property
    def privacy_mode(self) -> str:
        return self._data.get("privacy_mode", "balanced")

    @property
    def local_model_enabled(self) -> bool:
        return bool(self._data.get("local_model_enabled", False))

    @property
    def learning_enabled(self) -> bool:
        return bool(self._data.get("learning_enabled", True))

    @property
    def knowledge_directories(self) -> List[str]:
        return self._data.get("knowledge_directories", [r"D:\AUREX\knowledge", r"D:\Projects"])

    def add_allowed_directory(self, path_str: str) -> bool:
        norm = os.path.normpath(path_str)
        if norm not in [os.path.normpath(d) for d in self.allowed_directories]:
            self._data["allowed_directories"].append(norm)
            self.save()
            return True
        return False

    def remove_allowed_directory(self, path_str: str) -> bool:
        norm = os.path.normpath(path_str)
        curr = [os.path.normpath(d) for d in self.allowed_directories]
        if norm in curr:
            idx = curr.index(norm)
            # Cannot remove primary workspace root
            if os.path.normpath(self.workspace_root) == norm:
                return False
            del self._data["allowed_directories"][idx]
            self.save()
            return True
        return False


def get_settings() -> Settings:
    return Settings()
