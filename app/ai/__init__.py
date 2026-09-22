"""AI Providers module for AUREX."""

import logging
from typing import Optional
from app.ai.provider import AIProvider
from app.ai.groq_provider import GroqProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.claude_provider import ClaudeProvider
from app.ai.local_provider import LocalProvider
from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_active_provider: Optional[AIProvider] = None


def get_ai_provider(provider_name: Optional[str] = None, force_refresh: bool = False) -> AIProvider:
    """
    Get the configured AI provider singleton.
    Falls back gracefully if the requested provider is unavailable.
    """
    global _active_provider
    if _active_provider is not None and not force_refresh and provider_name is None:
        return _active_provider

    settings = get_settings()
    name = (provider_name or settings.ai_provider).lower()

    provider: AIProvider
    if name == "groq":
        provider = GroqProvider()
    elif name == "openai":
        provider = OpenAIProvider()
    elif name == "gemini":
        provider = GeminiProvider()
    elif name == "claude":
        provider = ClaudeProvider()
    elif name == "local":
        provider = LocalProvider()
    else:
        logger.warning(f"Unknown AI provider '{name}', falling back to Groq.")
        provider = GroqProvider()

    _active_provider = provider
    return provider


__all__ = [
    "AIProvider",
    "GroqProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "ClaudeProvider",
    "LocalProvider",
    "get_ai_provider"
]
