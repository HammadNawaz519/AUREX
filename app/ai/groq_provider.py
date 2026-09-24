"""Groq AI Provider integration for AUREX.

High-speed LLM inference and Whisper speech-to-text.
"""

import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class GroqProvider(AIProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self.base_url = "https://api.groq.com/openai/v1"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Aurex/1.0"
        }

    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """Send chat completion to Groq with retry logic."""
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = self._get_headers()
        headers["Content-Type"] = "application/json"

        max_retries = 3
        backoff = 1.0

        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=data_bytes,
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    choice = resp_data["choices"][0]["message"]
                    text_content = choice.get("content") or ""
                    
                    raw_tool_calls = choice.get("tool_calls") or []
                    parsed_tool_calls = []
                    for tc in raw_tool_calls:
                        func = tc.get("function", {})
                        fname = func.get("name")
                        fargs_raw = func.get("arguments", "{}")
                        try:
                            fargs = json.loads(fargs_raw) if isinstance(fargs_raw, str) else fargs_raw
                        except Exception:
                            fargs = {}
                        parsed_tool_calls.append({"name": fname, "arguments": fargs})

                    return {
                        "text": text_content,
                        "tool_calls": parsed_tool_calls,
                        "raw": resp_data
                    }

            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                logger.warning(f"Groq API HTTP error {e.code}: {err_body}")
                if e.code == 429 and attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                # If specific model rate limited or unavailable, try fallback model
                if e.code == 429 and self.model != "openai/gpt-oss-20b":
                    self.model = "openai/gpt-oss-20b"
                    continue
                raise RuntimeError(f"Groq API Error {e.code}: {err_body}")
            except Exception as e:
                logger.error(f"Groq request failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise

        raise RuntimeError("Groq API request failed after maximum retries.")

    def transcribe_audio(self, audio_data: bytes, filename: str = "input.wav") -> str:
        """
        Transcribe audio using Groq Whisper API (whisper-large-v3-turbo).
        Uses persistent requests.Session for ultra-low latency (<250ms).
        """
        if not audio_data or len(audio_data) < 300:
            return ""

        content_type = "audio/wav"
        if filename.endswith(".webm") or audio_data.startswith(b"\x1aE\xdf\xa3") or audio_data.startswith(b"\x1a\x45\xdf\xa3"):
            filename = "audio.webm"
            content_type = "audio/webm"
        elif filename.endswith(".mp3"):
            content_type = "audio/mp3"

        try:
            if not hasattr(self, "_http_session") or self._http_session is None:
                import requests
                self._http_session = requests.Session()

            files = {
                "file": (filename, audio_data, content_type),
                "model": (None, "whisper-large-v3-turbo"),
                "language": (None, "en"),
                "response_format": (None, "json"),
            }
            headers = {"Authorization": f"Bearer {self.api_key}"}

            resp = self._http_session.post(
                f"{self.base_url}/audio/transcriptions",
                headers=headers,
                files=files,
                timeout=12
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("text", "").strip()
            else:
                logger.error(f"Groq audio transcription failed: {resp.status_code} - {resp.text}")
                return ""
        except Exception as e:
            logger.error(f"Error in Whisper audio transcription: {e}")
            return ""

    def health_check(self) -> bool:
        """Test Groq API connectivity."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models",
                headers=self._get_headers(),
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Groq health check failed: {e}")
            return False
