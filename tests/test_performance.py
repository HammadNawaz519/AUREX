"""Performance and lifecycle verification tests for AUREX.

Asserts:
- Zero-CPU idle state (timer stopped when IDLE).
- Visibility-aware timer management (timers stopped when views are hidden).
- Instantaneous startup without premature background view allocation.
"""

import sys
import unittest
from PySide6.QtWidgets import QApplication
from app.ui.main_window import AurexMainWindow
from app.ui.voice_surface import VoiceInteractionSurface
from app.core.events import AgentState

# Ensure single QApplication instance
app = QApplication.instance() or QApplication(sys.argv)


class TestPerformanceAndLifecycle(unittest.TestCase):
    def test_voice_surface_zero_cpu_idle(self):
        surface = VoiceInteractionSurface()
        # Default state is IDLE
        self.assertEqual(surface.state, AgentState.IDLE)
        # Animation timer MUST be stopped when IDLE to guarantee 0% CPU consumption
        self.assertFalse(surface.anim_timer.isActive(), "Animation timer should be stopped when IDLE!")

        # Transition to active state: timer must start
        surface.set_state(AgentState.LISTENING)
        self.assertTrue(surface.anim_timer.isActive(), "Animation timer should be active during LISTENING!")

        # Transition back to IDLE: timer must stop immediately
        surface.set_state(AgentState.IDLE)
        self.assertFalse(surface.anim_timer.isActive(), "Animation timer must stop immediately when returning to IDLE!")

    def test_lazy_view_instantiation(self):
        window = AurexMainWindow()
        # Only HOME view should be instantiated at startup
        self.assertIn("HOME", window.views_instances)
        self.assertNotIn("SYSTEM", window.views_instances)
        self.assertNotIn("APPLICATIONS", window.views_instances)
        self.assertNotIn("MEMORY", window.views_instances)

        # Navigating to SYSTEM triggers lazy instantiation
        window._on_navigate("SYSTEM")
        self.assertIn("SYSTEM", window.views_instances)

        # Navigating to APPLICATIONS triggers lazy instantiation
        window._on_navigate("APPLICATIONS")
        self.assertIn("APPLICATIONS", window.views_instances)

    def test_system_view_timer_lifecycle(self):
        window = AurexMainWindow()
        window.show()

        # Navigate to SYSTEM
        window._on_navigate("SYSTEM")
        sys_view = window.views_instances["SYSTEM"]
        self.assertTrue(sys_view.timer.isActive(), "SystemView timer should be active while visible!")

        # Navigate away to HOME
        window._on_navigate("HOME")
        self.assertFalse(sys_view.timer.isActive(), "SystemView timer MUST stop when navigating away!")

    def test_apps_view_timer_lifecycle(self):
        window = AurexMainWindow()
        window.show()

        # Navigate to APPLICATIONS
        window._on_navigate("APPLICATIONS")
        apps_view = window.views_instances["APPLICATIONS"]
        self.assertTrue(apps_view.timer.isActive(), "AppsView timer should be active while visible!")

        # Navigate away to HOME
        window._on_navigate("HOME")
        self.assertFalse(apps_view.timer.isActive(), "AppsView timer MUST stop when navigating away!")


if __name__ == "__main__":
    unittest.main()
