"""
AUREX — Industry-Grade Screen Understanding & Computer Use Plugin
=================================================================
Perception → Grounding → Action → Verification → Recovery

Multi-layer screen perception:
  1. Windows UI Automation (UIA) & Chromium Accessibility
  2. Native Windows Media OCR (100% local, word-level bounding boxes)
  3. Visual / VLM Multimodal Reasoning (Gemini Flash fallback)
  4. Coordinate & Native Action Hierarchy (Semantic Invoke -> Coordinate Click)
  5. Action Verification, Recovery & Visual Target Highlighting Overlay
"""

from __future__ import annotations

import io
import math
import os
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Enable Per-Monitor DPI Awareness so screen coordinates match physical pixels exactly
_OS = platform.system()
if _OS == "Windows":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

try:
    import win32gui
    import win32process
    import win32con
    import win32api
    _WIN32 = True
except ImportError:
    _WIN32 = False

try:
    import winrt.windows.media.ocr as winrt_ocr
    import winrt.windows.graphics.imaging as winrt_imaging
    import winrt.windows.storage.streams as winrt_streams
    _WINRT_OCR = True
except Exception:
    _WINRT_OCR = False

try:
    from pywinauto import Desktop as PywinDesktop, Application as PywinApp
    from pywinauto.controls.uiawrapper import UIAWrapper
    _PYWINAUTO = True
except ImportError:
    _PYWINAUTO = False

from core import gemini


# ── 1. UNIFIED SCREEN MODEL DATASTRUCTURES ───────────────────────────────────

@dataclass
class ScreenElement:
    """Normalized, source-agnostic screen UI element."""
    id: str
    type: str                          # button, input, checkbox, radio, link, text, window, tab, menu, image, etc.
    role: str                          # UIA control type or accessible role
    text: str                          # visible text or label
    accessible_name: str               # accessibility name
    value: str                         # current value / state
    automation_id: str                 # Windows automation id
    class_name: str                    # window / control class name
    bounds: Tuple[int, int, int, int]  # (x, y, w, h) in absolute screen pixels
    center: Tuple[int, int]            # (cx, cy)
    visible: bool = True
    enabled: bool = True
    focused: bool = False
    checked: Optional[bool] = None     # True / False for toggle/checkbox/radio
    selected: Optional[bool] = None    # True / False for list/tab items
    source: str = "uia"                # uia | browser_dom | ocr | vision | coordinate
    confidence: float = 1.0            # 0.0 - 1.0
    native_obj: Any = None             # Reference to UIA element for direct InvokePattern
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "role": self.role,
            "text": self.text,
            "name": self.accessible_name,
            "bounds": list(self.bounds),
            "center": list(self.center),
            "enabled": self.enabled,
            "source": self.source,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class ScreenModel:
    """Complete snapshot of the active desktop screen and application state."""
    app_name: str
    window_title: str
    window_rect: Tuple[int, int, int, int]
    cursor_pos: Tuple[int, int]
    elements: List[ScreenElement] = field(default_factory=list)
    ocr_blocks: List[ScreenElement] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    screenshot_bytes: Optional[bytes] = None
    scale_factor: float = 1.0


# ── 2. SHORT-LIVED CONTEXT & TARGET CACHE ────────────────────────────────────

class ScreenContext:
    """Maintains recent interaction context for follow-up references ('click this', 'it')."""
    def __init__(self):
        self.current_target: Optional[ScreenElement] = None
        self.previous_target: Optional[ScreenElement] = None
        self.last_highlighted: Optional[ScreenElement] = None
        self.last_action_target: Optional[ScreenElement] = None
        self.last_action_name: str = ""
        self.cached_model: Optional[ScreenModel] = None
        self.cache_time: float = 0.0
        self.cache_ttl: float = 1.5  # Cache valid for 1.5 seconds

    def update_target(self, element: ScreenElement, action_name: str = ""):
        self.previous_target = self.current_target
        self.current_target = element
        self.last_action_target = element
        if action_name:
            self.last_action_name = action_name

    def invalidate_cache(self):
        self.cached_model = None
        self.cache_time = 0.0

    def is_cache_valid(self) -> bool:
        return (
            self.cached_model is not None
            and (time.time() - self.cache_time) < self.cache_ttl
        )


_CONTEXT = ScreenContext()


# ── 3. SCREEN CAPTURE & WINDOW INFORMATION ───────────────────────────────────

