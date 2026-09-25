"""
UI Element Detector for AUREX.
Priority: Windows UI Automation > Browser DOM > Visual OCR
Produces a list of UIElement objects representing the current screen.
"""
import logging
import re
from typing import List, Optional, Tuple
from PIL import Image
from app.vision.screen_model import UIElement

logger = logging.getLogger(__name__)


class UIDetector:
    """Detects UI elements using UIA, browser DOM, and visual/OCR fallback."""

    # ─── Windows UI Automation ──────────────────────────────────────────────

    def detect_via_uia(self, hwnd: Optional[int] = None) -> List[UIElement]:
        """
        Use Windows UI Automation (UIA) to extract elements from the active window.
        Highly reliable for native Win32/WPF/WinForms apps.
        """
        elements: List[UIElement] = []
        try:
            import comtypes.client  # type: ignore
            import comtypes  # type: ignore
            from comtypes import CoInitialize, CoUninitialize
            try:
                CoInitialize()
            except Exception:
                pass

            try:
                import comtypes.gen.UIAutomationClient as uia  # type: ignore

                UIA = comtypes.client.CreateObject(
                    "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                    interface=uia.IUIAutomation,
                )

                if hwnd:
                    root = UIA.ElementFromHandle(hwnd)
                else:
                    root = UIA.GetFocusedElement()
                    if root is None:
                        root = UIA.GetRootElement()

                # Walk tree (BFS, max 200 nodes)
                elements = self._walk_uia_tree(UIA, root, max_nodes=200)
            finally:
                try:
                    CoUninitialize()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"UIA detection unavailable: {e}")
        return elements

    def _walk_uia_tree(self, uia_client, root, max_nodes: int = 200) -> List[UIElement]:
        """BFS walk of UIA element tree."""
        results: List[UIElement] = []
        try:
            import comtypes.gen.UIAutomationClient as uia  # type: ignore
            from comtypes import COMError

            CONTROL_TYPE_MAP = {
                50000: "window",
                50001: "text",
                50002: "button",
                50003: "menu",
                50004: "menu",
                50005: "text",
                50006: "link",
                50007: "input",
                50008: "input",
                50009: "checkbox",
                50010: "radio",
                50011: "dropdown",
                50012: "scrollbar",
                50013: "tab",
                50020: "image",
                50025: "button",
                50026: "input",
            }

            cond = uia_client.CreateTrueCondition()
            walker = uia_client.CreateTreeWalker(cond)

            queue = [root]
            visited = 0
            while queue and visited < max_nodes:
                elem = queue.pop(0)
                visited += 1
                try:
                    ctrl_type = elem.CurrentControlType
                    name = elem.CurrentName or ""
                    rect = elem.CurrentBoundingRectangle
                    enabled = bool(elem.CurrentIsEnabled)
                    off_screen = bool(elem.CurrentIsOffscreen)
                    auto_id = elem.CurrentAutomationId or ""

                    etype = CONTROL_TYPE_MAP.get(ctrl_type, "element")

                    if name.strip() and rect.right > rect.left and not off_screen:
                        results.append(UIElement(
                            type=etype,
                            text=name.strip(),
                            role=str(ctrl_type),
                            bounds=(rect.left, rect.top, rect.right, rect.bottom),
                            enabled=enabled,
                            visible=not off_screen,
                            confidence=1.0,
                            automation_id=auto_id,
                            source="uia",
                        ))

                    # Enqueue children
                    child = walker.GetFirstChildElement(elem)
                    while child:
                        queue.append(child)
                        try:
                            child = walker.GetNextSiblingElement(child)
                        except COMError:
                            break
                except COMError:
                    continue
        except Exception as e:
            logger.debug(f"UIA tree walk error: {e}")
        return results

    # ─── Visual / OCR fallback ──────────────────────────────────────────────

    def detect_via_vision(self, image: Image.Image) -> List[UIElement]:
        """
        Detect UI elements from a screenshot using OCR + heuristics.
        Falls back gracefully when UIA is unavailable.
        """
        from app.vision.ocr_service import get_ocr_service
        ocr = get_ocr_service()
        elements: List[UIElement] = []

        if not ocr.available:
            return elements

        # Get structured OCR data (word + bounding boxes)
        words = ocr.extract_structured(image)

        # Simple heuristic classification based on text patterns
        for w in words:
            text = w.get("text", "").strip()
            bounds = w.get("bounds", (0, 0, 0, 0))
            conf = w.get("confidence", 0.9)
            if not text:
                continue

            etype = self._classify_text_element(text)
            elements.append(UIElement(
                type=etype,
                text=text,
                bounds=bounds,
                confidence=conf,
                source="ocr",
            ))

        return elements

    def _classify_text_element(self, text: str) -> str:
        """Heuristic text classification."""
        t = text.lower().strip()

        button_words = {"ok", "cancel", "submit", "apply", "save", "open", "close",
                        "next", "back", "previous", "done", "continue", "login",
                        "sign in", "sign up", "create", "delete", "remove", "add",
                        "download", "upload", "send", "confirm", "accept", "decline",
                        "yes", "no", "agree", "retry", "update", "install"}

        if t in button_words or re.match(r"^(click|press|tap)\s", t):
            return "button"

        if re.match(r"^https?://", t) or re.match(r"^www\.", t):
            return "link"

        if re.match(r"^[\w.\-]+@[\w.\-]+\.\w+$", t):
            return "input"

        if t.startswith("☐") or t.startswith("☑") or t.startswith("✓") or t.startswith("□"):
            return "checkbox"

        if t.startswith("○") or t.startswith("●"):
            return "radio"

        if re.match(r"^(file|edit|view|tools|help|window|format|insert|actions?)$", t):
            return "menu"

        if len(t) < 60:
            return "text"

        return "text"

    # ─── Combined Detection ──────────────────────────────────────────────────

    def detect(self, image: Optional[Image.Image] = None, hwnd: Optional[int] = None) -> List[UIElement]:
        """
        Attempt UIA first, fall back to visual OCR.
        De-duplicates elements by bounding-box overlap.
        """
        elements: List[UIElement] = []

        # Try UIA
        uia_elements = self.detect_via_uia(hwnd)
        if uia_elements:
            elements.extend(uia_elements)
            logger.debug(f"UI Detector: {len(uia_elements)} elements via UIA")

        # If UIA yielded very few results, supplement with vision
        if len(uia_elements) < 3 and image is not None:
            vision_elements = self.detect_via_vision(image)
            logger.debug(f"UI Detector: {len(vision_elements)} elements via vision/OCR")
            elements.extend(vision_elements)

        return elements


_instance: Optional[UIDetector] = None

def get_ui_detector() -> UIDetector:
    global _instance
    if _instance is None:
        _instance = UIDetector()
    return _instance
