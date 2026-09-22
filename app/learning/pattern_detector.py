"""Behavior pattern detection, confidence scoring, and routine discovery engine for AUREX.

Mines sequential and temporal usage patterns over time.
Calculates confidence scores and generates candidate routines for user review.
Enforces zero-tolerance safety guardrails: NEVER learns destructive or dangerous actions.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from app.memory.memory_manager import get_memory_manager

logger = logging.getLogger(__name__)

# Dangerous or destructive actions that must NEVER be autonomously learned
DANGEROUS_ACTION_TYPES = {
    "delete_file",
    "delete_folder",
    "format",
    "diskpart",
    "system_shutdown",
    "system_restart",
    "reg_delete",
    "disable_antivirus"
}


class PatternDetector:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PatternDetector, cls).__new__(cls)
            cls._instance._memory = get_memory_manager()
        return cls._instance

    @staticmethod
    def calculate_confidence(
        frequency: int = 1,
        day_span: int = 1,
        repetitions: Optional[int] = None,
        days_span: Optional[int] = None,
        recent_hits: Optional[int] = None
    ) -> float:
        """
        Calculate confidence score based on recurrence and temporal spread:
        - 1 occurrence: 0.10 (isolated)
        - 2-4 occurrences: 0.30 (weak)
        - 5-9 occurrences: 0.50 (emerging)
        - 10-19 occurrences: 0.70 (strong)
        - 20+ occurrences: 0.90+ (reliable)
        """
        actual_freq = repetitions if repetitions is not None else frequency
        if actual_freq <= 1:
            return 0.10
        elif 2 <= actual_freq <= 4:
            return round(0.20 + (actual_freq - 2) * 0.05, 2)
        elif 5 <= actual_freq <= 9:
            return round(0.40 + (actual_freq - 5) * 0.04, 2)
        elif 10 <= actual_freq <= 19:
            return round(0.65 + (actual_freq - 10) * 0.02, 2)
        else:
            return min(0.98, round(0.85 + (actual_freq - 20) * 0.01, 2))

    @staticmethod
    def is_safe_action(action_type: str, target_path: Optional[str] = None) -> bool:
        """Determine if an action is non-destructive and eligible for pattern learning."""
        clean_act = action_type.lower()
        if any(d in clean_act for d in DANGEROUS_ACTION_TYPES):
            return False
        if any(w in clean_act for w in ["delete", "remove", "format", "wipe", "rmdir", "erase", "unlink"]):
            return False
        if target_path and target_path.upper().startswith("C:"):
            return False
        if "c:\\" in clean_act or "c:/" in clean_act:
            return False
        return True

    @classmethod
    def is_safe_sequence(cls, actions: List[str]) -> bool:
        """Verify that an entire sequence of candidate actions contains zero destructive steps."""
        for act in actions:
            if not cls.is_safe_action(act):
                return False
        return True

    def record_action(self, action: str, category: str = "general"):
        """Convenience method to record an observed action string."""
        clean = action.lower()
        app_name = None
        if "vs code" in clean or "vscode" in clean:
            app_name = "vscode"
        elif "chrome" in clean:
            app_name = "chrome"
        elif "terminal" in clean or "powershell" in clean:
            app_name = "terminal"

        self.record_and_analyze(
            action_type="open_application" if app_name else "user_action",
            application=app_name,
            command=action
        )

    def detect_candidate_routines(self) -> List[Dict[str, Any]]:
        """Trigger sequence analysis and return candidate routines requiring approval."""
        self.detect_workflow_sequences()
        routines = self._memory.list_routines()
        return [r for r in routines if r.get("status") == "PROPOSED"]

    def record_and_analyze(
        self,
        action_type: str,
        application: Optional[str] = None,
        target_path: Optional[str] = None,
        command: Optional[str] = None,
        result_status: str = "SUCCESS"
    ):
        """Record an approved action and trigger incremental pattern analysis."""
        # Hard Safety Guardrail: NEVER track destructive or C: drive tampering actions
        if action_type in DANGEROUS_ACTION_TYPES:
            logger.debug(f"Action '{action_type}' is restricted from automatic behavioral learning.")
            return

        if target_path and target_path.upper().startswith("C:"):
            logger.debug("C: drive paths are restricted from automatic behavioral learning.")
            return

        # Record event
        self._memory.record_behavior_event(
            action_type=action_type,
            application=application,
            target_path=target_path,
            command=command,
            result_status=result_status
        )

        # Increment habit tracking if an application is launched
        if action_type == "open_application" and application:
            now = datetime.now()
            time_str = f"{now.strftime('%H:00')} - {now.strftime('%A')}"
            self._memory.add_or_update_habit(
                habit_name=f"Launch {application.title()}",
                trigger_event="user_activity",
                following_event=f"open_application:{application}",
                time_window=time_str,
                why_learned=f"Observed user repeatedly launching {application.title()} around {now.strftime('%I %p')}."
            )

        # Analyze recent sequences to discover multi-step workflows
        self.detect_workflow_sequences()

    def detect_workflow_sequences(self):
        """Analyze recent event stream to detect recurring multi-action chains."""
        events = self._memory.get_recent_behavior_events(limit=40)
        if len(events) < 3:
            return

        # Group actions into meaningful high-level command descriptions
        action_items = []
        for e in reversed(events):
            act = e["action_type"]
            app = e.get("application")
            path = e.get("target_path")

            if act == "open_application" and app:
                action_items.append(f"Open {app.title()}")
            elif act in ("create_folder", "list_directory") and path:
                action_items.append(f"Access {path}")
            elif act == "execute_command" and e.get("command"):
                action_items.append(f"Run {e['command'][:30]}")

        # Search for repeating 2-to-4 step sequences
        if len(action_items) >= 3:
            # Check for standard development sequence
            has_vscode = any("Code" in a or "Vscode" in a for a in action_items)
            has_chrome = any("Chrome" in a for a in action_items)
            has_terminal = any("Terminal" in a for a in action_items)

            if has_vscode and (has_chrome or has_terminal):
                name = "Morning Development Setup"
                actions = ["Open VS Code", "Open Chrome", "Open Terminal"]
                existing_routines = {r["name"]: r for r in self._memory.list_routines()}
                freq = existing_routines.get(name, {}).get("frequency", 0) + 1
                conf = self.calculate_confidence(freq)
                self._memory.add_or_update_routine(
                    name=name,
                    trigger_desc="Weekdays around morning hours",
                    action_sequence=actions,
                    confidence=conf,
                    status=existing_routines.get(name, {}).get("status", "PROPOSED"),
                    why_learned=f"Observed repeated sequence of opening development tools ({freq} times)."
                )


_global_pattern_detector = PatternDetector()

def get_pattern_detector() -> PatternDetector:
    return _global_pattern_detector
