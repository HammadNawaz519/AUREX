"""Automation scheduler for recurring tasks and triggers in AUREX."""

import time
import threading
import logging
from datetime import datetime
from typing import Callable, Optional
from app.memory.memory_manager import get_memory_manager

logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(self, action_runner: Optional[Callable[[str], None]] = None):
        self._action_runner = action_runner
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_checked_minute = -1

    def set_runner(self, runner: Callable[[str], None]):
        self._action_runner = runner

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="AurexSchedulerThread")
        self._thread.start()
        logger.info("AUREX Task Scheduler started.")

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("AUREX Task Scheduler stopped.")

    def trigger_startup(self):
        """Execute automations configured to run on startup."""
        mm = get_memory_manager()
        automations = mm.list_automations()
        for a in automations:
            if a["enabled"] and a["schedule_type"].lower() == "startup":
                logger.info(f"Triggering startup automation: {a['title']}")
                if self._action_runner:
                    self._action_runner(a["action_command"])

    def _loop(self):
        while self._running:
            now = datetime.now()
            # Only evaluate once per minute
            if now.minute != self._last_checked_minute:
                self._last_checked_minute = now.minute
                time_str = now.strftime("%H:%M")

                mm = get_memory_manager()
                automations = mm.list_automations()
                for a in automations:
                    if not a["enabled"]:
                        continue

                    # Daily schedule match (e.g. "09:00")
                    if a["schedule_type"].lower() == "daily" and a["schedule_val"] == time_str:
                        logger.info(f"Triggering daily automation: {a['title']}")
                        if self._action_runner:
                            self._action_runner(a["action_command"])

            time.sleep(5)


_global_scheduler = TaskScheduler()

def get_scheduler() -> TaskScheduler:
    return _global_scheduler
