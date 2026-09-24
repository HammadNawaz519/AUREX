"""AUREX Voice Processing Subsystem (Modular Clean Architecture)."""

from app.voice.voice_state import VoiceState, VoiceStateMachine
from app.voice.microphone import MicrophoneEngine, MicrophoneListener, MicrophoneDevice, get_microphone
from app.voice.vad import VoiceActivityDetector, VADState
from app.voice.wake_engine import WakeEngine, DoubleClapDetector, match_wake_phrase
from app.voice.stt import STTEngine, GroqSTT, LocalSTT, get_stt
from app.voice.tts import TTSEngine, TextToSpeech, get_tts
from app.voice.local_router import FastLocalRouter, ConversationContext
from app.voice.conversation import ConversationManager, get_conversation_manager
from app.voice.health import VoiceHealth, get_voice_health

# Backward-compatibility adapters
from app.voice.speech import SpeechRecognizer, get_recognizer
from app.voice.wakeword import WakeWordDetector, AcousticWakeService, get_acoustic_wake_service

__all__ = [
    "VoiceState",
    "VoiceStateMachine",
    "MicrophoneEngine",
    "MicrophoneListener",
    "MicrophoneDevice",
    "get_microphone",
    "VoiceActivityDetector",
    "VADState",
    "WakeEngine",
    "DoubleClapDetector",
    "match_wake_phrase",
    "STTEngine",
    "GroqSTT",
    "LocalSTT",
    "get_stt",
    "TTSEngine",
    "TextToSpeech",
    "get_tts",
    "FastLocalRouter",
    "ConversationContext",
    "ConversationManager",
    "get_conversation_manager",
    "VoiceHealth",
    "get_voice_health",
    "SpeechRecognizer",
    "get_recognizer",
    "WakeWordDetector",
    "AcousticWakeService",
    "get_acoustic_wake_service",
]
