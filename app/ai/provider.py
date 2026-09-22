"""Abstract Base AI Provider for AUREX."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class AIProvider(ABC):
    """Abstract interface for all AI service integrations."""

    @abstractmethod
    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        Execute chat completion.
        Returns:
            {
                "text": str,
                "tool_calls": List[{"name": str, "arguments": dict}],
                "raw": dict
            }
        """
        pass

    @abstractmethod
    def transcribe_audio(self, audio_data: bytes, filename: str = "input.wav") -> str:
        """
        Transcribe speech audio to text.
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        Verify provider connectivity and credentials.
        """
        pass
