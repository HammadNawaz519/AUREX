"""Privacy-First AI Router and Cost Optimization Dispatcher for AUREX.

Determines whether a user request is resolved:
- LOCAL: 100% on-device (Zero API calls, Zero cloud transmission)
- GROQ: Cloud LLM reasoning for conceptual, coding, and synthesis queries
- INTERNET: Real-time external web search
- LOCAL_AND_GROQ: Local document excerpt + Groq explanation
- INTERNET_AND_GROQ: Local state comparison with live web data
"""

import re
import socket
import logging
from enum import Enum
from typing import Tuple, Dict, Any, Optional
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class RouteTarget(Enum):
    LOCAL = "LOCAL"
    GROQ = "GROQ"
    INTERNET = "INTERNET"
    LOCAL_AND_GROQ = "LOCAL_AND_GROQ"
    INTERNET_AND_GROQ = "INTERNET_AND_GROQ"


class AIRouter:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIRouter, cls).__new__(cls)
            cls._instance._is_online_cache: Optional[bool] = None
            cls._instance._last_online_check = 0.0
            cls._instance._online_override: Optional[bool] = None
        return cls._instance

    def set_online_override(self, online: Optional[bool]):
        """Override online connectivity detection (useful for testing or manual offline toggle)."""
        self._online_override = online

    def is_online(self) -> bool:
        """Lightweight connectivity probe (cached for 15 seconds)."""
        if self._online_override is not None:
            return self._online_override

        import time
        now = time.time()
        if self._is_online_cache is not None and (now - self._last_online_check) < 15.0:
            return self._is_online_cache

        s = None
        try:
            socket.setdefaulttimeout(1.5)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("1.1.1.1", 53))
            self._is_online_cache = True
        except Exception:
            # Fallback: check hostname resolution
            try:
                socket.gethostbyname("google.com")
                self._is_online_cache = True
            except Exception:
                self._is_online_cache = False
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

        self._last_online_check = now
        return self._is_online_cache

    def classify_request(self, user_text: str) -> Tuple[RouteTarget, Dict[str, Any]]:
        """
        Evaluate user request and determine the optimal, cost-efficient, and privacy-respecting route.
        """
        clean = user_text.lower().strip()
        from app.voice.wakeword import WakeWordDetector
        _, clean = WakeWordDetector.check_and_strip(clean)

        settings = get_settings()
        mode = settings.privacy_mode.lower()
        online = self.is_online()

        # 1. Privacy Mode Override: If PRIVATE, force 100% LOCAL
        if mode == "private" or not online:
            return RouteTarget.LOCAL, {
                "reason": "Forced LOCAL due to Private Mode or Offline status",
                "offline": not online
            }

        # 2. LOCAL ACTIONS (Cost Optimization: ZERO Cloud Calls)
        # Check system metrics (CPU, RAM, Disk, Process)
        if any(k in clean for k in ["cpu", "ram", "memory usage", "what's using cpu", "system info", "battery", "storage usage"]):
            return RouteTarget.LOCAL, {"category": "system_telemetry", "cost": "$0.00"}

        # Time, Date, Status, Greetings
        if any(k in clean for k in ["what time is it", "what's the time", "current time", "what date is it", "today's date", "who are you", "what can you do", "introduce yourself"]):
            return RouteTarget.LOCAL, {"category": "system_time_status", "cost": "$0.00"}

        # Desktop & Window management, volume
        if any(k in clean for k in ["minimize", "show desktop", "list windows", "open windows", "focus window", "mute", "unmute", "volume"]):
            return RouteTarget.LOCAL, {"category": "window_management", "cost": "$0.00"}

        # Application control (open, close, launch, switch, start, run)
        if re.match(r"^(?:open|launch|close|exit|quit|switch\s+to|start|run)\s+[a-zA-Z0-9_\-\.\s]+$", clean):
            # If not an explanatory request, keep 100% local
            if not any(k in clean for k in ["why", "how", "explain", "tutorial"]):
                return RouteTarget.LOCAL, {"category": "application_control", "cost": "$0.00"}

        # Workspace file & folder actions
        if re.match(r"^(?:create|make|delete|remove|list|show)\s+(?:a\s+)?(?:folder|file|directory)\b", clean):
            return RouteTarget.LOCAL, {"category": "workspace_filesystem", "cost": "$0.00"}

        # Screenshot
        if "screenshot" in clean:
            return RouteTarget.LOCAL, {"category": "screen_capture", "cost": "$0.00"}

        # Personal Context & Memory Queries
        if any(clean.startswith(p) for p in ["where do i keep", "where is my", "what is my preferred", "start my usual", "start work", "morning routine"]):
            return RouteTarget.LOCAL, {"category": "local_memory_retrieval", "cost": "$0.00"}

        # 3. INTERNET AND GROQ (Comparison / Hybrid Queries)
        if ("latest" in clean or "current version" in clean) and ("check" in clean or "my project" in clean):
            return RouteTarget.INTERNET_AND_GROQ, {"category": "local_web_comparison"}

        # 4. REAL-TIME INTERNET SEARCH
        realtime_keywords = ["weather", "latest news", "current stock", "latest version", "release notes for", "who won"]
        if any(k in clean for k in realtime_keywords) or clean.startswith(("search the web", "search for", "google ")):
            return RouteTarget.INTERNET, {"category": "web_search"}

        # 5. LOCAL FILE EXPLANATION (LOCAL + GROQ)
        if any(k in clean for k in ["explain this file", "summarize this folder", "read this document", "explain my project"]):
            return RouteTarget.LOCAL_AND_GROQ, {"category": "local_document_synthesis"}

        # 6. GENERAL REASONING & SYNTHESIS (GROQ)
        return RouteTarget.GROQ, {"category": "general_reasoning"}


_global_ai_router = AIRouter()

def get_ai_router() -> AIRouter:
    return _global_ai_router
