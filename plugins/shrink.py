"""
AUREX Plugin: Shrink to Floating Pill Bubble
============================================
Shrinks the main AUREX window into a compact floating black pill bubble and
restores it back to the full window.

The pill reacts to the LIVE VOLUME (microphone while you speak, the assistant's
voice while it speaks): rings and wave travel outward in proportion to the
strength of the sound. In silence only the centre dot is shown. The ripples
never reach the word "AUREX".

Performance / stability notes
-----------------------------
* The signal bridge lives on the GUI thread and uses real slots, so widgets are
  never created or shown from a worker thread (this was the cause of the
  blinking / momentary freezes).
* The pill only repaints (~30 fps) while there is actual sound, plus one final
  repaint to clear the rings. In silence it does not repaint at all.
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QPointF, QObject, pyqtSignal, pyqtSlot
)
from PyQt6.QtGui import (
    QPainter, QBrush, QColor, QPen, QRadialGradient, QFont
)
from PyQt6.QtWidgets import QWidget, QApplication


# ── Tuning ───────────────────────────────────────────────────────────────────
_GATE = 0.05        # volume below this = silence (raise to e.g. 0.08 if noisy)
_GAIN = 1.6         # boosts small microphone levels


# ── Global Singleton Instances ───────────────────────────────────────────────
_pill_window: Optional["ShrinkPillWindow"] = None
_main_window: Optional[QWidget] = None
_is_transitioning: bool = False


class ShrinkPillWindow(QWidget):
    """Compact frameless floating pill that reacts to live audio volume."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(48, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("AUREX Pill Mode\n• Click or Double-click to restore\n• Drag to reposition")

        self._state: str = "SLEEPING"
        self._phase: float = 0.0
        self._disp: float = 0.0           # smoothed volume strength 0..1
        self._dirty: bool = False
        self._last_t: float = time.monotonic()
        self._restoring: bool = False
        self._dragging: bool = False

        self._timer: QTimer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(8)       # 120+ FPS high-refresh rate
        self._timer.timeout.connect(self._on_tick)

        self._position_top_left()

    # The timer only runs while the pill is actually on screen.
    def showEvent(self, event):
        self._last_t = time.monotonic()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def start_wave(self):
        if not self._timer.isActive():
            self._timer.start()

    def stop_wave(self):
        self._timer.stop()

    def set_state(self, state: str):
        self._state = (state or "").upper()
        self.update()

    # ── live volume ──────────────────────────────────────────────────────────
    def _read_level(self) -> float:
        """Smoothed 0..1 level the HUD already computes from the audio threads."""
        win = _find_main_window()
        hud = getattr(win, "hud", None)
        if hud is None or getattr(hud, "muted", False):
            return 0.0
        try:
            return float(getattr(hud, "_amp_disp", 0.0))
        except Exception:
            return 0.0

    def _on_tick(self):
        now = time.monotonic()
        dt = max(0.001, min(0.05, now - self._last_t))
        self._last_t = now

        is_active = self._state in ("LISTENING", "SPEAKING")
        if is_active:
            lvl = min(1.0, self._read_level() * _GAIN)
            vol_boost = max(0.0, (lvl - _GATE) / (1.0 - _GATE))
            target = min(1.0, 0.32 + 0.68 * vol_boost)
            # Smooth attack and release tuned for 120 FPS
            rate = 14.0 if target > self._disp else 4.0
            self._disp += (target - self._disp) * (1.0 - math.exp(-rate * dt))
        else:
            self._disp += (0.0 - self._disp) * (1.0 - math.exp(-6.0 * dt))
            if self._disp < 0.005:
                self._disp = 0.0

        if self._disp > 0.0:
            # Butter-smooth outward travel at 120 FPS
            self._phase = (self._phase + dt * (0.35 + 0.9 * self._disp)) % 1.0
            self._dirty = True
            self.update()
        elif self._dirty:
            # one last repaint to clear the rings, then stay idle
            self._dirty = False
            self.update()

    # ── placement ────────────────────────────────────────────────────────────
    def _position_top_left(self):
        app = QApplication.instance()
        if not app:
            return
        screen = app.primaryScreen()
        if screen:
            ag = screen.availableGeometry()
            self.move(
                ag.left() + 24,
                ag.top() + 24
            )

    def _snap_to_edge(self):
        app = QApplication.instance()
        screen = app.primaryScreen() if app else None
        if not screen:
            return
        ag = screen.availableGeometry()
        pos = self.frameGeometry().topLeft()
        cx = pos.x() + self.width() / 2
        cy = pos.y() + self.height() / 2
        margin_x, margin_y = 18, 30
        snap_x = ag.left() + margin_x if cx < ag.center().x() else ag.right() - self.width() - margin_x
        snap_y = ag.top() + margin_y if cy < ag.center().y() else ag.bottom() - self.height() - margin_y
        self.move(snap_x, snap_y)

    # ── mouse ────────────────────────────────────────────────────────────────
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
            if not self._dragging:
                if not self._restoring:
                    self._restoring = True
                    QTimer.singleShot(10, restore)
            else:
                self._snap_to_edge()
            self._dragging = False
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if not self._restoring:
            self._restoring = True
            QTimer.singleShot(10, restore)
        event.accept()

    # ── painting ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        center = QPointF(cx, cy)
        max_r = min(w, h) / 2.0 - 2.0

        # Rings fade out clear of the outer rim.
        min_r = 7.5
        max_ripple_r = max_r - 2.0
        wave_span = max_ripple_r - min_r
        s = self._disp                      # 0 = silence, 1 = loud

        # 1. Compact Jet-black disc
        bg = QRadialGradient(center, max_r)
        bg.setColorAt(0.0, QColor(14, 16, 20, 252))
        bg.setColorAt(0.68, QColor(6, 7, 10, 254))
        bg.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(212, 196, 168, int(45 + 40 * s)), 1.2))
        painter.drawEllipse(center, max_r, max_r)

        # 2. Volume-driven rings: only when listening or speaking.
        #    Louder = travel further, shine brighter, move faster.
        if s > 0.0:
            reach = 0.3 + 0.7 * s
            num_waves = 4
            for i in range(num_waves):
                prog = (self._phase + i / float(num_waves)) % 1.0
                r = min_r + (prog ** 0.85) * wave_span * reach
                alpha = int(220 * ((1.0 - prog) ** 1.4) * (s ** 0.7))
                if alpha > 3:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(212, 196, 168, int(alpha * 0.35)), 2.4))
                    painter.drawEllipse(center, r, r)
                    painter.setPen(QPen(QColor(235, 222, 200, alpha), 1.2))
                    painter.drawEllipse(center, r, r)

        # 3. Centre dot: prominent, glowing, centered in small black disc
        core_r = min_r + s * 2.5
        glow_r = core_r + 3.5
        core = QRadialGradient(center, glow_r)
        core.setColorAt(0.0, QColor(255, 255, 255, 245))
        core.setColorAt(0.35, QColor(235, 220, 190, 190))
        core.setColorAt(0.75, QColor(212, 196, 168, 70))
        core.setColorAt(1.0, QColor(212, 196, 168, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(core))
        painter.drawEllipse(center, glow_r, glow_r)
        painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
        painter.drawEllipse(center, 3.8, 3.8)

        painter.end()


# ── Internal Window Control (always runs on the Qt GUI thread) ───────────────

class _ShrinkBridge(QObject):
    shrink_sig = pyqtSignal()
    restore_sig = pyqtSignal()
    state_sig = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            # Live on the GUI thread FIRST, so slots below never run on a worker.
            self.moveToThread(app.thread())
        self.shrink_sig.connect(self._on_shrink)
        self.restore_sig.connect(self._on_restore)
        self.state_sig.connect(self._on_state)

    @pyqtSlot()
    def _on_shrink(self):
        _do_shrink()

    @pyqtSlot()
    def _on_restore(self):
        _do_restore()

    @pyqtSlot(str)
    def _on_state(self, state: str):
        _do_set_state(state)


_bridge: Optional[_ShrinkBridge] = None


def _get_bridge() -> _ShrinkBridge:
    global _bridge
    if _bridge is None:
        _bridge = _ShrinkBridge()
    return _bridge


def _do_set_state(state: str):
    if _pill_window is not None:
        _pill_window.set_state(state)


def set_pill_state(state: str) -> bool:
    """Thread-safe update of the pill state (LISTENING, SPEAKING, SLEEPING...)."""
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
    global _pill_window, _is_transitioning
    if _is_transitioning:
        return
    _is_transitioning = True
    try:
        main_win = _find_main_window()
        if main_win is not None:
            # Close the quick drawer so no animation gets stuck
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
    global _pill_window, _is_transitioning
    if _is_transitioning:
        return
    _is_transitioning = True
    try:
        if _pill_window is not None:
            _pill_window.stop_wave()
            _pill_window.hide()

        main_win = _find_main_window()
        if main_win is not None:
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


# ── Public API (thread-safe to call from any worker thread) ──────────────────

def shrink() -> bool:
    """Shrink AUREX into the compact floating pill bubble."""
    app = QApplication.instance()
    if not app:
        return False
    _get_bridge().shrink_sig.emit()
    return True


def restore() -> bool:
    """Restore AUREX from pill bubble back to the full window."""
    app = QApplication.instance()
    if not app:
        return False
    _get_bridge().restore_sig.emit()
    return True


def toggle() -> bool:
    """Toggle between shrunk pill bubble and full window."""
    if _pill_window is not None and _pill_window.isVisible():
        return restore()
    return shrink()


def get_state() -> str:
    """Returns 'pill' if currently shrunk, 'full' if the full window is active."""
    if _pill_window is not None and _pill_window.isVisible():
        return "pill"
    return "full"


# ── Plugin Declaration for Gemini Live ───────────────────────────────────────

PLUGIN = {
    "name": "shrink",
    "description": (
        "Shrink AUREX into a compact floating desktop pill bubble whose rings react to live voice volume, "
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
    """Plugin execution entrypoint called by AUREX / Gemini Live."""
    action = str(parameters.get("action", "")).strip().lower()

    if any(k in action for k in ("state", "mode", "am i", "current", "status", "check")):
        current = get_state()
        result_text = f"AUREX is currently in {'pill (mini) mode' if current == 'pill' else 'full window mode'}."

    elif any(k in action for k in ("restore", "expand", "bade", "bada", "baray", "full", "normal",
                                   "wapas", "wapis", "show", "dikha", "back")):
        restore()
        result_text = "Restored AUREX to full window."

    elif "toggle" in action:
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