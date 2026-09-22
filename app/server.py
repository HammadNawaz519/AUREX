"""Local HTTP API Server for AUREX TypeScript Voice Surface.

Provides zero-dependency REST endpoints on http://127.0.0.1:8765 to execute commands,
manage voice transcription, and query agent status with full CORS support.
"""

import io
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any
from urllib.parse import urlparse

from app.core.agent import get_agent
from app.voice.speech import get_recognizer
from app.config.settings import get_settings

logger = logging.getLogger("AurexServer")

_widget_action_handler = None

def set_widget_action_handler(handler):
    global _widget_action_handler
    _widget_action_handler = handler

def trigger_widget_action(action: str):
    if _widget_action_handler:
        try:
            _widget_action_handler(action)
        except Exception as e:
            logger.warning(f"Widget action dispatch error: {e}")


class AurexAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep server logs concise
        logger.info(f"{self.command} {self.path} - {args[0] if args else ''}")

    def _set_cors_headers(self, status: int = 200, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Type", content_type)
        self.end_headers()

    def do_OPTIONS(self):
        self._set_cors_headers(204)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            settings = get_settings()
            payload = {
                "status": "ONLINE",
                "agent": "AUREX",
                "provider": settings.ai_provider,
                "privacy_mode": settings.privacy_mode
            }
            self._set_cors_headers(200)
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        # Serve static UI files from ui/dist
        from pathlib import Path
        import mimetypes
        ui_dist = Path(__file__).resolve().parent.parent / "ui" / "dist"

        req_path = parsed.path.lstrip("/")
        if not req_path:
            req_path = "index.html"

        target_file = (ui_dist / req_path).resolve()

        # Prevent path traversal outside ui_dist
        try:
            target_file.relative_to(ui_dist)
        except ValueError:
            self._set_cors_headers(403)
            self.wfile.write(b"Forbidden")
            return

        if not target_file.is_file():
            # SPA Fallback to index.html
            target_file = ui_dist / "index.html"

        if target_file.is_file():
            content_type, _ = mimetypes.guess_type(str(target_file))
            if not content_type:
                content_type = "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                content_type += "; charset=utf-8"

            try:
                data = target_file.read_bytes()
                self._set_cors_headers(200, content_type=content_type)
                self.wfile.write(data)
            except Exception as e:
                logger.error(f"Error serving static file {target_file}: {e}")
                self._set_cors_headers(500)
                self.wfile.write(b"Server Error")
        else:
            self._set_cors_headers(404)
            self.wfile.write(json.dumps({"error": "UI build not found. Run 'npm run build' in /ui."}).encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))

        if parsed.path == "/api/command":
            raw_body = self.rfile.read(content_length)
            try:
                data = json.loads(raw_body.decode("utf-8"))
                command_text = data.get("command", "").strip()
                if not command_text:
                    self._set_cors_headers(400)
                    self.wfile.write(json.dumps({"error": "Empty command"}).encode("utf-8"))
                    return

                lower_cmd = command_text.lower()
                if any(p in lower_cmd for p in ["come up", "bring up", "come to front", "pop up", "wake up"]):
                    trigger_widget_action("come_up")
                    response_text = "I am here on top of your apps."
                elif any(p in lower_cmd for p in ["go back", "send to back", "hide behind", "go to wallpaper", "back to wallpaper"]):
                    trigger_widget_action("go_back")
                    response_text = "Pinned back to your desktop wallpaper."
                else:
                    agent = get_agent()
                    response_text = agent.process_input(command_text)

                self._set_cors_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "command": command_text,
                    "response": response_text
                }).encode("utf-8"))

            except Exception as e:
                logger.error(f"Error handling /api/command: {e}")
                self._set_cors_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/voice":
            audio_bytes = self.rfile.read(content_length)
            try:
                rec = get_recognizer()
                transcript = rec.transcribe(audio_bytes)
                if not transcript:
                    self._set_cors_headers(200)
                    self.wfile.write(json.dumps({
                        "success": False,
                        "transcript": "",
                        "response": "No speech detected. Please speak clearly and try again."
                    }).encode("utf-8"))
                    return

                lower_trans = transcript.lower()
                if any(p in lower_trans for p in ["come up", "bring up", "come to front", "pop up", "wake up"]):
                    trigger_widget_action("come_up")
                    response_text = "I am here on top of your apps."
                elif any(p in lower_trans for p in ["go back", "send to back", "hide behind", "go to wallpaper", "back to wallpaper"]):
                    trigger_widget_action("go_back")
                    response_text = "Pinned back to your desktop wallpaper."
                else:
                    agent = get_agent()
                    response_text = agent.process_input(transcript)

                self._set_cors_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "transcript": transcript,
                    "response": response_text
                }).encode("utf-8"))

            except Exception as e:
                logger.error(f"Error handling /api/voice: {e}")
                self._set_cors_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/api/widget/action":
            raw_body = self.rfile.read(content_length)
            try:
                data = json.loads(raw_body.decode("utf-8"))
                action = data.get("action", "")
                trigger_widget_action(action)
                self._set_cors_headers(200)
                self.wfile.write(json.dumps({"success": True, "action": action}).encode("utf-8"))
            except Exception as e:
                self._set_cors_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        else:
            self._set_cors_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))


def launch_desktop_window(url: str):
    """Launch the TypeScript Voice Surface in a dedicated desktop app window."""
    import os
    import shutil
    import subprocess
    import webbrowser

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in edge_paths:
        if os.path.exists(p):
            try:
                subprocess.Popen([p, f"--app={url}", "--window-size=920,620"])
                return
            except Exception:
                pass

    chrome_path = shutil.which("chrome") or shutil.which("google-chrome")
    if chrome_path:
        try:
            subprocess.Popen([chrome_path, f"--app={url}", "--window-size=920,620"])
            return
        except Exception:
            pass

    webbrowser.open(url)


def run_server(port: int = 8765, open_browser: bool = False):
    server = HTTPServer(("127.0.0.1", port), AurexAPIHandler)
    url = f"http://127.0.0.1:{port}"
    logger.info(f"AUREX Local Agent API server running on {url}")

    if open_browser:
        threading.Timer(0.8, launch_desktop_window, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_server(open_browser=True)
