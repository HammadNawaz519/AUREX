"""Local LLM Provider (Ollama / Local OpenAI Compatible) for AUREX."""

import json
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class LocalProvider(AIProvider):
    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.base_url = (base_url or settings.get("local_api_base", "http://localhost:11434/v1")).rstrip("/")
        self.model = model or settings.get("local_model", "llama3")

    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            msg = resp_data["choices"][0]["message"]
            return {"text": msg.get("content") or "", "tool_calls": [], "raw": resp_data}

    def transcribe_audio(self, audio_data: bytes, filename: str = "input.wav") -> str:
        return ""

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/models")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False
