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


class ScreenCaptureService:
    """Fast screen capture using MSS (DXGI-backed) with ImageGrab fallback."""

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
            try:
                if self._mss:
                    return self._capture_mss(region)
                return self._capture_pillow(region)
            except Exception as e:
                logger.error(f"Screen capture failed: {e}")
                return None

    def _capture_mss(self, region: Optional[Tuple[int,int,int,int]]) -> Image.Image:
        import mss
        sct = self._mss
        if region:
            left, top, right, bottom = region
            mon = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        else:
            mon = sct.monitors[0]  # full virtual desktop

        sct_img = sct.grab(mon)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        self._last_image = img
        return img

    def _capture_pillow(self, region: Optional[Tuple[int,int,int,int]]) -> Image.Image:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=region)
        img = img.convert("RGB")
        self._last_image = img
        return img

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

            # Use PrintWindow for off-screen windows
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
        """Return HWND of the currently focused window."""
        try:
            import win32gui
            return win32gui.GetForegroundWindow()
        except Exception:
            return None

    def get_active_window_title(self) -> str:
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

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
