"""
Screen Understanding Service for AUREX.
Orchestrates: Capture → Process → Detect → OCR → ScreenState.
Supports on-demand capture (task-triggered) and passive change-detection.
"""
import logging
import threading
import time
from typing import Optional, Callable

from app.vision.screen_model import ScreenState, UIElement
from app.vision.screen_capture import get_screen_capture_service
from app.vision.ui_detector import get_ui_detector
from app.vision.ocr_service import get_ocr_service

logger = logging.getLogger(__name__)


class ScreenUnderstandingService:
    """
    Unified screen perception pipeline:
      capture → UIA/OCR → structured ScreenState → agent
    """

    def __init__(self):
        self._capture = get_screen_capture_service()
        self._detector = get_ui_detector()
        self._ocr = get_ocr_service()

        self._active: bool = False          # screen-awareness ON/OFF
        self._current_state: Optional[ScreenState] = None
        self._state_lock = threading.Lock()

        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._state_callbacks: list = []

        # Privacy tracking
        self._local_only: bool = True       # default: do not send screenshots to cloud
        self._cloud_vision: bool = False

    # ─── Public API ────────────────────────────────────────────────────────

    def enable(self):
        """Enable screen awareness (user-initiated)."""
        self._active = True
        self._stop_event.clear()
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="aurex-screen-monitor"
            )
            self._monitor_thread.start()
        logger.info("Screen awareness ENABLED.")

    def disable(self):
        """Disable screen awareness."""
        self._active = False
        self._stop_event.set()
        logger.info("Screen awareness DISABLED.")

    @property
    def is_active(self) -> bool:
        return self._active

    def capture_now(self) -> Optional[ScreenState]:
        """
        On-demand: capture current screen and build ScreenState immediately.
        Used during active task execution.
        """
        return self._build_screen_state()

    def get_current_state(self) -> Optional[ScreenState]:
        with self._state_lock:
            return self._current_state

    def on_state_change(self, callback: Callable[[ScreenState], None]):
        """Register callback fired when screen changes significantly."""
        self._state_callbacks.append(callback)

    def capture_and_get_context(self) -> str:
        """Capture screen and return agent-ready text context string."""
        state = self.capture_now()
        if state:
            return state.to_agent_context()
        return "Screen capture unavailable."

    def scroll_and_read(self, direction: str = "down", max_scrolls: int = 8) -> str:
        """
        Scroll and continuously OCR the screen, merging text until no new content.
        Used for 'Read the assignment' type commands.
        """
        import pyautogui  # type: ignore
        collected_texts = []
        visited_hashes = set()

        for i in range(max_scrolls):
            state = self.capture_now()
            if state is None:
                break

            text = state.visible_text.strip()
            text_hash = hash(text[:500])

            if text_hash in visited_hashes:
                logger.debug(f"scroll_and_read: repeated content at scroll {i}, stopping.")
                break

            visited_hashes.add(text_hash)
            if text:
                collected_texts.append(text)

            # Scroll
            try:
                if direction == "down":
                    pyautogui.scroll(-5)
                else:
                    pyautogui.scroll(5)
                time.sleep(0.4)
            except Exception as e:
                logger.warning(f"Scroll failed: {e}")
                break

        return "\n---\n".join(collected_texts)

    def find_element_on_screen(self, text: str, etype: str = "") -> Optional[UIElement]:
        """Capture and find a UI element by text match."""
        state = self.capture_now()
        if state:
            return state.find_element(text=text, etype=etype)
        return None

    # ─── Privacy controls ──────────────────────────────────────────────────

    def set_cloud_vision(self, enabled: bool):
        self._cloud_vision = enabled
        logger.info(f"Cloud vision: {'ON' if enabled else 'OFF'}")

    @property
    def will_send_to_cloud(self) -> bool:
        return self._cloud_vision

    # ─── Internal ──────────────────────────────────────────────────────────

    def _build_screen_state(self) -> Optional[ScreenState]:
        """Full pipeline: capture → detect elements → OCR text → ScreenState."""
        try:
            capture_svc = self._capture
            img = capture_svc.capture()
            if img is None:
                return None

            hwnd = capture_svc.get_active_window_hwnd()
            title = capture_svc.get_active_window_title()
            w, h = capture_svc.get_screen_size()

            # Detect UI elements (UIA preferred, vision fallback)
            elements = self._detector.detect(image=img, hwnd=hwnd)

            # OCR full visible text
            visible_text = ""
            if self._ocr.available:
                try:
                    visible_text = self._ocr.extract_text(img)
                except Exception as e:
                    logger.warning(f"OCR failed in build: {e}")

            # Determine application name from window title
            app_name = self._parse_app_name(title)

            # Check if browser
            is_browser, browser_url = self._detect_browser_url(title, elements)

            state = ScreenState(
                application=app_name,
                window_title=title,
                elements=elements,
                visible_text=visible_text,
                screen_width=w,
                screen_height=h,
                is_browser=is_browser,
                browser_url=browser_url,
            )

            with self._state_lock:
                self._current_state = state

            return state

        except Exception as e:
            logger.error(f"Screen state build failed: {e}")
            return None

    def _parse_app_name(self, title: str) -> str:
        """Extract application name from window title."""
        if not title:
            return "Unknown"
        # Common patterns: "File - App" or "App"
        parts = title.split(" - ")
        if len(parts) >= 2:
            return parts[-1].strip()
        return title.strip()

    def _detect_browser_url(self, title: str, elements: list):
        """Detect if active window is a browser and try to find URL."""
        browsers = ["chrome", "firefox", "edge", "msedge", "safari", "opera", "brave"]
        title_lower = title.lower()
        is_browser = any(b in title_lower for b in browsers)

        # Try to find URL bar element
        url = ""
        if is_browser:
            for el in elements:
                if el.type in ("input", "text") and el.text.startswith(("http", "www.")):
                    url = el.text
                    break

        return is_browser, url

    def _monitor_loop(self):
        """Background loop: check for significant screen changes."""
        logger.debug("Screen monitor loop started.")
        while not self._stop_event.is_set():
            if not self._active:
                time.sleep(1.0)
                continue

            try:
                img = self._capture.capture()
                if img and self._capture.has_significant_change(img):
                    state = self._build_screen_state()
                    if state:
                        for cb in self._state_callbacks:
                            try:
                                cb(state)
                            except Exception:
                                pass
            except Exception as e:
                logger.debug(f"Monitor loop error: {e}")

            time.sleep(1.5)  # max ~0.67 fps passive monitoring — low CPU


_instance: Optional[ScreenUnderstandingService] = None

def get_screen_understanding_service() -> ScreenUnderstandingService:
    global _instance
    if _instance is None:
        _instance = ScreenUnderstandingService()
    return _instance
