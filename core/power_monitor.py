"""
AUREX Core: System Power & Sleep/Wake Monitor
=============================================
Provides bulletproof detection for when the laptop/PC enters sleep or wakes up
from sleep/standby/hibernation/modern standby.

Key features:
1. Native Windows Power Message Hook (WM_POWERBROADCAST):
   Catches PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND, and PBT_APMSUSPEND.
2. Windows 8/10/11 RegisterSuspendResumeNotification:
   Explicitly registers top-level window handle for low-power state transitions.
3. Monotonic Time-Gap Heartbeat:
   Hardware-level time-jump detection that works across all power modes, S0 Modern
   Standby, and even if OS window messages are delayed or suppressed.
4. Auto-Shrink to Pill Mode:
   When configured (default: True), automatically restores/shrinks AUREX into
   the sleek floating pill bubble whenever the laptop turns on after sleep.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
import threading
import time
from typing import Callable, List, Optional

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

_OS = platform.system()

# Windows Power Broadcast Constants
WM_POWERBROADCAST          = 0x0218
PBT_APMSUSPEND             = 0x0004   # System is suspending execution
PBT_APMRESUMECRITICAL       = 0x0006   # Operation resuming after critical suspend
PBT_APMRESUMESUSPEND       = 0x0007   # Operation resuming from user input (lid open / key / power)
PBT_APMRESUMEAUTOMATIC     = 0x0012   # Operation resuming automatically on any wake
PBT_POWERSETTINGCHANGE     = 0x8013   # Power setting notification

DEVICE_NOTIFY_WINDOW_HANDLE = 0x00000000


if _OS == "Windows":
    from ctypes import wintypes

    class _WinMsg(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]


class _PowerNativeFilter(QAbstractNativeEventFilter):
    """Intercepts Windows WM_POWERBROADCAST messages at the application message pump."""

    def __init__(self, on_wake: Callable[[str], None], on_suspend: Callable[[str], None]):
        super().__init__()
        self._on_wake = on_wake
        self._on_suspend = on_suspend

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
                msg = _WinMsg.from_address(int(message))
                if msg.message == WM_POWERBROADCAST:
                    wp = int(msg.wParam)
                    if wp in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND, PBT_APMRESUMECRITICAL):
                        code = "RESUME_AUTO" if wp == PBT_APMRESUMEAUTOMATIC else "RESUME_USER"
                        self._on_wake(f"Windows WM_POWERBROADCAST ({code})")
                    elif wp == PBT_APMSUSPEND:
                        self._on_suspend("Windows WM_POWERBROADCAST (PBT_APMSUSPEND)")
        except Exception:
            pass
        return False, 0


class _HeartbeatThread(threading.Thread):
    """
    Monitors monotonic clock progression in the background.
    When a laptop is asleep, thread execution pauses while system hardware clock
    continues advancing. Upon wake, a sudden jump (delta > threshold) is detected
    immediately within 1-2 seconds of the laptop resuming.
    """

    def __init__(self, on_wake: Callable[[str], None], interval: float = 1.5, gap_threshold: float = 4.0):
        super().__init__(name="AurexPowerHeartbeat", daemon=True)
        self._on_wake = on_wake
        self._interval = interval
        self._gap_threshold = gap_threshold
        self._stop_event = threading.Event()

    def run(self):
        last_mono = time.monotonic()
        while not self._stop_event.is_set():
            time.sleep(self._interval)
            now = time.monotonic()
            delta = now - last_mono
            last_mono = now
            if delta >= self._gap_threshold:
                self._on_wake(f"Hardware Clock Jump ({delta:.1f}s sleep)")

    def stop(self):
        self._stop_event.set()


class PowerMonitor(QObject):
    """Central singleton controller for system power, sleep, and wake events."""

    system_resumed = pyqtSignal(str)     # Emitted on GUI thread when laptop wakes up
    system_suspended = pyqtSignal(str)   # Emitted on GUI thread when laptop goes to sleep

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._last_wake_time: float = 0.0
        self._native_filter: Optional[_PowerNativeFilter] = None
        self._h_power_notify = None
        self._heartbeat: Optional[_HeartbeatThread] = None
        self._wake_callbacks: List[Callable[[str], None]] = []

        # Default handler: switch to pill mode if configured
        self.system_resumed.connect(self._default_resume_handler)

        self._start_monitors()

    def _start_monitors(self):
        app = QApplication.instance()
        if app and _OS == "Windows":
            try:
                self._native_filter = _PowerNativeFilter(
                    on_wake=self._on_wake_event,
                    on_suspend=self._on_suspend_event,
                )
                app.installNativeEventFilter(self._native_filter)
            except Exception as e:
                print(f"[AUREX Power] Native event filter setup error: {e}")

        # Start monotonic clock heartbeat monitor
        self._heartbeat = _HeartbeatThread(on_wake=self._on_wake_event)
        self._heartbeat.start()

    def register_window(self, win):
        """Register a top-level window for Win32 suspend/resume notifications."""
        if _OS != "Windows":
            return
        try:
            hwnd = int(win.winId()) if hasattr(win, "winId") else int(win)
            user32 = ctypes.windll.user32
            if hasattr(user32, "RegisterSuspendResumeNotification"):
                from ctypes import wintypes
                user32.RegisterSuspendResumeNotification.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                user32.RegisterSuspendResumeNotification.restype = wintypes.HANDLE
                self._h_power_notify = user32.RegisterSuspendResumeNotification(hwnd, DEVICE_NOTIFY_WINDOW_HANDLE)
        except Exception as e:
            print(f"[AUREX Power] RegisterSuspendResumeNotification warning: {e}")

    def add_wake_callback(self, cb: Callable[[str], None]):
        """Register a custom callback to execute whenever the laptop resumes."""
        if cb not in self._wake_callbacks:
            self._wake_callbacks.append(cb)

    def _on_wake_event(self, reason: str):
        now = time.time()
        # Debounce multiple notifications within 3.0 seconds
        if now - self._last_wake_time < 3.0:
            return
        self._last_wake_time = now

        print(f"[AUREX] ⚡ System resume detected: {reason}")
        # Emit on Qt main thread via signal
        self.system_resumed.emit(reason)

        for cb in list(self._wake_callbacks):
            try:
                cb(reason)
            except Exception as e:
                print(f"[AUREX Power] Callback error: {e}")

    def _on_suspend_event(self, reason: str):
        print(f"[AUREX] 🌙 System entering sleep/suspend: {reason}")
        self.system_suspended.emit(reason)

    def _default_resume_handler(self, reason: str):
        """When laptop wakes from sleep, default to pill mode if enabled."""
        try:
            from memory.config_manager import get_start_in_pill
            if get_start_in_pill():
                from ui import shrink_app_to_pill
                # Call shrink cleanly
                shrink_app_to_pill()
        except Exception as e:
            print(f"[AUREX Power] Error executing resume pill switch: {e}")


# ── Global Singleton Access ──────────────────────────────────────────────────
_INSTANCE: Optional[PowerMonitor] = None


def init_power_monitor(win=None) -> PowerMonitor:
    """Initialize or return the global PowerMonitor singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PowerMonitor()
    if win is not None:
        _INSTANCE.register_window(win)
    return _INSTANCE


def get_power_monitor() -> Optional[PowerMonitor]:
    return _INSTANCE
