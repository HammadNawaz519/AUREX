"""
AUREX Plugin: Shrink to Floating Pill Bubble
============================================
Provides smooth, reliable shrinking of the main AUREX window into a sleek,
compact floating black desktop pill bubble with a center-to-outwards wave animation,
and seamless restoring back to the full window.
"""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QBrush, QColor, QPen, QRadialGradient, QFont
)
from PyQt6.QtWidgets import QWidget, QApplication


# ── Global Singleton Instances ───────────────────────────────────────────────
_pill_window: Optional[ShrinkPillWindow] = None
_main_window: Optional[QWidget] = None


class ShrinkPillWindow(QWidget):
    """
    A compact, frameless, floating circular black pill window that sticks to the
    desktop with a mesmerizing center-to-outwards radiant wave animation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(124, 124)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("AUREX Pill Mode\n• Click or Double-click to restore\n• Drag to reposition")

        self._phase: float = 0.0
        self._timer: QTimer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps smooth wave
        self._timer.timeout.connect(self._on_tick)

        self._position_bottom_right()

    def _position_bottom_right(self):
        """Stick to the desktop bottom-right corner with a sleek margin."""
        app = QApplication.instance()
        if not app:
            return
        screen = app.primaryScreen()
        if screen:
            ag = screen.availableGeometry()
            margin_x = 28
            margin_y = 48
            self.move(
                ag.right() - self.width() - margin_x,
                ag.bottom() - self.height() - margin_y
            )

    def _on_tick(self):
        # Calm, luxurious wave expansion rate
        self._phase = (self._phase + 0.009) % 1.0
        self.update()

    def start_wave(self):
        if not self._timer.isActive():
            self._timer.start()

    def stop_wave(self):
        if self._timer.isActive():
            self._timer.stop()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and hasattr(self, "_press_pos"):
            dist = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
            if dist < 6:
                # Direct click without dragging -> restore full window
                restore()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        restore()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        center = QPointF(cx, cy)
        max_r = min(w, h) / 2.0 - 5.0
        min_r = 6.0
        wave_span = max_r - min_r

        # ── 1. Deep Jet-Black Circular Disc ──────────────────────────────────
        bg_grad = QRadialGradient(center, max_r)
        bg_grad.setColorAt(0.0, QColor(14, 16, 20, 252))
        bg_grad.setColorAt(0.65, QColor(6, 7, 10, 254))
        bg_grad.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.setBrush(QBrush(bg_grad))

        # Breathing outer border rim with warm beige/gold tone
        border_alpha = int(60 + 35 * math.sin(self._phase * 2.0 * math.pi))
        border_pen = QPen(QColor(212, 196, 168, border_alpha), 1.5)
        painter.setPen(border_pen)
        painter.drawEllipse(center, max_r, max_r)

        # ── 2. Concentric Waves Radiating from Center to Outwards ────────────
        num_waves = 5
        for i in range(num_waves):
            # Staggered phase offset for each wave ring
            prog = (self._phase + (i / float(num_waves))) % 1.0

            # Radius expands from min_r (center) to max_r (perimeter)
            r = min_r + (prog ** 0.82) * wave_span

            # Opacity fades naturally as wave expands outwards
            fade = 1.0 - prog
            alpha = int(225 * (fade ** 1.35))

            if alpha > 3:
                # Soft diffuse outer glow for each wave ring
                glow_pen = QPen(QColor(212, 196, 168, int(alpha * 0.35)), 3.8)
                painter.setPen(glow_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, r, r)

                # Sharp luminous wave line
                wave_pen = QPen(QColor(235, 222, 200, alpha), 1.6)
                painter.setPen(wave_pen)
                painter.drawEllipse(center, r, r)

        # ── 3. Pulsing Central Energy Nexus ──────────────────────────────────
        pulse = 0.5 + 0.5 * math.sin(self._phase * 4.0 * math.pi)
        core_r = min_r + pulse * 2.5

        core_grad = QRadialGradient(center, core_r + 6)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 245))
        core_grad.setColorAt(0.35, QColor(235, 220, 190, 190))
        core_grad.setColorAt(0.75, QColor(212, 196, 168, 70))
        core_grad.setColorAt(1.0, QColor(212, 196, 168, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(core_grad))
        painter.drawEllipse(center, core_r + 6, core_r + 6)

        # Micro bright center point
        painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
        painter.drawEllipse(center, 2.2, 2.2)

        # ── 4. Elegant AUREX Accent ──────────────────────────────────────────
        painter.setFont(QFont("Segoe UI", 6, QFont.Weight.DemiBold))
        painter.setPen(QPen(QColor(212, 196, 168, 120)))
        painter.drawText(QRectF(0, h - 23, w, 14), Qt.AlignmentFlag.AlignCenter, "AUREX")


# ── Internal Window Control (Runs on Qt Main Thread) ─────────────────────────

def _find_main_window() -> Optional[QWidget]:
    global _main_window
    if _main_window is not None:
        return _main_window

    try:
        from ui import get_active_window
        win = get_active_window()
        if win is not None:
            _main_window = win
            return win
    except Exception:
        pass

    app = QApplication.instance()
    if app:
        for w in app.topLevelWidgets():
            if w.inherits("QMainWindow") or "MainWindow" in type(w).__name__:
                _main_window = w
                return w
    return None


def _do_shrink():
    global _pill_window, _main_window
    main_win = _find_main_window()
    if main_win is not None:
        main_win.hide()

    if _pill_window is None:
        _pill_window = ShrinkPillWindow()

    _pill_window.show()
    _pill_window.raise_()
    _pill_window.activateWindow()
    _pill_window.start_wave()


def _do_restore():
    global _pill_window, _main_window
    if _pill_window is not None:
        _pill_window.stop_wave()
        _pill_window.hide()

    main_win = _find_main_window()
    if main_win is not None:
        main_win.show()
        main_win.raise_()
        main_win.activateWindow()


# ── Public API (Safe to call from any thread or button) ──────────────────────

def shrink() -> bool:
    """Shrink AUREX into the compact floating pill bubble."""
    app = QApplication.instance()
    if not app:
        return False
    QTimer.singleShot(0, _do_shrink)
    return True


def restore() -> bool:
    """Restore AUREX from pill bubble back to full window."""
    app = QApplication.instance()
    if not app:
        return False
    QTimer.singleShot(0, _do_restore)
    return True


def toggle() -> bool:
    """Toggle between shrunk pill bubble and full window."""
    global _pill_window
    if _pill_window is not None and _pill_window.isVisible():
        return restore()
    else:
        return shrink()


# ── Plugin Declaration for Gemini Live ───────────────────────────────────────

PLUGIN = {
    "name": "shrink",
    "description": (
        "Shrink AUREX into a compact floating desktop pill bubble with a center-to-outwards radiant wave animation, "
        "or restore back to full window. ALWAYS invoke this tool (and NEVER minimize active desktop windows or call computer_settings) "
        "when user asks to: 'shrink', 'go to pill mode', 'mini mode', 'chote hojao', 'chota hojao', 'chhota hojao', "
        "'be small', 'small pill', 'bubble mode', 'desktop pill', 'restore', 'bade hojao', 'expand', 'full window', 'normal window'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Either 'shrink' (to go to pill mode), 'restore' (to bring back full window), or 'toggle'. Defaults to 'shrink'."
            }
        },
        "required": []
    }
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """
    Plugin execution entrypoint called by AUREX / Gemini Live.
    """
    action = str(parameters.get("action", "")).strip().lower()

    if any(k in action for k in ("restore", "expand", "bade", "bada", "baray", "full", "normal", "wapas", "wapis")):
        restore()
        result_text = "Restored AUREX to full window."
    elif any(k in action for k in ("toggle",)):
        toggle()
        result_text = "Toggled AUREX window mode."
    else:
        shrink()
        result_text = "Shrunk AUREX to compact floating desktop pill bubble."

    if player:
        try:
            player.write_log(f"AUREX: {result_text}")
        except Exception:
            pass

    return result_text