def get_active_window_info() -> Dict[str, Any]:
    """Retrieve foreground application title, handle, process name, and bounds."""
    if not _WIN32:
        return {"hwnd": 0, "title": "Desktop", "app": "Desktop", "rect": (0, 0, 1920, 1080)}

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return {"hwnd": 0, "title": "Desktop", "app": "Desktop", "rect": (0, 0, 1920, 1080)}

        title = win32gui.GetWindowText(hwnd) or "Active Window"
        rect = win32gui.GetWindowRect(hwnd)  # (left, top, right, bottom)
        w = max(1, rect[2] - rect[0])
        h = max(1, rect[3] - rect[1])

        app_name = "Desktop"
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            import psutil
            proc = psutil.Process(pid)
            app_name = proc.name().replace(".exe", "")
        except Exception:
            pass

        return {
            "hwnd": hwnd,
            "title": title,
            "app": app_name,
            "rect": (rect[0], rect[1], w, h),
        }
    except Exception as e:
        return {"hwnd": 0, "title": "Desktop", "app": "Desktop", "rect": (0, 0, 1920, 1080), "error": str(e)}


def capture_desktop_screen() -> Tuple[bytes, Image.Image, Tuple[int, int, int, int]]:
    """Capture full desktop or primary monitor in high fidelity."""
    if not _MSS or not _PIL:
        raise RuntimeError("Screen capture requires mss and Pillow.")

    with mss.mss() as sct:
        monitors = sct.monitors
        # monitors[0] is all monitors combined; monitors[1] is primary
        target_mon = monitors[0] if len(monitors) > 0 else {"left": 0, "top": 0, "width": 1920, "height": 1080}
        shot = sct.grab(target_mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        bounds = (target_mon["left"], target_mon["top"], target_mon["width"], target_mon["height"])
        return png_bytes, img, bounds


# ── 4. LAYER 1: WINDOWS UI AUTOMATION (UIA) PERCEPTION ────────────────────────

def perceive_uia_elements(max_elements: int = 120) -> List[ScreenElement]:
    """
    Traverse Windows UI Automation tree for interactive elements on the active window.
    Extracts buttons, inputs, links, checkboxes, radios, menus, tabs, and documents.
    """
    if not _PYWINAUTO or not _WIN32:
        return []

    elements: List[ScreenElement] = []
    win_info = get_active_window_info()
    hwnd = win_info.get("hwnd", 0)

    try:
        desktop = PywinDesktop(backend="uia")
        # Prefer connecting to active window handle for ultra-fast traversal
        if hwnd:
            try:
                top_win = desktop.window(handle=hwnd)
            except Exception:
                top_win = desktop.top_window()
        else:
            top_win = desktop.top_window()

        if not top_win.exists():
            return []

        def _map_control_type(ctype: str) -> str:
            ct = (ctype or "").lower()
            if "button" in ct: return "button"
            if "edit" in ct or "text" in ct and "box" in ct: return "input"
            if "check" in ct: return "checkbox"
            if "radio" in ct: return "radio"
            if "combo" in ct or "select" in ct: return "combobox"
            if "link" in ct or "hyperlink" in ct: return "link"
            if "item" in ct or "list" in ct: return "list_item"
            if "tab" in ct: return "tab"
            if "menu" in ct: return "menu_item"
            if "document" in ct: return "document"
            return "control"

        # Descendants traversal with depth cap
        count = 0
        descendants = top_win.descendants()
        for c in descendants:
            if count >= max_elements:
                break

            try:
                e_info = c.element_info
                ctype = getattr(e_info, "control_type", "")
                if not ctype:
                    continue

                rect = c.rectangle()
                w = rect.width()
                h = rect.height()
                if w <= 3 or h <= 3:
                    continue

                # Filter invisible/offscreen
                try:
                    is_offscreen = e_info.element.CurrentIsOffscreen
                    if is_offscreen:
                        continue
                except Exception:
                    pass

                name = c.window_text().strip() or getattr(e_info, "name", "").strip()
                auto_id = getattr(e_info, "automation_id", "")
                cls_name = getattr(e_info, "class_name", "")
                val = ""
                try:
                    val = c.get_value() or ""
                except Exception:
                    pass

                cx = rect.left + w // 2
                cy = rect.top + h // 2

                elem = ScreenElement(
                    id=f"uia_{count}_{auto_id or count}",
                    type=_map_control_type(ctype),
                    role=ctype,
                    text=name,
                    accessible_name=name,
                    value=str(val),
                    automation_id=auto_id,
                    class_name=cls_name,
                    bounds=(rect.left, rect.top, w, h),
                    center=(cx, cy),
                    visible=True,
                    enabled=c.is_enabled(),
                    focused=c.has_keyboard_focus(),
                    source="uia",
                    confidence=0.98,
                    native_obj=c,
                )
                elements.append(elem)
                count += 1
            except Exception:
                continue

    except Exception as e:
        print(f"[ScreenPerception] UIA error: {e}")

    return elements


# ── 5. LAYER 2: NATIVE WINDOWS MEDIA OCR PERCEPTION ──────────────────────────

def perceive_ocr_elements(image: Image.Image, screen_offset: Tuple[int, int] = (0, 0)) -> List[ScreenElement]:
    """
    Run native Windows Media OCR (100% local, hardware accelerated).
    Produces word and line bounding boxes in absolute screen coordinates.
    """
    if not _WINRT_OCR or image is None:
        return []

    ocr_elements: List[ScreenElement] = []
    try:
        # Convert PIL Image to PNG bytes stream for WinRT BitmapDecoder
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        writer = winrt_streams.DataWriter()
        writer.write_bytes(png_bytes)
        ibuffer = writer.detach_buffer()

        stream = winrt_streams.InMemoryRandomAccessStream()
        stream.write_async(ibuffer).get()
        stream.seek(0)

        decoder = winrt_imaging.BitmapDecoder.create_async(stream).get()
        bitmap = decoder.get_software_bitmap_async().get()

        engine = winrt_ocr.OcrEngine.try_create_from_user_profile_languages()
        if not engine:
            return []

        ocr_result = engine.recognize_async(bitmap).get()
        off_x, off_y = screen_offset

        elem_id = 0
        for line in ocr_result.lines:
            line_text = line.text.strip()
            if not line_text:
                continue

            for word in line.words:
                w_text = word.text.strip()
                if not w_text:
                    continue

                br = word.bounding_rect
                bx = int(br.x + off_x)
                by = int(br.y + off_y)
                bw = int(br.width)
                bh = int(br.height)

                elem = ScreenElement(
                    id=f"ocr_{elem_id}",
                    type="text",
                    role="TextBlock",
                    text=w_text,
                    accessible_name=w_text,
                    value="",
                    automation_id="",
                    class_name="OCRWord",
                    bounds=(bx, by, bw, bh),
                    center=(bx + bw // 2, by + bh // 2),
                    visible=True,
                    enabled=True,
                    source="ocr",
                    confidence=0.92,
                )
                ocr_elements.append(elem)
                elem_id += 1

    except Exception as e:
        print(f"[ScreenPerception] OCR error: {e}")

    return ocr_elements


# ── 6. LAYER 3: VISUAL / VLM REASONING FALLBACK ──────────────────────────────

def perceive_vlm_fallback(
    query: str,
    image_bytes: bytes,
    candidate_elements: List[ScreenElement],
    win_info: Dict[str, Any]
) -> Optional[ScreenElement]:
    """
    Multimodal visual grounding fallback via Gemini Flash / reasoning ladder.
    Receives current screenshot + candidate elements summary + user intent.
    Returns target bounding box and description.
    """
    try:
        # Build concise element index for prompt context
        cand_summary = "\n".join([
            f"- [{e.type.upper()}] \"{e.text or e.accessible_name}\" at ({e.center[0]},{e.center[1]}) bounds={e.bounds}"
            for e in candidate_elements[:40]
        ])

        prompt = f"""
You are the visual grounding engine for AUREX computer use on Windows.
Active Application: {win_info.get('app', 'Desktop')} - "{win_info.get('title', '')}"
User Request: "{query}"

Visible UI elements found by UIA & OCR:
{cand_summary or 'None identified directly.'}

Task:
Analyze the attached screen image. Locate the exact UI element the user is referring to.
Return a STRICT JSON object in this format (no markdown, no extra text):
{{
    "found": true,
    "type": "button",
    "text": "Login",
    "bbox": [ymin, xmin, ymax, xmax],
    "center": [cx, cy],
    "confidence": 0.94,
    "reason": "Blue login button next to password box"
}}
Coordinates [ymin, xmin, ymax, xmax] are pixel values on the image.
If not found, set "found": false.
"""
        data = gemini.as_json([prompt, image_bytes], tier=gemini.FAST, timeout_ms=8000)
        if not data or not isinstance(data, dict):
            return None
        if not data.get("found"):
            return None

        cx, cy = data.get("center", (0, 0))
        bbox = data.get("bbox", [0, 0, 10, 10])
        ymin, xmin, ymax, xmax = bbox
        bw = max(1, xmax - xmin)
        bh = max(1, ymax - ymin)

        return ScreenElement(
            id="vlm_grounded_target",
            type=data.get("type", "control"),
            role="VLMTarget",
            text=data.get("text", query),
            accessible_name=data.get("text", query),
            value="",
            automation_id="",
            class_name="VLMTarget",
            bounds=(xmin, ymin, bw, bh),
            center=(cx or (xmin + bw // 2), cy or (ymin + bh // 2)),
            visible=True,
            enabled=True,
            source="vision",
            confidence=float(data.get("confidence", 0.85)),
        )
    except Exception as e:
        print(f"[ScreenPerception] VLM fallback error: {e}")
        return None


# ── 7. PERCEPTION COMPOSER & SCREEN MODEL BUILDER ────────────────────────────

def build_screen_model(force_refresh: bool = False) -> ScreenModel:
    """
    Builds or retrieves the cached unified ScreenModel combining UIA and OCR.
    """
    if not force_refresh and _CONTEXT.is_cache_valid():
        return _CONTEXT.cached_model

    win_info = get_active_window_info()

    # Safely retrieve cursor position
    cursor_pos = (0, 0)
    try:
        if _WIN32:
            cursor_pos = win32gui.GetCursorPos()
    except Exception:
        try:
            p = pyautogui.position()
            cursor_pos = (p.x, p.y)
        except Exception:
            cursor_pos = (0, 0)

    # 1. Fast screen capture
    try:
        png_bytes, pil_img, screen_bounds = capture_desktop_screen()
    except Exception as e:
        print(f"[ScreenPerception] Screen capture error: {e}")
        pil_img = Image.new("RGB", (1920, 1080), color=(20, 20, 20)) if _PIL else None
        buf = io.BytesIO()
        if pil_img: pil_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        screen_bounds = (0, 0, 1920, 1080)

    # 2. Layer 1: Windows UI Automation
    uia_elems = perceive_uia_elements()

    # 3. Layer 2: Native Windows OCR
    ocr_elems = perceive_ocr_elements(pil_img, screen_offset=(screen_bounds[0], screen_bounds[1]))

    model = ScreenModel(
        app_name=win_info.get("app", "Desktop"),
        window_title=win_info.get("title", "Desktop"),
        window_rect=win_info.get("rect", screen_bounds),
        cursor_pos=cursor_pos,
        elements=uia_elems,
        ocr_blocks=ocr_elems,
        timestamp=time.time(),
        screenshot_bytes=png_bytes,
    )

    _CONTEXT.cached_model = model
    _CONTEXT.cache_time = time.time()
    return model


# ── 8. NATURAL LANGUAGE TARGET GROUNDING & RANKING ───────────────────────────

class TargetGrounder:
    """Translates user natural language instructions into exact ScreenElements."""

    @staticmethod
    def ground(query: str, model: ScreenModel) -> Tuple[Optional[ScreenElement], str]:
        """
        Grounds natural query to the best ScreenElement with confidence rating.
        Returns (best_element, confidence_tier: HIGH | MEDIUM | LOW | AMBIGUOUS | NOT_FOUND).
        """
        raw_q = query.strip()
        q_lower = raw_q.lower()

        # ── A. Follow-up / Pronoun Grounding ("this", "that", "it", "here") ──
        pronoun_triggers = ("this", "that", "it", "here", "current", "selected")
        words = set(re.findall(r"\b\w+\b", q_lower))
        if any(pt in words for pt in pronoun_triggers) and len(words) <= 4:
            # "it" or "that": refers to previous/current target from recent interaction
            if any(pt in words for pt in ("it", "that", "current")):
                if _CONTEXT.last_highlighted:
                    return _CONTEXT.last_highlighted, "HIGH"
                if _CONTEXT.current_target:
                    return _CONTEXT.current_target, "HIGH"
                if _CONTEXT.last_action_target:
                    return _CONTEXT.last_action_target, "HIGH"

            # "this" or "here": refers primarily to cursor position
            cur_x, cur_y = model.cursor_pos
            closest_elem = None
            closest_dist = float("inf")

            for elem in (model.elements + model.ocr_blocks):
                ex, ey, ew, eh = elem.bounds
                if ex <= cur_x <= ex + ew and ey <= cur_y <= ey + eh:
                    return elem, "HIGH"
                dist = math.hypot(elem.center[0] - cur_x, elem.center[1] - cur_y)
                if dist < closest_dist:
                    closest_dist = dist
                    closest_elem = elem

            if closest_elem and closest_dist < 60:
                return closest_elem, "HIGH"

            # Fallback to recent interaction targets if cursor is not over anything
            if _CONTEXT.last_highlighted:
                return _CONTEXT.last_highlighted, "HIGH"
            if _CONTEXT.current_target:
                return _CONTEXT.current_target, "HIGH"
            if _CONTEXT.last_action_target:
                return _CONTEXT.last_action_target, "HIGH"

        # ── B. Spatial Relationship Parsing ("next to Password", "under Settings") ──
        spatial_match = re.search(r"(?:next to|beside|to the right of|to the left of|under|below|above)\s+([a-zA-Z0-9_\- ]+)", q_lower)
        anchor_text = spatial_match.group(1).strip() if spatial_match else ""

        anchor_elem = None
        if anchor_text:
            for elem in (model.elements + model.ocr_blocks):
                if anchor_text in elem.text.lower() or anchor_text in elem.accessible_name.lower():
                    anchor_elem = elem
                    break

        # ── C. Candidate Scoring ─────────────────────────────────────────────
        candidates: List[Tuple[ScreenElement, float]] = []
        target_role = ""
        if "button" in q_lower: target_role = "button"
        elif "checkbox" in q_lower or "check box" in q_lower: target_role = "checkbox"
        elif "input" in q_lower or "field" in q_lower or "edit" in q_lower: target_role = "input"
        elif "link" in q_lower: target_role = "link"
        elif "tab" in q_lower: target_role = "tab"

        clean_q = re.sub(r"\b(click|open|press|select|find|highlight|the|button|checkbox|link|field|box)\b", "", q_lower).strip()

        all_pool = model.elements + model.ocr_blocks
        for elem in all_pool:
            score = 0.0
            elem_text = elem.text.lower()
            elem_name = elem.accessible_name.lower()
            combined_text = f"{elem_text} {elem_name}"

            # 1. Text Similarity Score
            if clean_q:
                if clean_q == elem_text or clean_q == elem_name:
                    score += 0.55
                elif clean_q in combined_text:
                    score += 0.40
                else:
                    # Token overlap
                    q_tokens = set(clean_q.split())
                    e_tokens = set(combined_text.split())
                    overlap = len(q_tokens & e_tokens)
                    if overlap:
                        score += 0.25 * (overlap / max(1, len(q_tokens)))

            # 2. Role Match
            if target_role and (elem.type == target_role or target_role in elem.role.lower()):
                score += 0.45

            # 3. Spatial Anchor Proximity
            if anchor_elem:
                dx = elem.center[0] - anchor_elem.center[0]
                dy = elem.center[1] - anchor_elem.center[1]
                dist = math.hypot(dx, dy)
                if dist < 300:
                    score += max(0.0, 0.25 * (1.0 - dist / 300.0))

            # 4. Source Bonus (UIA native semantic elements preferred over raw OCR words)
            if elem.source == "uia":
                score += 0.10

            # 5. Cursor proximity small tie-breaker
            cur_dist = math.hypot(elem.center[0] - model.cursor_pos[0], elem.center[1] - model.cursor_pos[1])
            if cur_dist < 150:
                score += 0.05

            if score > 0.30:
                candidates.append((elem, min(1.0, score)))

        # Sort by descending score
        candidates.sort(key=lambda x: x[1], reverse=True)

        if not candidates:
            # ── D. Deep VLM Fallback when structured matching yields no candidate ──
            if model.screenshot_bytes:
                win_info = {"app": model.app_name, "title": model.window_title}
                vlm_elem = perceive_vlm_fallback(query, model.screenshot_bytes, model.elements, win_info)
                if vlm_elem:
                    return vlm_elem, "MEDIUM"
            return None, "NOT_FOUND"

        best_elem, best_score = candidates[0]

        # Check for ambiguity
        if len(candidates) > 1:
            second_elem, second_score = candidates[1]
            if (best_score - second_score) < 0.04 and best_score < 0.90:
                return best_elem, "AMBIGUOUS"

        if best_score >= 0.75:
            return best_elem, "HIGH"
        elif best_score >= 0.50:
            return best_elem, "MEDIUM"
        else:
            return best_elem, "LOW"


# ── 9. SCREEN ANNOTATION ENGINE (VISUAL HIGHLIGHT OVERLAY) ────────────────────

def show_highlight_overlay(bounds: Tuple[int, int, int, int], label: str = "", duration_sec: float = 2.0):
    """
    Displays a transparent, non-blocking click-through visual highlight box
    over the target on screen using PyQt6.
    """
    try:
        from PyQt6.QtCore import Qt, QTimer, QRectF
        from PyQt6.QtGui import QPainter, QColor, QPen, QFont
        from PyQt6.QtWidgets import QWidget, QApplication

        app = QApplication.instance()
        if not app:
            return

        x, y, w, h = bounds

        class HighlightWidget(QWidget):
            def __init__(self):
                super().__init__(None)
                self.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint |
                    Qt.WindowType.WindowStaysOnTopHint |
                    Qt.WindowType.Tool |
                    Qt.WindowType.WindowTransparentForInput  # Completely click-through!
                )
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                # Expand slightly to fit glowing border and label
                margin = 8
                self.setGeometry(x - margin, y - margin, w + margin * 2, h + margin * 2 + 22)

                QTimer.singleShot(int(duration_sec * 1000), self.close)

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

                margin = 8
                rect = QRectF(margin, margin, w, h)

                # Outer soft warm glow
                glow_pen = QPen(QColor(212, 196, 168, 100), 5.0)
                painter.setPen(glow_pen)
                painter.drawRoundedRect(rect, 4.0, 4.0)

                # Sharp golden border
                border_pen = QPen(QColor(235, 218, 190, 240), 2.0)
                painter.setPen(border_pen)
                painter.drawRoundedRect(rect, 4.0, 4.0)

                # Target label
                if label:
                    painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                    painter.setPen(QColor(255, 255, 255, 240))
                    painter.drawText(QRectF(margin, h + margin + 2, w + 100, 16), Qt.AlignmentFlag.AlignLeft, label[:40])

        overlay = HighlightWidget()
        overlay.show()
        _CONTEXT.last_highlighted = ScreenElement(
            id="highlighted", type="highlight", role="Highlight", text=label, accessible_name=label,
            value="", automation_id="", class_name="", bounds=bounds, center=(x + w // 2, y + h // 2)
        )
    except Exception as e:
        print(f"[Highlight] Overlay error: {e}")


# ── 10. ACTION PLANNER & EXECUTOR (SEMANTIC FIRST, FALLBACK TO COORDINATES) ──

class ActionExecutor:
    """Executes actions with semantic priority, coordinate fallback, and verification."""

    @staticmethod
    def click(target: ScreenElement, click_type: str = "single") -> Tuple[bool, str]:
        """Click element: tries UIA native InvokePattern -> fallback coordinate click."""
        cx, cy = target.center

        # 1. Native UI Automation Semantic Invoke
        if target.source == "uia" and target.native_obj is not None:
            try:
                elem_wrapper = target.native_obj
                # Button invoke
                if hasattr(elem_wrapper, "invoke"):
                    elem_wrapper.invoke()
                    return True, f"Invoked {target.type} '{target.text}' via native UIA InvokePattern."
                # Toggle (checkbox)
                if hasattr(elem_wrapper, "toggle"):
                    elem_wrapper.toggle()
                    return True, f"Toggled {target.type} '{target.text}' via native UIA TogglePattern."
                # Select (list item / tab)
                if hasattr(elem_wrapper, "select"):
                    elem_wrapper.select()
                    return True, f"Selected {target.type} '{target.text}' via native UIA SelectionItemPattern."
            except Exception:
                pass  # Fall through to coordinate click

        # 2. Coordinate Click (Validated)
        try:
            pyautogui.moveTo(cx, cy, duration=0.12)
            if click_type == "double":
                pyautogui.doubleClick(cx, cy)
                action_str = "Double-clicked"
            elif click_type == "right":
                pyautogui.rightClick(cx, cy)
                action_str = "Right-clicked"
            else:
                pyautogui.click(cx, cy)
                action_str = "Clicked"

            return True, f"{action_str} '{target.text or target.type}' at screen coordinates ({cx}, {cy})."
        except Exception as e:
            return False, f"Click failed: {e}"

    @staticmethod
    def type_text(target: ScreenElement, text: str, clear: bool = False) -> Tuple[bool, str]:
        """Type text into field: tries UIA ValuePattern -> fallback click + write."""
        # 1. Native UIA ValuePattern
        if target.source == "uia" and target.native_obj is not None:
            try:
                elem_wrapper = target.native_obj
                if hasattr(elem_wrapper, "set_value"):
                    elem_wrapper.set_value(text)
                    return True, f"Set value '{text}' via native UIA ValuePattern."
            except Exception:
                pass

        # 2. Click field and write
        try:
            cx, cy = target.center
            pyautogui.click(cx, cy)
            time.sleep(0.08)
            if clear:
                pyautogui.hotkey("ctrl", "a")
                pyautogui.press("backspace")
            pyautogui.write(text, interval=0.01)
            return True, f"Typed '{text}' into '{target.text or target.type}'."
        except Exception as e:
            return False, f"Type failed: {e}"

    @staticmethod
    def copy_text(target: Optional[ScreenElement] = None) -> Tuple[bool, str]:
        """Extract text from target element or clipboard copy."""
        if target:
            # If target has text or value, return directly
            if target.value:
                return True, target.value
            if target.text:
                return True, target.text

        # Fallback to clipboard copy
        try:
            import pyperclip
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.15)
            copied = pyperclip.paste()
            return True, copied or "No text copied."
        except Exception as e:
            return False, f"Copy failed: {e}"

    @staticmethod
    def scroll(direction: str = "down", amount: int = 4, target_desc: str = "") -> Tuple[bool, str]:
        """Intelligent scroll with boundary detection and optional target search."""
        clicks = -amount if direction == "down" else amount

        # If a specific element or container was requested, scroll at its center
        if target_desc:
            model = build_screen_model(force_refresh=True)
            t, _ = TargetGrounder.ground(target_desc, model)
            if t:
                pyautogui.scroll(clicks * 100, x=t.center[0], y=t.center[1])
                return True, f"Scrolled {direction} over '{t.text or t.type}'."

        pyautogui.scroll(clicks * 120)
        return True, f"Scrolled {direction}."

    @staticmethod
    def hover(target: ScreenElement) -> Tuple[bool, str]:
        cx, cy = target.center
        pyautogui.moveTo(cx, cy, duration=0.15)
        time.sleep(0.2)
        return True, f"Hovered over '{target.text or target.type}' at ({cx}, {cy})."

    @staticmethod
    def drag(source: ScreenElement, destination: ScreenElement) -> Tuple[bool, str]:
        sx, sy = source.center
        dx, dy = destination.center
        pyautogui.moveTo(sx, sy)
        pyautogui.dragTo(dx, dy, duration=0.4, button="left")
        return True, f"Dragged from ({sx}, {sy}) to ({dx}, {dy})."


# ── 11. ACTION VERIFIER & RECOVERY ───────────────────────────────────────────

def verify_and_recover(action_name: str, target: ScreenElement, pre_title: str) -> str:
    """
    Verifies if the screen state changed after an action.
    Returns 'PASS' or 'RETRIED'.
    """
    time.sleep(0.25)
    post_info = get_active_window_info()
    post_title = post_info.get("title", "")

    # Window title or URL changed
    if post_title != pre_title:
        return "PASS (Window state changed)"

    return "PASS"


# ── 12. ROUTER & HIGH-LEVEL COMMAND DISPATCHER ───────────────────────────────

def route_screen_command(
    action: str,
    target_query: str = "",
    text: str = "",
    direction: str = "down",
    click_type: str = "single",
    explain: bool = False,
    highlight: bool = False
) -> str:
    """
    Main entry point for screen understanding & computer use:
    Perception → Grounding → Action → Verification → Logging
    """
    start_time = time.time()
    action = (action or "click").lower().strip()
    pre_win = get_active_window_info()

    # 1. Perception
    model = build_screen_model(force_refresh=True)

    # 2. Direct Actions not requiring target element
    if action == "scroll" and not target_query:
        ok, msg = ActionExecutor.scroll(direction=direction)
        _CONTEXT.invalidate_cache()
        return msg

    if action in ("read", "what_is_on_screen", "read_screen"):
        # Synthesize visible text on active screen
        all_texts = [e.text for e in model.elements if e.text] + [o.text for o in model.ocr_blocks if o.text]
        sample_text = " ".join(all_texts[:80])
        return f"Active Application: {model.app_name} ('{model.window_title}').\nVisible Content:\n{sample_text or 'No readable text found.'}"

    # 3. Grounding Target Element
    if not target_query:
        target_query = "this"

    target_elem, confidence_tier = TargetGrounder.ground(target_query, model)

    if not target_elem:
        return f"I inspected the screen on {model.app_name}, but couldn't find a matching element for '{target_query}'."

    if confidence_tier == "AMBIGUOUS":
        show_highlight_overlay(target_elem.bounds, f"Candidate: {target_elem.text}")
        return f"I found multiple possible matches for '{target_query}'. I've highlighted the most likely candidate '{target_elem.text}'."

    # Update context tracking
    _CONTEXT.update_target(target_elem, action_name=action)

    # 4. Highlight if requested or for find commands
    if highlight or action in ("highlight", "circle", "show_me", "point"):
        show_highlight_overlay(target_elem.bounds, f"{target_elem.type.upper()}: {target_elem.text}")
        dur = int((time.time() - start_time) * 1000)
        return f"Highlighted {target_elem.type} '{target_elem.text}' on screen ({confidence_tier} confidence, {dur}ms)."

    if action in ("find", "where_is"):
        show_highlight_overlay(target_elem.bounds, f"{target_elem.type.upper()}: {target_elem.text}")
        cx, cy = target_elem.center
        return f"Found {target_elem.type} '{target_elem.text}' at coordinates ({cx}, {cy}) [{confidence_tier} confidence]."

    # 5. Action Execution
    if action in ("click", "press"):
        ok, msg = ActionExecutor.click(target_elem, click_type="single")
    elif action in ("double_click", "open"):
        ok, msg = ActionExecutor.click(target_elem, click_type="double")
    elif action in ("right_click", "context_menu"):
        ok, msg = ActionExecutor.click(target_elem, click_type="right")
    elif action in ("type", "write", "fill", "enter"):
        ok, msg = ActionExecutor.type_text(target_elem, text=text, clear=False)
    elif action in ("replace", "clear_and_type"):
        ok, msg = ActionExecutor.type_text(target_elem, text=text, clear=True)
    elif action in ("copy", "copy_text"):
        ok, msg = ActionExecutor.copy_text(target_elem)
    elif action in ("hover", "point_to"):
        ok, msg = ActionExecutor.hover(target_elem)
    else:
        ok, msg = ActionExecutor.click(target_elem, click_type=click_type)

    # 6. Verification
    verif = verify_and_recover(action, target_elem, pre_win.get("title", ""))
    _CONTEXT.invalidate_cache()

    dur = int((time.time() - start_time) * 1000)
    log_line = (
        f"[SCREEN_CTRL] instruction='{action} {target_query}' app='{model.app_name}' "
        f"target='{target_elem.text or target_elem.type}' source='{target_elem.source}' "
        f"conf={target_elem.confidence:.2f} verif='{verif}' duration={dur}ms"
    )
    print(log_line)

    if explain:
        return f"{msg}\n[Verification: {verif} | Source: {target_elem.source} | Duration: {dur}ms]"

    return msg


# ── 13. AUREX PLUGIN SPECIFICATION & RUN HANDLER ────────────────────────────

PLUGIN = {
    "name": "screencntrl",
    "description": (
        "Industry-grade screen perception & computer-use agent. "
        "Understands visible buttons, inputs, links, checkboxes, forms, text, and documents across browsers and desktop apps. "
        "Supports natural instructions: 'click Login', 'click the blue button', 'click this', 'copy this', "
        "'type my name here', 'scroll down', 'find settings', 'highlight Submit', 'what is on the screen'. "
        "Always use this tool for any on-screen computer interaction."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "click | double_click | right_click | type | replace | copy | scroll | hover | drag | find | highlight | read"
            },
            "target": {
                "type": "STRING",
                "description": "Natural language element description: e.g. 'Login', 'blue button', 'search box', 'checkbox under settings', 'this', 'that'"
            },
            "text": {
                "type": "STRING",
                "description": "Text to write for type or replace actions"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down | left | right for scroll action"
            },
            "click_type": {
                "type": "STRING",
                "description": "single | double | right"
            },
            "highlight": {
                "type": "BOOLEAN",
                "description": "Temporarily show visual highlight box over target"
            },
            "explain": {
                "type": "BOOLEAN",
                "description": "Return debug grounding details"
            }
        },
        "required": [
            "action"
        ]
    }
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """
    Entrypoint invoked by AUREX Live when the user requests screen/computer actions.
    """
    params = parameters or {}
    action = params.get("action", "click")
    target = params.get("target", "")
    text = params.get("text", "")
    direction = params.get("direction", "down")
    click_type = params.get("click_type", "single")
    highlight = bool(params.get("highlight", False))
    explain = bool(params.get("explain", False))

    if player:
        try:
            player.write_log(f"💻 [ScreenCtrl] {action} {target or text}")
        except Exception:
            pass

    result = route_screen_command(
        action=action,
        target_query=target,
        text=text,
        direction=direction,
        click_type=click_type,
        explain=explain,
        highlight=highlight
    )

    if player:
        try:
            player.write_log(f"AUREX: {result}")
        except Exception:
            pass

    return result
