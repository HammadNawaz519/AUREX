"""Google Gemini Provider implementation for AUREX."""

import json
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.get("gemini_api_key", "")
        self.model = model or settings.get("gemini_model", "gemini-1.5-flash")
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("Gemini API key is not configured.")

        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": m["content"]}]
            })

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature}
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            candidates = resp_data.get("candidates", [])
            text = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
            return {"text": text, "tool_calls": [], "raw": resp_data}

    def transcribe_audio(self, audio_data: bytes, filename: str = "input.wav") -> str:
        # Gemini multimodal audio transcription
        import base64
        b64 = base64.b64encode(audio_data).decode("utf-8")
        payload = {
            "contents": [{
                "parts": [
                    {"text": "Transcribe this audio strictly verbatim. Return only the transcription text."},
                    {"inlineData": {"mimeType": "audio/wav", "data": b64}}
                ]
            }]
        }
        url = f"{self.base_url}/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()

    def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            url = f"{self.base_url}/models?key={self.api_key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False
