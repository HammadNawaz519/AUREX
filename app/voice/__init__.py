"""AUREX Voice Subsystem — Spacebar Push-To-Talk, Double-Clap Trigger, and TTS."""

from app.voice.microphone import MicrophoneRecorder, get_microphone
from app.voice.speech import SpeechToText, get_stt, get_recognizer, SpeechRecognizer, clean_wake_phrase, WakeWordDetector
from app.voice.clap_detector import DoubleClapDetector
from app.voice.tts import TTSEngine, get_tts, TextToSpeech, sanitize_speech_text
from app.voice.controller import VoiceController, get_voice_controller

__all__ = [
    "MicrophoneRecorder",
    "get_microphone",
    "SpeechToText",
    "get_stt",
    "get_recognizer",
    "SpeechRecognizer",
    "clean_wake_phrase",
    "WakeWordDetector",
    "DoubleClapDetector",
    "TTSEngine",
    "get_tts",
    "TextToSpeech",
    "sanitize_speech_text",
    "VoiceController",
    "get_voice_controller",
]
