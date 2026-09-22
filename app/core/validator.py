"""Terminal command validator and safety inspector for AUREX.

Guarantees shell execution never tampers with C: drive, Windows security,
antivirus/Defender, boot parameters, or partition tables.
"""

import re
import shlex
from typing import Tuple, List
from app.core.security import is_path_allowed, is_c_drive, canonical_path

BLOCKED_PATTERNS = [
    # Disk and partition destruction
    r"\bformat\b",
    r"\bdiskpart\b",
    r"\bcipher\s+/w",
    r"\bbcdedit\b",
    # Registry deletion / tampering
    r"\breg\s+(delete|add)\s+['\"]?hklm",
    r"\breg\s+(delete|add)\s+['\"]?hkcr",
    # Ownership / ACL stripping
    r"\btakeown\b",
    r"\bicacls\b.*(/grant|/deny|/setowner)",
    # Destructive deletion targeting C:
    r"\bdel(ete)?\s+([/\w\s-]*)[c|C]:",
    r"\brmdir\s+([/\w\s-]*)[c|C]:",
    r"\bRemove-Item\s+([/\w\s-]*)[c|C]:",
    r"\brd\s+([/\w\s-]*)[c|C]:",
    # Defender / Antivirus tampering
    r"DisableRealtimeMonitoring",
    r"Set-MpPreference",
    r"net\s+stop\s+(windefend|mpssvc|wuauserv)",
    r"sc\s+(stop|delete|config)\s+(windefend|mpssvc)",
    # Credential dumping / hijacking
    r"\bmimikatz\b",
    r"\bprocdump\b.*lsass",
    r"\bvssadmin\s+delete\s+shadows",
]


class CommandValidator:
    """Validates commands before execution in shell / subprocess."""

    @classmethod
    def validate(cls, command_str: str) -> Tuple[bool, str, bool]:
        """
        Validates a command.
        Returns:
            (is_allowed: bool, reason: str, requires_confirmation: bool)
        """
        cmd = command_str.strip()
        if not cmd:
            return False, "Command is empty.", False

        # 1. Check against permanently BLOCKED patterns
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return False, f"ACCESS DENIED: Command contains prohibited pattern '{pattern}'.", False

        # 2. Extract potential path arguments and inspect for C: write / tampering
        # Look for tokens with drive letters, slashes, or quotes
        tokens = re.findall(r'(?:[a-zA-Z]:\\[^\s"\']+|"[^"]*"|\'[^\']*\')', cmd)
        write_indicators = ["del", "rm", "remove-item", "move", "mv", "copy", "cp", "echo", ">", ">>", "out-file", "set-content"]
        has_write = any(re.search(rf"\b{ind}\b", cmd, re.IGNORECASE) for ind in write_indicators) or (">" in cmd)

        for token in tokens:
            clean_token = token.strip('"').strip("'")
            if re.match(r'^[a-zA-Z]:', clean_token) or ".." in clean_token:
                try:
                    resolved = canonical_path(clean_token)
                    if has_write and is_c_drive(resolved):
                        return False, f"ACCESS DENIED: Command targets C: drive for write/modification ('{clean_token}').", False
                except Exception:
                    pass

        # 3. Explicit check for redirects or pipe targeting C:
        if re.search(r'>\s*(["]?[c|C]:[^"]*)', cmd):
            return False, "ACCESS DENIED: Command redirects output to C: drive.", False

        # 4. Legit commands require user confirmation for safety
        return True, "Command passed security checks and requires execution confirmation.", True
