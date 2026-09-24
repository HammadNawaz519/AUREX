"""
Screen data model for AUREX structured screen understanding.
Provides ScreenState and UIElement dataclasses used throughout the vision pipeline.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import time


@dataclass
class UIElement:
    """Represents a single detected UI element on screen."""
    type: str                          # button | text | input | checkbox | link | menu | tab | icon | scrollbar | window | dialog | image | table | dropdown | radio
    text: str = ""
    role: str = ""                     # accessibility role if available
    bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x1, y1, x2, y2
    enabled: bool = True
    visible: bool = True
    focused: bool = False
    confidence: float = 1.0
    automation_id: str = ""
    source: str = "vision"             # vision | uia | dom | ocr
    extra: dict = field(default_factory=dict)

    @property
    def center(self) -> Tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "text": self.text,
            "role": self.role,
            "bounds": list(self.bounds),
            "center": list(self.center),
            "enabled": self.enabled,
            "visible": self.visible,
            "focused": self.focused,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "automation_id": self.automation_id,
        }


@dataclass
class ScreenState:
    """Full structured representation of the current screen."""
    timestamp: float = field(default_factory=time.time)
    application: str = ""
    window_title: str = ""
    elements: List[UIElement] = field(default_factory=list)
    scroll_position: Tuple[int, int] = (0, 0)  # x, y
    visible_text: str = ""
    focused_element: Optional[UIElement] = None
    cursor_position: Tuple[int, int] = (0, 0)
    screen_width: int = 1920
    screen_height: int = 1080
    image_path: Optional[str] = None   # path to captured screenshot if taken
    is_browser: bool = False
    browser_url: str = ""

    def find_element(self, text: str = "", etype: str = "") -> Optional[UIElement]:
        """Find first element matching text and/or type."""
        text_lower = text.lower()
        for el in self.elements:
            if etype and el.type != etype:
                continue
            if text_lower and text_lower not in el.text.lower():
                continue
            return el
        return None

    def find_all(self, text: str = "", etype: str = "") -> List[UIElement]:
        """Find all elements matching criteria."""
        text_lower = text.lower()
        results = []
        for el in self.elements:
            if etype and el.type != etype:
                continue
            if text_lower and text_lower not in el.text.lower():
                continue
            results.append(el)
        return results

    def to_agent_context(self) -> str:
        """Render a concise text representation for agent reasoning."""
        lines = []
        if self.application:
            lines.append(f"Application: {self.application}")
        if self.window_title:
            lines.append(f"Window: {self.window_title}")
        if self.is_browser and self.browser_url:
            lines.append(f"URL: {self.browser_url}")
        lines.append("")

        if self.elements:
            lines.append("Detected UI Elements:")
            for el in self.elements[:40]:  # cap context
                loc = f"({el.bounds[0]},{el.bounds[1]})"
                lines.append(f"  [{el.type.upper()}] \"{el.text}\" @ {loc}")

        if self.visible_text:
            snippet = self.visible_text[:800].replace("\n", " | ")
            lines.append(f"\nVisible Text (excerpt): {snippet}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "application": self.application,
            "window_title": self.window_title,
            "elements": [e.to_dict() for e in self.elements],
            "scroll_position": list(self.scroll_position),
            "visible_text": self.visible_text[:2000],
            "cursor_position": list(self.cursor_position),
            "screen_size": [self.screen_width, self.screen_height],
            "is_browser": self.is_browser,
            "browser_url": self.browser_url,
        }
