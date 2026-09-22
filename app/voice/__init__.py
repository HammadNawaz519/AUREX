"""Voice processing subsystem for AUREX."""

from app.voice.microphone import MicrophoneListener, get_microphone
from app.voice.speech import SpeechRecognizer, get_recognizer
from app.voice.wakeword import WakeWordDetector
from app.voice.tts import TextToSpeech, get_tts

__all__ = [
    "MicrophoneListener",
    "get_microphone",
    "SpeechRecognizer",
    "get_recognizer",
    "WakeWordDetector",
    "TextToSpeech",
    "get_tts"
]
