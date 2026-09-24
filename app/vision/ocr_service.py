"""
OCR Service for AUREX.
Uses Windows MSOCR (WinRT) as primary, Tesseract as secondary, and
Pillow+pytesseract as tertiary fallback.
All methods return plain UTF-8 text.
"""
import logging
import threading
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()


class OCRService:
    """Multi-backend OCR with graceful fallback chain."""

    def __init__(self):
        self._backend: str = "none"
        self._init_backend()

    def _init_backend(self):
        # Try Windows.Media.Ocr (WinRT) first — highest quality, no install
        try:
            import asyncio
            import winrt.windows.media.ocr as _ocr  # type: ignore
            import winrt.windows.globalization as _glob  # type: ignore
            self._backend = "winrt"
            logger.info("OCR: Windows.Media.Ocr (WinRT) initialized.")
            return
        except Exception:
            pass

        # Try pytesseract
        try:
            import pytesseract  # type: ignore
            pytesseract.get_tesseract_version()
            self._backend = "tesseract"
            logger.info("OCR: Tesseract backend initialized.")
            return
        except Exception:
            pass

        logger.warning("OCR: No backend available. Text extraction will be limited.")
        self._backend = "none"

    @property
    def available(self) -> bool:
        return self._backend != "none"

    def extract_text(self, image: Image.Image) -> str:
        """Extract all text from a PIL Image. Returns plain string."""
        with _LOCK:
            if self._backend == "winrt":
                return self._ocr_winrt(image)
            elif self._backend == "tesseract":
                return self._ocr_tesseract(image)
            return ""

    def extract_structured(self, image: Image.Image) -> list:
        """Return list of {text, bounds} dicts for downstream element detection."""
        with _LOCK:
            if self._backend == "tesseract":
                return self._tesseract_structured(image)
            # WinRT also gives word-level bounding boxes
            if self._backend == "winrt":
                return self._winrt_structured(image)
            return []

    # ─── WinRT backend ──────────────────────────────────────────────────────

    def _ocr_winrt(self, image: Image.Image) -> str:
        try:
            import asyncio
            import io
            import winrt.windows.media.ocr as winrt_ocr
            import winrt.windows.globalization as winrt_glob
            import winrt.windows.graphics.imaging as winrt_img
            import winrt.windows.storage.streams as winrt_streams

            engine = winrt_ocr.OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                engine = winrt_ocr.OcrEngine.try_create_from_language(
                    winrt_glob.Language("en-US")
                )

            async def _run():
                buf = io.BytesIO()
                image.convert("RGBA").save(buf, format="PNG")
                buf.seek(0)
                ra_stream = winrt_streams.InMemoryRandomAccessStream()
                writer = winrt_streams.DataWriter(ra_stream)
                writer.write_bytes(buf.read())
                await writer.store_async()
                await writer.flush_async()
                ra_stream.seek(0)

                decoder = await winrt_img.BitmapDecoder.create_async(ra_stream)
                bitmap = await decoder.get_software_bitmap_converted_async(
                    winrt_img.BitmapPixelFormat.BGRA8,
                    winrt_img.BitmapAlphaMode.PREMULTIPLIED
                )
                result = await engine.recognize_async(bitmap)
                return result.text or ""

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already in async event loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    text = pool.submit(lambda: asyncio.run(_run())).result()
            else:
                text = asyncio.run(_run())
            return text
        except Exception as e:
            logger.warning(f"WinRT OCR failed: {e}; falling back to tesseract")
            self._backend = "tesseract"
            return self._ocr_tesseract(image)

    def _winrt_structured(self, image: Image.Image) -> list:
        # Simplified: return just text for now, structured via tesseract
        text = self._ocr_winrt(image)
        if text:
            return [{"text": text, "bounds": (0, 0, image.width, image.height)}]
        return []

    # ─── Tesseract backend ──────────────────────────────────────────────────

    def _ocr_tesseract(self, image: Image.Image) -> str:
        try:
            import pytesseract  # type: ignore
            return pytesseract.image_to_string(image, config="--psm 3")
        except Exception as e:
            logger.warning(f"Tesseract OCR failed: {e}")
            return ""

    def _tesseract_structured(self, image: Image.Image) -> list:
        try:
            import pytesseract  # type: ignore
            data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                config="--psm 3"
            )
            results = []
            n = len(data["text"])
            for i in range(n):
                txt = data["text"][i].strip()
                conf = float(data["conf"][i]) if data["conf"][i] != "-1" else 0.0
                if txt and conf > 30:
                    x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                    results.append({
                        "text": txt,
                        "bounds": (x, y, x + w, y + h),
                        "confidence": conf / 100.0,
                    })
            return results
        except Exception as e:
            logger.warning(f"Tesseract structured OCR failed: {e}")
            return []

    @property
    def available(self) -> bool:
        return self._backend != "none"


_instance: Optional[OCRService] = None

def get_ocr_service() -> OCRService:
    global _instance
    if _instance is None:
        _instance = OCRService()
    return _instance
