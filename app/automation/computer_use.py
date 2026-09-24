"""
Computer Use Service for AUREX.
Provides safe, element-aware mouse and keyboard control.
Preferred: find element by text/role, then click its live coordinates.
Never blindly clicks hardcoded coordinates.
"""
import logging
import time
import threading
from typing import Optional, Tuple, List
from app.vision.screen_model import UIElement, ScreenState

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()


class ComputerUseService:
    """
    Execute controlled UI interactions:
      - Click elements by semantic description
      - Type text into focused fields
      - Scroll pages
      - Keyboard shortcuts
      - Verify actions succeeded
    """

    def __init__(self):
        self._action_history: List[dict] = []
        self._pyautogui = None
        self._init_pyautogui()

    def _init_pyautogui(self):
        try:
            import pyautogui  # type: ignore
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.08
            self._pyautogui = pyautogui
            logger.info("ComputerUse: pyautogui initialized.")
        except Exception as e:
            logger.warning(f"ComputerUse: pyautogui unavailable: {e}")

    # ─── High-level Element-Aware Actions ──────────────────────────────────

    def click_element(self, element: UIElement, double: bool = False) -> bool:
        """Click a UIElement at its center coordinates."""
        x, y = element.center
        return self.click_at(x, y, double=double, label=element.text)

    def click_text(self, text: str, state: Optional[ScreenState] = None,
                   double: bool = False) -> bool:
        """
        Find a UI element matching `text` in state or by live capture,
        then click it.
        """
        if state:
            el = state.find_element(text=text)
            if el:
                return self.click_element(el, double=double)

        # Live capture fallback
        from app.vision.screen_understanding import get_screen_understanding_service
        el = get_screen_understanding_service().find_element_on_screen(text)
        if el:
            return self.click_element(el, double=double)

        logger.warning(f"click_text: could not find element with text '{text}'")
        return False

    def click_at(self, x: int, y: int, double: bool = False, label: str = "") -> bool:
        """Click at absolute screen coordinates."""
        if not self._pyautogui:
            return False
        with _LOCK:
            try:
                pg = self._pyautogui
                pg.moveTo(x, y, duration=0.12)
                if double:
                    pg.doubleClick(x, y)
                else:
                    pg.click(x, y)
                self._record_action("click", label or f"({x},{y})", (x, y))
                logger.debug(f"Clicked {'(double)' if double else ''} at ({x},{y}) - {label}")
                return True
            except Exception as e:
                logger.error(f"click_at failed: {e}")
                return False

    def right_click_element(self, element: UIElement) -> bool:
        x, y = element.center
        if not self._pyautogui:
            return False
        with _LOCK:
            try:
                self._pyautogui.rightClick(x, y)
                self._record_action("right_click", element.text, (x, y))
                return True
            except Exception as e:
                logger.error(f"right_click failed: {e}")
                return False

    def type_text(self, text: str, interval: float = 0.03) -> bool:
        """Type text into the currently focused input field."""
        if not self._pyautogui:
            return False
        with _LOCK:
            try:
                self._pyautogui.typewrite(text, interval=interval)
                self._record_action("type", text[:40], None)
                return True
            except Exception as e:
                logger.error(f"type_text failed: {e}")
                return False

    def type_into(self, text: str, element: UIElement) -> bool:
        """Click an input element then type text into it."""
        if not self.click_element(element):
            return False
        time.sleep(0.1)
        return self.type_text(text)

    def press_key(self, key: str) -> bool:
        """Press a keyboard key or hotkey combination (e.g. 'ctrl+c', 'enter', 'tab')."""
        if not self._pyautogui:
            return False
        with _LOCK:
            try:
                if "+" in key:
                    parts = [p.strip() for p in key.split("+")]
                    self._pyautogui.hotkey(*parts)
                else:
                    self._pyautogui.press(key)
                self._record_action("key", key, None)
                return True
            except Exception as e:
                logger.error(f"press_key '{key}' failed: {e}")
                return False

    def scroll(self, clicks: int = -3, x: int = None, y: int = None) -> bool:
        """
        Scroll up (positive) or down (negative).
        clicks: positive = scroll up, negative = scroll down.
        """
        if not self._pyautogui:
            return False
        with _LOCK:
            try:
                if x and y:
                    self._pyautogui.scroll(clicks, x=x, y=y)
                else:
                    self._pyautogui.scroll(clicks)
                self._record_action("scroll", f"{'up' if clicks > 0 else 'down'} {abs(clicks)}", None)
                return True
            except Exception as e:
                logger.error(f"scroll failed: {e}")
                return False

    def scroll_to_find(self, text: str, max_scrolls: int = 10,
                       direction: str = "down") -> Optional[UIElement]:
        """
        Scroll until an element with given text is found, or max_scrolls reached.
        Returns the UIElement if found, else None.
        """
        from app.vision.screen_understanding import get_screen_understanding_service
        svc = get_screen_understanding_service()
        clicks = -5 if direction == "down" else 5

        for i in range(max_scrolls):
            el = svc.find_element_on_screen(text)
            if el:
                return el
            self.scroll(clicks)
            time.sleep(0.4)

        return None

    def drag_element(self, from_el: UIElement, to_el: UIElement) -> bool:
        """Drag from one element to another."""
        if not self._pyautogui:
            return False
        with _LOCK:
            try:
                fx, fy = from_el.center
                tx, ty = to_el.center
                self._pyautogui.moveTo(fx, fy, duration=0.1)
                self._pyautogui.dragTo(tx, ty, duration=0.3, button="left")
                self._record_action("drag", f"{from_el.text} → {to_el.text}", None)
                return True
            except Exception as e:
                logger.error(f"drag_element failed: {e}")
                return False

    def screenshot_region(self, bounds: Tuple[int, int, int, int]):
        """Capture a specific screen region and return PIL Image."""
        from app.vision.screen_capture import get_screen_capture_service
        return get_screen_capture_service().capture(region=bounds)

    # ─── Action History ─────────────────────────────────────────────────────

    def _record_action(self, action_type: str, target: str, coords: Optional[Tuple]):
        self._action_history.append({
            "type": action_type,
            "target": target,
            "coords": coords,
            "time": time.time(),
        })
        # Keep last 100
        if len(self._action_history) > 100:
            self._action_history.pop(0)

    def get_last_actions(self, n: int = 5) -> List[dict]:
        return self._action_history[-n:]

    def undo_last(self) -> bool:
        """Attempt to undo last action via Ctrl+Z."""
        return self.press_key("ctrl+z")


_instance: Optional[ComputerUseService] = None

def get_computer_use_service() -> ComputerUseService:
    global _instance
    if _instance is None:
        _instance = ComputerUseService()
    return _instance
