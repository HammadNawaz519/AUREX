"""Correction and explicit preference learning engine for AUREX.

Detects user corrections ("No, I mean D:\OS", "No, use Firefox") and explicit preferences,
immediately adjusting semantic mappings and local memory to prevent repeating mistakes.
"""

import re
import logging
from typing import Tuple, Optional
from app.memory.memory_manager import get_memory_manager
from app.core.context import get_context

logger = logging.getLogger(__name__)


class CorrectionLearner:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CorrectionLearner, cls).__new__(cls)
            cls._instance._memory = get_memory_manager()
            cls._instance._context = get_context()
        return cls._instance

    def inspect_for_correction(self, user_text: str) -> Tuple[bool, Optional[str]]:
        """
        Inspect whether the user input is correcting AUREX's previous turn.
        Returns:
            (is_correction: bool, feedback_message: Optional[str])
        """
        clean = user_text.strip()
        clean_lower = clean.lower()

        # 1. Check for folder/path correction (e.g. "No, I mean D:\OS", "Wrong folder, use D:\OS")
        path_match = re.search(
            r"(?:no|wrong|nope|actually|not\s+that)[,\.\s]+(?:i\s+mean|use|it's|open|go\s+to)?\s*([a-zA-Z]:\\[^\s\"']+)",
            clean,
            re.IGNORECASE
        )
        if path_match:
            correct_path = path_match.group(1).rstrip("\\")
            # Retrieve what previous turn was about
            prev_turn = self._context.turns[-1] if self._context.turns else None
            trigger_topic = "my project"
            wrong_target = "default"

            if prev_turn:
                # Extract key phrases from previous user input (e.g. "my OS project")
                match_phrase = re.search(r"(?:open|find|show)\s+(.+)", prev_turn.user_input, re.IGNORECASE)
                if match_phrase:
                    trigger_topic = match_phrase.group(1).strip()
                if prev_turn.tool_data:
                    wrong_target = str(prev_turn.tool_data)

            # Record correction and update location mapping
            self._memory.set_location_mapping(
                natural_name=trigger_topic,
                resolved_path=correct_path,
                confidence=0.95,
                why_learned=f"User corrected: '{clean}'"
            )
            self._memory.record_correction(
                trigger_phrase=trigger_topic,
                wrong_target=wrong_target,
                correct_target=correct_path,
                confidence=0.95
            )
            logger.info(f"Learned correction: '{trigger_topic}' -> '{correct_path}'")
            return True, f"Understood. I have updated my memory: '{trigger_topic}' now maps to {correct_path}."

        # 2. Check for application preference correction (e.g. "No, use Firefox", "I prefer VS Code")
        app_match = re.search(
            r"(?:no|wrong|nope)[,\.\s]+use\s+(chrome|firefox|code|vscode|vs\s+code|edge|spotify)",
            clean_lower
        )
        if app_match:
            app_name = app_match.group(1)
            self._memory.set_preference("preferred_browser" if "fox" in app_name or "chrome" in app_name else "preferred_app", app_name)
            self._memory.add_fact("user", "prefers_application", app_name, confidence=0.95, why_learned=f"User correction: '{clean}'")
            return True, f"Got it. I have saved your preference to use {app_name.title()}."

        # 3. Explicit preference statement (e.g. "I prefer VS Code", "I use Firefox", "My projects are on D drive")
        if re.search(r"\bi\s+(?:prefer|always\s+use)\s+([a-zA-Z0-9_\s]+)", clean_lower):
            pref_val = re.search(r"\bi\s+(?:prefer|always\s+use)\s+([a-zA-Z0-9_\s]+)", clean, re.IGNORECASE).group(1).strip()
            self._memory.set_preference("user_preference", pref_val)
            self._memory.add_fact("user", "preference", pref_val, confidence=0.95, why_learned="Explicit user preference")
            return True, f"Recorded preference: You prefer {pref_val}."

        return False, None


_global_correction_learner = CorrectionLearner()

def get_correction_learner() -> CorrectionLearner:
    return _global_correction_learner
