"""
AUREX Plugin: Shrink to Floating Pill Bubble
============================================
Provides smooth, reliable shrinking of the main AUREX window into a sleek,
compact floating black desktop pill bubble with a center-to-outwards wave animation,
and seamless restoring back to the full window.
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QObject, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QBrush, QColor, QPen, QRadialGradient, QFont
)
from PyQt6.QtWidgets import QWidget, QApplication


# ── Global Singleton Instances ───────────────────────────────────────────────
_pill_window: Optional[ShrinkPillWindow] = None
_main_window: Optional[QWidget] = None
_is_transitioning: bool = False


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

        self._state: str = "SLEEPING"
        self._phase: float = 0.0
        self._restoring: bool = False
        self._timer: QTimer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps smooth wave
        self._timer.timeout.connect(self._on_tick)

        self._position_bottom_right()

    def set_state(self, state: str):
        """Update active state. Ripples only animate when listening or speaking."""
        self._state = (state or "").upper()
        if self._state in ("LISTENING", "SPEAKING"):
            self.start_wave()
        else:
            self.stop_wave()
        self.update()

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
            self._dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            delta = event.globalPosition().toPoint() - self._press_pos
            if delta.manhattanLength() > 4:
                self._dragging = True
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not getattr(self, "_dragging", False):
                if not getattr(self, "_restoring", False):
                    self._restoring = True
                    # Cleanly release any mouse grab and defer restore to the next event loop tick
                    try:
                        self.releaseMouse()
                    except Exception:
                        pass
                    QTimer.singleShot(10, restore)
            else:
                # Snap to nearest screen edge
                self._snap_to_edge()
            self._dragging = False
            event.accept()

    def _snap_to_edge(self):
        """Snap pill to the nearest screen edge corner for tidy positioning."""
        app = QApplication.instance()
        if not app:
            return
        screen = app.primaryScreen()
        if not screen:
            return
        ag = screen.availableGeometry()
        pos = self.frameGeometry().topLeft()
        cx = pos.x() + self.width() / 2
        cy = pos.y() + self.height() / 2
        margin_x, margin_y = 18, 30
        # Determine nearest horizontal & vertical edge
        snap_x = ag.left() + margin_x if cx < ag.center().x() else ag.right() - self.width() - margin_x
        snap_y = ag.top() + margin_y if cy < ag.center().y() else ag.bottom() - self.height() - margin_y
        self.move(snap_x, snap_y)

    def mouseDoubleClickEvent(self, event):
        if not getattr(self, "_restoring", False):
            self._restoring = True
            try:
                self.releaseMouse()
            except Exception:
                pass
            QTimer.singleShot(10, restore)
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

        # Ripple waves fade completely into the disc before reaching the word "AUREX"
        # The word AUREX sits at y = h - 23 (101px), which is 39px from center.
        # Setting max_ripple_r to 35px ensures waves fade out 4px clear above the text.
        max_ripple_r = (h - 23.0) - cy - 4.0
        min_r = 6.0
        wave_span = max_ripple_r - min_r

        # ── 1. Deep Jet-Black Circular Disc ──────────────────────────────────
        bg_grad = QRadialGradient(center, max_r)
        bg_grad.setColorAt(0.0, QColor(14, 16, 20, 252))
        bg_grad.setColorAt(0.65, QColor(6, 7, 10, 254))
        bg_grad.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.setBrush(QBrush(bg_grad))

        # Breathing outer border rim with warm beige/gold tone
        is_active = self._state in ("LISTENING", "SPEAKING")
        border_alpha = int(60 + 35 * math.sin(self._phase * 2.0 * math.pi)) if is_active else 45
        border_pen = QPen(QColor(212, 196, 168, border_alpha), 1.5)
        painter.setPen(border_pen)
        painter.drawEllipse(center, max_r, max_r)

        # ── 2. Concentric Waves Radiating from Center to Outwards ────────────
        # Ripples ONLY appear and animate when listening or speaking, and fade out
        # completely before reaching the word "AUREX"
        if is_active:
            num_waves = 4
            for i in range(num_waves):
                # Staggered phase offset for each wave ring
                prog = (self._phase + (i / float(num_waves))) % 1.0

                # Radius expands from min_r (center) up to max_ripple_r
                r = min_r + (prog ** 0.85) * wave_span

                # Opacity fades naturally and dissolves to 0 before hitting the text
                fade = max(0.0, 1.0 - prog)
                alpha = int(220 * (fade ** 1.4))

                if alpha > 3:
                    # Soft diffuse outer glow for each wave ring
                    glow_pen = QPen(QColor(212, 196, 168, int(alpha * 0.35)), 3.2)
                    painter.setPen(glow_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(center, r, r)

                    # Sharp luminous cream wave line
                    wave_pen = QPen(QColor(235, 222, 200, alpha), 1.5)
                    painter.setPen(wave_pen)
                    painter.drawEllipse(center, r, r)

        # ── 3. Pulsing Central Energy Nexus ──────────────────────────────────
        pulse = (0.5 + 0.5 * math.sin(self._phase * 4.0 * math.pi)) if is_active else 0.2
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


# ── Internal Window Control (Runs on Qt Main Thread via Signal Bridge) ──────

class _ShrinkBridge(QObject):
    shrink_sig = pyqtSignal()
    restore_sig = pyqtSignal()
    state_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.shrink_sig.connect(_do_shrink)
        self.restore_sig.connect(_do_restore)
        self.state_sig.connect(_do_set_state)


_bridge: Optional[_ShrinkBridge] = None


def _get_bridge() -> _ShrinkBridge:
    global _bridge
    if _bridge is None:
        _bridge = _ShrinkBridge()
        app = QApplication.instance()
        if app and app.thread():
            try:
                _bridge.moveToThread(app.thread())
            except Exception:
                pass
    return _bridge


def _do_set_state(state: str):
    global _pill_window
    if _pill_window is not None:
        _pill_window.set_state(state)


def set_pill_state(state: str) -> bool:
    """Thread-safe update of the pill bubble state (LISTENING, SPEAKING, SLEEPING)."""
    app = QApplication.instance()
    if not app:
        return False
    _get_bridge().state_sig.emit(state)
    return True


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
    return _main_window


def _do_shrink():
    global _pill_window, _main_window, _is_transitioning
    if _is_transitioning:
        return
    _is_transitioning = True
    try:
        main_win = _find_main_window()
        if main_win is not None:
            # If quick drawer is open, close/hide it so no animation gets stuck
            if hasattr(main_win, "_quick_drawer") and main_win._quick_drawer is not None:
                try:
                    main_win._quick_drawer.hide()
                    main_win._drawer_open = False
                except Exception:
                    pass
            main_win.hide()

        app = QApplication.instance()
        if app:
            for w in app.topLevelWidgets():
                if (w.inherits("QMainWindow") or "MainWindow" in type(w).__name__) and w != _pill_window:
                    w.hide()

        if _pill_window is None:
            _pill_window = ShrinkPillWindow()

        _pill_window._restoring = False
        cur_st = "SLEEPING"
        if main_win is not None and hasattr(main_win, "hud") and hasattr(main_win.hud, "state"):
            cur_st = getattr(main_win.hud, "state", "SLEEPING")
        _pill_window.set_state(cur_st)
        _pill_window.show()
        _pill_window.raise_()
        _pill_window.activateWindow()
    finally:
        _is_transitioning = False


def _do_restore():
    global _pill_window, _main_window, _is_transitioning
    if _is_transitioning:
        return
    _is_transitioning = True
    try:
        if _pill_window is not None:
            _pill_window.stop_wave()
            _pill_window.hide()

        main_win = _find_main_window()
        if main_win is not None:
            # Un-minimize and restore normal window state
            main_win.setWindowState(
                (main_win.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
            )
            main_win.showNormal()
            main_win.raise_()
            main_win.activateWindow()

            if sys.platform == "win32":
                try:
                    hwnd = int(main_win.winId())
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                except Exception:
                    pass

            if hasattr(main_win, "_apply_window_mask"):
                main_win._apply_window_mask()

            if hasattr(main_win, "hud") and main_win.hud is not None:
                main_win.hud._step_t = time.time()
                main_win.hud._last_t = time.time()
                main_win.hud.update()

            main_win.update()
        else:
            app = QApplication.instance()
            if app:
                for w in app.topLevelWidgets():
                    if (w.inherits("QMainWindow") or "MainWindow" in type(w).__name__) and w != _pill_window:
                        w.setWindowState(
                            (w.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
                        )
                        w.showNormal()
                        w.raise_()
                        w.activateWindow()
    finally:
        _is_transitioning = False


# ── Public API (100% thread-safe to call from any background worker thread) ──

def shrink() -> bool:
    """Shrink AUREX into the compact floating pill bubble."""
    app = QApplication.instance()
    if not app:
        return False
    _get_bridge().shrink_sig.emit()
    return True


def restore() -> bool:
    """Restore AUREX from pill bubble back to full window."""
    app = QApplication.instance()
    if not app:
        return False
    _get_bridge().restore_sig.emit()
    return True


def toggle() -> bool:
    """Toggle between shrunk pill bubble and full window."""
    global _pill_window
    if _pill_window is not None and _pill_window.isVisible():
        return restore()
    else:
        return shrink()


def get_state() -> str:
    """Returns 'pill' if currently shrunk, 'full' if full window is active."""
    global _pill_window
    if _pill_window is not None and _pill_window.isVisible():
        return "pill"
    return "full"


# ── Plugin Declaration for Gemini Live ───────────────────────────────────────

PLUGIN = {
    "name": "shrink",
    "description": (
        "Shrink AUREX into a compact floating desktop pill bubble with a center-to-outwards radiant wave animation, "
        "or restore it back to the full window. Can also toggle between the two modes, or check the current state. "
        "ALWAYS invoke this tool (and NEVER minimize active desktop windows or call computer_settings) "
        "when user says: "
        "shrink | go to pill mode | mini mode | hide | go small | chhota karo | chote hojao | chota hojao | "
        "chhota hojao | choti | be small | small pill | bubble mode | desktop pill | mini pill | "
        "dikha do pill | pill dikha | AUREX chhupa do | "
        "restore | show | expand | bade hojao | bada karo | wapas lao | wapas ao | "
        "normal | full window | show AUREX | full size | "
        "toggle | am I in pill mode | what mode | current mode | state."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "Action to perform. Options: "
                    "'shrink' — hide AUREX to compact pill bubble, "
                    "'restore' — bring AUREX back to full window, "
                    "'toggle' — switch between pill and full, "
                    "'state' — return whether currently in pill or full mode. "
                    "Defaults to 'shrink' if not specified."
                )
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

    # State query
    if any(k in action for k in ("state", "mode", "am i", "current", "status", "check")):
        current = get_state()
        result_text = f"AUREX is currently in {'pill (mini) mode' if current == 'pill' else 'full window mode'}."

    elif any(k in action for k in ("restore", "expand", "bade", "bada", "baray", "full", "normal",
                                   "wapas", "wapis", "show", "dikha", "back")):
        restore()
        result_text = "Restored AUREX to full window."

    elif any(k in action for k in ("toggle",)):
        toggle()
        state = get_state()
        result_text = f"Toggled AUREX — now in {'pill (mini) mode' if state == 'pill' else 'full window mode'}."

    else:
        shrink()
        result_text = "Shrunk AUREX to compact floating desktop pill bubble."

    if player:
        try:
            player.write_log(f"AUREX: {result_text}")
        except Exception:
            pass

    return result_text
