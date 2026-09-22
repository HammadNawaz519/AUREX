"""OpenAI Provider implementation for AUREX."""

import json
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.get("openai_api_key", "")
        self.model = model or settings.get("openai_model", "gpt-4o")
        self.base_url = "https://api.openai.com/v1"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Aurex/1.0"
        }

    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("OpenAI API key is not configured.")

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

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=data, headers=self._get_headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            msg = resp_data["choices"][0]["message"]
            raw_tools = msg.get("tool_calls") or []
            parsed_tools = []
            for t in raw_tools:
                f = t.get("function", {})
                args = f.get("arguments", "{}")
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except Exception:
                    args = {}
                parsed_tools.append({"name": f.get("name"), "arguments": args})
            return {"text": msg.get("content") or "", "tool_calls": parsed_tools, "raw": resp_data}

    def transcribe_audio(self, audio_data: bytes, filename: str = "input.wav") -> str:
        # Standard OpenAI Whisper transcription endpoint
        boundary = "----AurexOpenAIBoundary"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        }
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-1\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n"
        ).encode("utf-8") + audio_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(f"{self.base_url}/audio/transcriptions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")).get("text", "").strip()

    def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            req = urllib.request.Request(f"{self.base_url}/models", headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False
