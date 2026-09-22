"""Memory manager for user preferences, task aliases, history, and activity logging."""

import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.memory.database import get_db

logger = logging.getLogger(__name__)


class MemoryManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MemoryManager, cls).__new__(cls)
            cls._instance.db = get_db()
        return cls._instance

    # Preferences
    def set_preference(self, key: str, value: Any):
        conn = self.db.get_connection()
        try:
            val_str = json.dumps(value) if not isinstance(value, str) else value
            with conn:
                conn.execute(
                    "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                    (key, val_str)
                )
        finally:
            conn.close()

    def get_preference(self, key: str, default: Any = None) -> Any:
        conn = self.db.get_connection()
        try:
            row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
            if row:
                raw = row["value"]
                try:
                    return json.loads(raw)
                except Exception:
                    return raw
            return default
        finally:
            conn.close()

    def list_preferences(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT key, value, updated_at FROM preferences ORDER BY key").fetchall()
            return [{"key": r["key"], "value": r["value"], "updated_at": r["updated_at"]} for r in rows]
        finally:
            conn.close()

    def delete_preference(self, key: str) -> bool:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
                return cur.rowcount > 0
        finally:
            conn.close()

    # Aliases
    def add_alias(self, alias_phrase: str, target_action: str):
        conn = self.db.get_connection()
        try:
            clean = alias_phrase.strip().lower()
            with conn:
                conn.execute(
                    "INSERT INTO aliases (alias_phrase, target_action) VALUES (?, ?) "
                    "ON CONFLICT(alias_phrase) DO UPDATE SET target_action=excluded.target_action",
                    (clean, target_action)
                )
        finally:
            conn.close()

    def resolve_alias(self, text: str) -> Optional[str]:
        clean = text.strip().lower()
        conn = self.db.get_connection()
        try:
            row = conn.execute("SELECT target_action FROM aliases WHERE alias_phrase = ?", (clean,)).fetchone()
            if row:
                return row["target_action"]
            return None
        finally:
            conn.close()

    def list_aliases(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT alias_phrase, target_action, created_at FROM aliases ORDER BY alias_phrase").fetchall()
            return [{"alias": r["alias_phrase"], "action": r["target_action"], "created_at": r["created_at"]} for r in rows]
        finally:
            conn.close()

    def delete_alias(self, alias_phrase: str) -> bool:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM aliases WHERE alias_phrase = ?", (alias_phrase.strip().lower(),))
                return cur.rowcount > 0
        finally:
            conn.close()

    # History
    def add_history(self, role: str, content: str):
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute("INSERT INTO conversation_history (role, content) VALUES (?, ?)", (role, content))
        finally:
            conn.close()

    def get_recent_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM conversation_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in reversed(rows)]
        finally:
            conn.close()

    def clear_history(self):
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM conversation_history")
        finally:
            conn.close()

    # Activities
    def log_activity(self, action_type: str, status: str, summary: str):
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO activity_log (action_type, status, summary) VALUES (?, ?, ?)",
                    (action_type, status, summary)
                )
        finally:
            conn.close()

    def get_recent_activities(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT action_type, status, summary, timestamp FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [{
                "action_type": r["action_type"],
                "status": r["status"],
                "summary": r["summary"],
                "timestamp": r["timestamp"]
            } for r in rows]
        finally:
            conn.close()

    # Automations
    def add_automation(self, title: str, schedule_type: str, schedule_val: str, action_command: str) -> int:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO automations (title, schedule_type, schedule_val, action_command) VALUES (?, ?, ?, ?)",
                    (title, schedule_type, schedule_val, action_command)
                )
                return cur.lastrowid
        finally:
            conn.close()

    def list_automations(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT id, title, schedule_type, schedule_val, action_command, enabled, created_at FROM automations ORDER BY id"
            ).fetchall()
            return [{
                "id": r["id"],
                "title": r["title"],
                "schedule_type": r["schedule_type"],
                "schedule_val": r["schedule_val"],
                "action_command": r["action_command"],
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"]
            } for r in rows]
        finally:
            conn.close()

    def toggle_automation(self, auto_id: int, enabled: bool):
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute("UPDATE automations SET enabled = ? WHERE id = ?", (1 if enabled else 0, auto_id))
        finally:
            conn.close()

    def delete_automation(self, auto_id: int) -> bool:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM automations WHERE id = ?", (auto_id,))
                return cur.rowcount > 0
        finally:
            conn.close()

    # Facts
    def add_fact(self, subject: str, predicate: str, obj: str, confidence: float = 0.8, source: str = "observed", why_learned: str = "") -> int:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO facts (subject, predicate, object, confidence, source, why_learned) VALUES (?, ?, ?, ?, ?, ?)",
                    (subject, predicate, obj, confidence, source, why_learned)
                )
                return cur.lastrowid
        finally:
            conn.close()

    def list_facts(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT id, subject, predicate, object, confidence, source, why_learned, created_at FROM facts ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_fact(self, fact_id: int) -> bool:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
                return cur.rowcount > 0
        finally:
            conn.close()

    # Behavior Events Telemetry
    def record_behavior_event(self, action_type: str, application: str = None, target_path: str = None, command: str = None, result_status: str = "SUCCESS"):
        now = datetime.now()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO behavior_events (action_type, application, target_path, command, result_status, hour_of_day, day_of_week) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (action_type, application, target_path, command, result_status, now.hour, now.weekday())
                )
        finally:
            conn.close()

    def get_recent_behavior_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT id, action_type, application, target_path, command, result_status, hour_of_day, day_of_week, timestamp "
                "FROM behavior_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # Habits
    def add_or_update_habit(self, habit_name: str, trigger_event: str, following_event: str, time_window: str = "", confidence: float = 0.1, why_learned: str = ""):
        conn = self.db.get_connection()
        try:
            with conn:
                row = conn.execute(
                    "SELECT id, frequency, confidence FROM habits WHERE habit_name = ?", (habit_name,)
                ).fetchone()
                if row:
                    new_freq = row["frequency"] + 1
                    new_conf = min(0.95, row["confidence"] + 0.05)
                    conn.execute(
                        "UPDATE habits SET frequency = ?, confidence = ?, time_window = ?, why_learned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_freq, new_conf, time_window, why_learned, row["id"])
                    )
                else:
                    conn.execute(
                        "INSERT INTO habits (habit_name, trigger_event, following_event, frequency, confidence, time_window, why_learned) "
                        "VALUES (?, ?, ?, 1, ?, ?, ?)",
                        (habit_name, trigger_event, following_event, confidence, time_window, why_learned)
                    )
        finally:
            conn.close()

    def list_habits(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT id, habit_name, trigger_event, following_event, frequency, confidence, time_window, why_learned, updated_at FROM habits ORDER BY confidence DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_habit(self, habit_id: int) -> bool:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
                return cur.rowcount > 0
        finally:
            conn.close()

    # Routines
    def add_or_update_routine(self, name: str, trigger_desc: str, action_sequence: List[str] | str, confidence: float = 0.1, status: str = "PROPOSED", why_learned: str = ""):
        seq_str = json.dumps(action_sequence) if isinstance(action_sequence, list) else action_sequence
        conn = self.db.get_connection()
        try:
            with conn:
                row = conn.execute("SELECT id, frequency, confidence FROM routines WHERE name = ?", (name,)).fetchone()
                if row:
                    new_freq = row["frequency"] + 1
                    new_conf = min(0.98, row["confidence"] + 0.05)
                    conn.execute(
                        "UPDATE routines SET trigger_desc = ?, action_sequence = ?, frequency = ?, confidence = ?, why_learned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (trigger_desc, seq_str, new_freq, new_conf, why_learned, row["id"])
                    )
                else:
                    conn.execute(
                        "INSERT INTO routines (name, trigger_desc, action_sequence, frequency, confidence, status, why_learned) "
                        "VALUES (?, ?, ?, 1, ?, ?, ?)",
                        (name, trigger_desc, seq_str, confidence, status, why_learned)
                    )
        finally:
            conn.close()

    def save_routine(
        self,
        name: str,
        trigger_desc: str = "",
        action_sequence: List[str] | str = None,
        confidence: float = 0.1,
        status: str = "PROPOSED",
        why_learned: str = "",
        **kwargs
    ):
        t_desc = trigger_desc or kwargs.get("trigger_type", "")
        seq = action_sequence or []
        return self.add_or_update_routine(
            name=name,
            trigger_desc=t_desc,
            action_sequence=seq,
            confidence=confidence,
            status=status,
            why_learned=why_learned
        )

    def list_routines(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            if status:
                rows = conn.execute("SELECT id, name, trigger_desc, action_sequence, frequency, confidence, status, why_learned, updated_at FROM routines WHERE status = ? ORDER BY confidence DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT id, name, trigger_desc, action_sequence, frequency, confidence, status, why_learned, updated_at FROM routines ORDER BY confidence DESC").fetchall()
            
            res = []
            for r in rows:
                item = dict(r)
                try:
                    item["actions"] = json.loads(item["action_sequence"])
                except Exception:
                    item["actions"] = [item["action_sequence"]]
                res.append(item)
            return res
        finally:
            conn.close()

    def set_routine_status(self, name: str, status: str) -> bool:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("UPDATE routines SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?", (status, name))
                return cur.rowcount > 0
        finally:
            conn.close()

    def delete_routine(self, name: str) -> bool:
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM routines WHERE name = ?", (name,))
                return cur.rowcount > 0
        finally:
            conn.close()

    # Location Mappings
    def set_location_mapping(self, natural_name: str, resolved_path: str, confidence: float = 0.5, why_learned: str = ""):
        clean_name = natural_name.strip().lower()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO location_mappings (natural_name, resolved_path, confidence, is_preferred, why_learned, updated_at) "
                    "VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(natural_name) DO UPDATE SET resolved_path=excluded.resolved_path, confidence=excluded.confidence, is_preferred=1, why_learned=excluded.why_learned, updated_at=CURRENT_TIMESTAMP",
                    (clean_name, resolved_path, confidence, why_learned)
                )
        finally:
            conn.close()

    def get_location_mapping(self, natural_name: str) -> Optional[str]:
        clean_name = natural_name.strip().lower()
        conn = self.db.get_connection()
        try:
            row = conn.execute("SELECT resolved_path FROM location_mappings WHERE natural_name = ? AND is_preferred = 1", (clean_name,)).fetchone()
            if row:
                return row["resolved_path"]
            return None
        finally:
            conn.close()

    def list_location_mappings(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT id, natural_name, resolved_path, confidence, is_preferred, why_learned, updated_at FROM location_mappings ORDER BY natural_name").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_location_mapping(self, natural_name: str) -> bool:
        clean_name = natural_name.strip().lower()
        conn = self.db.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM location_mappings WHERE natural_name = ?", (clean_name,))
                return cur.rowcount > 0
        finally:
            conn.close()

    # Corrections
    def record_correction(self, trigger_phrase: str, wrong_target: str, correct_target: str, confidence: float = 0.9):
        clean_phrase = trigger_phrase.strip().lower()
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO corrections (trigger_phrase, wrong_target, correct_target, confidence) VALUES (?, ?, ?, ?)",
                    (clean_phrase, wrong_target, correct_target, confidence)
                )
        finally:
            conn.close()

    def list_corrections(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute("SELECT id, trigger_phrase, wrong_target, correct_target, confidence, timestamp FROM corrections ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_memory_manager() -> MemoryManager:
    return MemoryManager()
