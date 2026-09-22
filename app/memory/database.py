"""SQLite persistent memory database connection and schema management for AUREX."""

import sqlite3
import os
import logging
from pathlib import Path
from typing import Optional
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._init_db()
        return cls._instance

    def _get_db_path(self) -> Path:
        settings = get_settings()
        root = Path(settings.workspace_root)
        mem_dir = root / "memory"
        try:
            mem_dir.mkdir(parents=True, exist_ok=True)
            return mem_dir / "aurex_memory.db"
        except Exception:
            # Fallback to local app directory
            local = Path(__file__).resolve().parent / "aurex_memory.db"
            return local

    def _init_db(self):
        db_path = self._get_db_path()
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Preferences table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Aliases table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aliases (
                    alias_phrase TEXT PRIMARY KEY,
                    target_action TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Conversation history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Activity log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Automations & scheduled triggers
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS automations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    schedule_val TEXT NOT NULL,
                    action_command TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Facts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence REAL DEFAULT 0.8,
                    source TEXT DEFAULT 'observed',
                    why_learned TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Habits table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS habits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    habit_name TEXT NOT NULL,
                    trigger_event TEXT NOT NULL,
                    following_event TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 0.1,
                    time_window TEXT,
                    why_learned TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Routines table (candidate & approved)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    trigger_desc TEXT,
                    action_sequence TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 0.1,
                    status TEXT DEFAULT 'PROPOSED',
                    why_learned TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Location mappings (e.g. "my OS project" -> "D:\OS")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS location_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    natural_name TEXT UNIQUE NOT NULL,
                    resolved_path TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    is_preferred INTEGER DEFAULT 1,
                    why_learned TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Corrections history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_phrase TEXT NOT NULL,
                    wrong_target TEXT NOT NULL,
                    correct_target TEXT NOT NULL,
                    confidence REAL DEFAULT 0.9,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Behavior events telemetry log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS behavior_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    application TEXT,
                    target_path TEXT,
                    command TEXT,
                    result_status TEXT,
                    hour_of_day INTEGER,
                    day_of_week INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Local Knowledge documentation index
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_docs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    summary TEXT,
                    content_chunks TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            conn.close()
            logger.info(f"Database initialized successfully at {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database at {db_path}: {e}")

    def get_connection(self) -> sqlite3.Connection:
        db_path = self._get_db_path()
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn


def get_db() -> Database:
    return Database()
