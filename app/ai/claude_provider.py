"""Anthropic Claude Provider implementation for AUREX."""

import json
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class ClaudeProvider(AIProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.get("claude_api_key", "")
        self.model = model or settings.get("claude_model", "claude-3-5-sonnet-20241022")
        self.base_url = "https://api.anthropic.com/v1"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
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
            raise ValueError("Claude API key is not configured.")

        formatted_msgs = []
        for m in messages:
            formatted_msgs.append({"role": m["role"], "content": m["content"]})

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": formatted_msgs,
            "temperature": temperature
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/messages", data=data, headers=self._get_headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            content = resp_data.get("content", [])
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            return {"text": text, "tool_calls": [], "raw": resp_data}

    def transcribe_audio(self, audio_data: bytes, filename: str = "input.wav") -> str:
        return ""

    def health_check(self) -> bool:
        return bool(self.api_key)
