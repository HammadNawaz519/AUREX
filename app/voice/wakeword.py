"""Wake phrase detection and stripping for AUREX."""

import re
from typing import Tuple
from app.config.settings import get_settings


class WakeWordDetector:
    @classmethod
    def check_and_strip(cls, text: str) -> Tuple[bool, str]:
        """
        Check if the text contains a wake word, and strip it off if present.
        Returns:
            (has_wake_word: bool, cleaned_prompt: str)
        """
        settings = get_settings()
        custom_wake = settings.wake_word.lower()

        clean = text.strip()
        # Patterns for Hey Aurex, Aurex, Hi Aurex, Ok Aurex, Jarvis
        patterns = [
            rf"^(?:hey|hi|hello|ok|okay)?\s*{re.escape(custom_wake)}[,\.\?!;:]*\s*",
            r"^(?:hey|hi|hello|ok|okay)?\s*aurex[,\.\?!;:]*\s*",
            r"^(?:hey|hi|hello|ok|okay)?\s*rex[,\.\?!;:]*\s*",
            r"^(?:hey|hi|hello|ok|okay)?\s*jarvis[,\.\?!;:]*\s*"
        ]

        for p in patterns:
            match = re.match(p, clean, re.IGNORECASE)
            if match:
                stripped = clean[match.end():].strip()
                return True, stripped

        return False, clean
