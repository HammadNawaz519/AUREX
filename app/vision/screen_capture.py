"""
Screen Capture Service for AUREX.
Uses Windows DXGI Desktop Duplication (via mss) as primary method,
with Pillow ImageGrab as fallback. Returns PIL Images.
"""
import logging
import threading
import time
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()


def ensure_interactive_desktop():
    """Ensure current thread is attached to the active user desktop station."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


class ScreenCaptureService:
    """Fast screen capture using Pillow (all_screens=True), MSS, and Qt with interactive desktop attachment."""

    def __init__(self):
        self._mss = None
        self._last_capture_time: float = 0.0
        self._min_interval: float = 0.15   # max ~6 fps passive
        self._last_image: Optional[Image.Image] = None
        self._change_threshold: float = 0.02  # 2% pixel change = significant
        self._init_mss()

    def _init_mss(self):
        try:
            import mss
            self._mss = mss.mss()
            logger.info("Screen capture: MSS (DXGI) initialized.")
        except Exception:
            logger.warning("MSS not available; will use Pillow ImageGrab fallback.")

    def capture(self, region: Optional[Tuple[int,int,int,int]] = None) -> Optional[Image.Image]:
        """
        Capture screen or a region.
        region: (left, top, right, bottom) in screen pixels, or None for full screen.
        Returns PIL Image in RGB.
        """
        with _LOCK:
            ensure_interactive_desktop()

            # 1. Try Pillow ImageGrab with all_screens=True (most resilient across multi-monitor & Windows 11)
            try:
                img = self._capture_pillow(region)
                if img is not None:
                    ext = img.getextrema()
                    # Ensure image is not pure black
                    if ext != ((0, 0), (0, 0), (0, 0)):
                        self._last_image = img
                        return img
            except Exception as e:
                logger.debug(f"Pillow capture failed: {e}")

            # 2. Try MSS
            if self._mss:
                try:
                    img = self._capture_mss(region)
                    if img is not None:
                        ext = img.getextrema()
                        if ext != ((0, 0), (0, 0), (0, 0)):
                            self._last_image = img
                            return img
                except Exception as e:
                    logger.debug(f"MSS capture failed: {e}")

            # 3. Fallback to Qt capture
            img = self._capture_qt(region)
            if img is not None:
                self._last_image = img
                return img

            return self._last_image

    def _capture_qt(self, region: Optional[Tuple[int,int,int,int]] = None) -> Optional[Image.Image]:
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QGuiApplication, QImage
            app = QApplication.instance()
            if not app:
                return None
            screen = QGuiApplication.primaryScreen()
            if not screen:
                return None
            if region:
                left, top, right, bottom = region
                pixmap = screen.grabWindow(0, left, top, right - left, bottom - top)
            else:
                pixmap = screen.grabWindow(0)

            if pixmap.isNull():
                return None

            qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
            w, h = qimg.width(), qimg.height()
            b = bytes(qimg.constBits())
            return Image.frombuffer("RGB", (w, h), b, "raw", "RGB", qimg.bytesPerLine(), 1)
        except Exception:
            return None

    def _capture_mss(self, region: Optional[Tuple[int,int,int,int]]) -> Optional[Image.Image]:
        import mss
        sct = self._mss
        if region:
            left, top, right, bottom = region
            mon = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        else:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

        sct_img = sct.grab(mon)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        return img

    def _capture_pillow(self, region: Optional[Tuple[int,int,int,int]]) -> Optional[Image.Image]:
        from PIL import ImageGrab
        if region:
            img = ImageGrab.grab(bbox=region, all_screens=True)
        else:
            img = ImageGrab.grab(all_screens=True)
        return img.convert("RGB")

    def capture_window(self, hwnd: int) -> Optional[Image.Image]:
        """Capture a specific window by HWND (Windows only)."""
        try:
            import win32gui
            import win32ui
            import win32con
            from ctypes import windll

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            w = right - left
            h = bottom - top
            if w <= 0 or h <= 0:
                return None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            save_bmp = win32ui.CreateBitmap()
            save_bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(save_bmp)

            result = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)

            bmpinfo = save_bmp.GetInfo()
            bmpstr = save_bmp.GetBitmapBits(True)

            img = Image.frombuffer(
                "RGB",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr, "raw", "BGRX", 0, 1
            )

            win32gui.DeleteObject(save_bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            return img
        except Exception as e:
            logger.warning(f"Window capture failed for HWND {hwnd}: {e}")
            return self.capture()

    def has_significant_change(self, new_image: Image.Image) -> bool:
        """Compare new capture to last – returns True if screen changed significantly."""
        if self._last_image is None:
            return True
        try:
            import numpy as np
            prev = np.array(self._last_image.resize((160, 90))).astype(float)
            curr = np.array(new_image.resize((160, 90))).astype(float)
            diff = np.abs(prev - curr).mean() / 255.0
            return diff > self._change_threshold
        except Exception:
            return True

    def get_active_window_hwnd(self) -> Optional[int]:
        """Return HWND of the currently focused user window (skipping AUREX floating widget)."""
        ensure_interactive_desktop()
        try:
            import win32gui
            import win32con
            hwnd = win32gui.GetForegroundWindow()
            curr = hwnd
            while curr:
                if win32gui.IsWindowVisible(curr):
                    title = win32gui.GetWindowText(curr)
                    if title and "aurex" not in title.lower():
                        return curr
                curr = win32gui.GetWindow(curr, win32con.GW_HWNDNEXT)
            return hwnd
        except Exception:
            return None

    def get_active_window_title(self) -> str:
        """Return title of currently focused user window (skipping AUREX floating widget)."""
        ensure_interactive_desktop()
        try:
            import win32gui
            import win32con
            hwnd = win32gui.GetForegroundWindow()
            curr = hwnd
            while curr:
                if win32gui.IsWindowVisible(curr):
                    title = win32gui.GetWindowText(curr)
                    if title and "aurex" not in title.lower():
                        return title
                curr = win32gui.GetWindow(curr, win32con.GW_HWNDNEXT)
            return win32gui.GetWindowText(hwnd) or "Desktop"
        except Exception:
            return "Desktop"

    def get_screen_size(self) -> Tuple[int, int]:
        try:
            import win32api
            return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
        except Exception:
            return 1920, 1080


_service: Optional[ScreenCaptureService] = None

def get_screen_capture_service() -> ScreenCaptureService:
    global _service
    if _service is None:
        _service = ScreenCaptureService()
    return _service
