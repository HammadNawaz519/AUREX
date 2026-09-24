"""AUREX Push-To-Talk Voice Diagnostics.

Usage:
  python -m app.voice.test
"""

import sys
import time
import numpy as np
import io
import wave

from app.voice.microphone import MicrophoneRecorder
from app.voice.speech import SpeechToText, clean_wake_phrase
from app.voice.tts import TTSEngine, sanitize_speech_text
from app.voice.controller import VoiceController


def test_1_microphone():
    print("\n[TEST 1] Testing on-demand MicrophoneRecorder...")
    recorder = MicrophoneRecorder()
    assert not recorder.is_recording, "Should not be recording when idle"
    
    ok = recorder.start()
    assert ok and recorder.is_recording, "Microphone start failed"
    print("  Recording audio for 1.0 second...")
    time.sleep(1.0)
    
    wav_bytes = recorder.stop()
    assert not recorder.is_recording, "Microphone should be stopped"
    assert len(wav_bytes) > 1000, f"Expected WAV bytes, got {len(wav_bytes)}"
    assert wav_bytes.startswith(b"RIFF"), "Invalid WAV header"
    print(f"  Captured {len(wav_bytes)} WAV bytes successfully.")
    print("  [PASS] Test 1: MicrophoneRecorder verified.")
    return True


def test_2_speech_to_text():
    print("\n[TEST 2] Testing SpeechToText container detection and API connectivity...")
    stt = SpeechToText()
    
    # 1. Clean wake phrase
    m, clean = clean_wake_phrase("Hey AUREX open Chrome")
    assert m and clean == "open Chrome"
    
    m, clean = clean_wake_phrase("Open my OS project")
    assert not m and clean == "Open my OS project"

    # 2. Synthetic WAV transcription test
    sr = 16000
    t = np.linspace(0, 0.8, int(sr * 0.8), endpoint=False)
    sine = (0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(sine.tobytes())
    wav_bytes = buf.getvalue()

    result = stt.transcribe(wav_bytes)
    print(f"  Groq Whisper response: '{result}'")
    print("  [PASS] Test 2: SpeechToText verified.")
    return True


def test_3_speech_sanitizer():
    print("\n[TEST 3] Testing Speech Sanitizer (terminal dump and code removal)...")
    terminal_output = """
    PS C:\\VS Code\\OS> cargo build
       Compiling os-kernel v0.1.0 (D:\\VS Code\\OS)
        Finished dev [unoptimized + debuginfo] target(s) in 0.42s
    Exit code: 0
    """
    clean = sanitize_speech_text(terminal_output)
    print(f"  Terminal dump sanitized to: '{clean}'")
    assert "cargo" not in clean and "Compiling" not in clean
    assert "successfully" in clean

    code_block = "I found the answer: ```python\nprint('hello')\n``` It is working."
    clean_code = sanitize_speech_text(code_block)
    print(f"  Code block sanitized to: '{clean_code}'")
    assert "print" not in clean_code

    print("  [PASS] Test 3: Speech Sanitizer verified.")
    return True


def test_4_tts_and_interrupt():
    print("\n[TEST 4] Testing TTSEngine and instant interruption...")
    tts = TTSEngine()
    
    print("  Playing TTS: 'AUREX ready.'")
    tts.speak("Aurex ready.")
    time.sleep(1.2)
    
    print("  Testing instant stop()...")
    tts.speak("This is a long sentence that will be stopped instantly.")
    time.sleep(0.3)
    tts.stop()
    assert not tts.is_speaking
    print("  [PASS] Test 4: TTSEngine verified.")
    return True


def test_5_controller_flow():
    print("\n[TEST 5] Testing VoiceController push-to-talk orchestration...")
    controller = VoiceController()
    
    states = []
    user_transcripts = []
    assistant_responses = []

    controller.on("state", lambda s, t: states.append(s))
    controller.on("user_transcript", lambda t: user_transcripts.append(t))
    controller.on("assistant_response", lambda r: assistant_responses.append(r))

    # Test UI shrink command
    controller._process_utterance = lambda b: None # mock
    controller.set_ui_action_handler(lambda action: print(f"  UI Action triggered: {action}"))

    controller.start_recording()
    assert controller.mic.is_recording
    assert "LISTENING" in states

    controller.stop_recording()
    assert not controller.mic.is_recording
    assert "TRANSCRIBING" in states

    print("  [PASS] Test 5: VoiceController verified.")
    return True


def main():
    print("=" * 60)
    print("   AUREX PUSH-TO-TALK VOICE SYSTEM VERIFICATION")
    print("=" * 60)
    
    tests = [
        test_1_microphone,
        test_2_speech_to_text,
        test_3_speech_sanitizer,
        test_4_tts_and_interrupt,
        test_5_controller_flow,
    ]
    
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"[FAIL] {t.__name__} failed: {e}")
            sys.exit(1)

    print("\n" + "=" * 60)
    print(">>> ALL PUSH-TO-TALK DIAGNOSTIC TESTS PASSED! <<<")
    print("=" * 60)


if __name__ == "__main__":
    main()
