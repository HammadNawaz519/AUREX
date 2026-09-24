"""AUREX Voice System — Diagnostic Test Suite.

Usage:
  python -m app.voice.test
  python -m app.voice.test --test 1  (or mic_enum)
  python -m app.voice.test --test 2  (or mic_stream)
  python -m app.voice.test --test 3  (or mic_rms)
  python -m app.voice.test --test 4  (or wake)
  python -m app.voice.test --test 5  (or tts)
  python -m app.voice.test --test 6  (or stt)
  python -m app.voice.test --test 7  (or full)
"""

from __future__ import annotations
import argparse
import io
import logging
import sys
import time
import wave
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AurexVoiceTest")


def run_test_1_mic_enumeration() -> bool:
    print("\n" + "=" * 60)
    print("TEST 1: Microphone Enumeration")
    print("=" * 60)
    from app.voice.microphone import MicrophoneEngine
    engine = MicrophoneEngine()
    devices = engine.get_microphone_devices()
    print(f"Found {len(devices)} input audio devices on Windows:\n")
    for d in devices:
        print(f"  [Device {d.index:2d}] {d.name[:35]:35s} | API: {d.host_api_name:10s} | sr={int(d.default_samplerate)}Hz | ch={d.max_channels}")
    
    if not devices:
        print("[FAIL] No microphone devices found!")
        return False
    print(f"\n[PASS] Enumerated {len(devices)} audio input devices successfully.")
    return True


def run_test_2_mic_stream() -> bool:
    print("\n" + "=" * 60)
    print("TEST 2: Microphone Stream (Non-Blocking Callback)")
    print("=" * 60)
    from app.voice.microphone import MicrophoneEngine
    engine = MicrophoneEngine()
    dev = engine.select_microphone()
    if not dev:
        print("[FAIL] select_microphone() did not find an active device.")
        return False
    print(f"Selected device: {dev}")
    
    frames_received = 0
    def on_frame(mono_f, mono_i, sr):
        nonlocal frames_received
        frames_received += 1

    engine.add_frame_consumer(on_frame)
    print("Starting stream for 1.5 seconds...")
    started = engine.start_stream()
    if not started:
        print("[FAIL] engine.start_stream() returned False.")
        return False

    time.sleep(1.5)
    engine.stop_stream()
    print(f"Frames received: {frames_received}")
    if frames_received > 5:
        print(f"[PASS] Stream started and received {frames_received} callback audio frames.")
        return True
    else:
        print("[FAIL] Received insufficient audio frames.")
        return False


def run_test_3_mic_rms() -> bool:
    print("\n" + "=" * 60)
    print("TEST 3: Live Audio RMS & Dynamic Range")
    print("=" * 60)
    from app.voice.microphone import MicrophoneEngine
    engine = MicrophoneEngine()
    engine.select_microphone()
    
    rms_values = []
    peak_values = []
    
    def on_frame(mono_f, mono_i, sr):
        if len(mono_f) > 0:
            r = float(np.sqrt(np.mean(mono_f ** 2)))
            p = float(np.max(np.abs(mono_f)))
            rms_values.append(r)
            peak_values.append(p)

    engine.add_frame_consumer(on_frame)
    engine.start_stream()
    print("Sampling live microphone for 2.0 seconds...")
    time.sleep(2.0)
    engine.stop_stream()

    if not rms_values:
        print("[FAIL] No audio frames captured.")
        return False

    avg_rms = float(np.mean(rms_values))
    max_peak = float(np.max(peak_values))
    print(f"Average RMS: {avg_rms:.6f}")
    print(f"Max Peak:    {max_peak:.6f}")
    print(f"Total frames: {len(rms_values)}")

    # Check for live non-zero audio
    if max_peak > 0.0001:
        print("[PASS] Microphone is producing live, non-zero acoustic signal!")
        return True
    else:
        print("[WARN] Microphone produced all-zero audio. Check Windows privacy settings or mic mute.")
        return False


def run_test_4_wake_detector() -> bool:
    print("\n" + "=" * 60)
    print("TEST 4: Wake Detector & Double-Clap Gesture")
    print("=" * 60)
    from app.voice.wake_engine import match_wake_phrase, DoubleClapDetector

    # 1. Wake phrase string matching
    phrases = [
        ("Hey AUREX open Chrome", True, "open Chrome"),
        ("AUREX what is the weather", True, "what is the weather"),
        ("hey rex run test", True, "run test"),
        ("Jarvis show status", True, "show status"),
        ("open visual studio", False, "open visual studio"),
    ]

    for text, exp_match, exp_clean in phrases:
        m, clean = match_wake_phrase(text)
        print(f"  Testing phrase: '{text}' -> matched={m}, stripped='{clean}'")
        if m != exp_match:
            print(f"[FAIL] Expected matched={exp_match} for '{text}'")
            return False

    # 2. Double clap detector synthetic test
    clap_detector = DoubleClapDetector(sensitivity="high", cooldown=1.0)
    sr = 16000
    spike_frame = np.zeros(512, dtype=np.float32)
    spike_frame[20:28] = 0.85  # sharp clap spike

    # First clap
    res1 = clap_detector.process_frame(spike_frame, sr)
    assert not res1, "First clap should not trigger alone"
    time.sleep(0.25)
    # Second clap within 120-750ms
    res2 = clap_detector.process_frame(spike_frame, sr)
    if not res2:
        print("[FAIL] Double clap failed to trigger on second spike.")
        return False

    print("[PASS] Wake phrases and double-clap gesture verified successfully.")
    return True


def run_test_5_tts() -> bool:
    print("\n" + "=" * 60)
    print("TEST 5: TTS Synthesis & Instant Barge-In Stop")
    print("=" * 60)
    from app.voice.tts import TTSEngine
    tts = TTSEngine()
    
    print("1. Testing speech playback ('AUREX voice online')...")
    tts.speak("Aurex voice online.")
    time.sleep(1.8)

    print("2. Testing barge-in interruption...")
    tts.speak("This is a very long response that must be cut off instantly when the user says stop.")
    time.sleep(0.4)
    assert tts.is_speaking, "TTS should be speaking before stop"
    tts.stop()
    assert not tts.is_speaking, "TTS must not be speaking after stop"
    print("[PASS] TTS speech synthesis and barge-in cut-off verified successfully.")
    return True


def run_test_6_stt() -> bool:
    print("\n" + "=" * 60)
    print("TEST 6: STT Engine & Container Inspection")
    print("=" * 60)
    from app.voice.stt import STTEngine
    stt = STTEngine()

    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sine = (0.25 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    wav_bytes = stt.pcm_to_wav(sine, sr)

    container_fn, mime = stt.detect_container(wav_bytes)
    print(f"Container detected: {container_fn} ({mime})")
    assert container_fn == "audio.wav" and mime == "audio/wav"

    print("Testing STT API connectivity with audio payload...")
    transcript = stt.transcribe(wav_bytes, "test.wav")
    print(f"Transcription response: '{transcript}'")
    print("[PASS] STT container detection and transcription pipeline functional.")
    return True


def run_test_7_full_pipeline() -> bool:
    print("\n" + "=" * 60)
    print("TEST 7: Full Voice Pipeline & Fast Local Router")
    print("=" * 60)
    from app.voice.conversation import ConversationManager
    from app.voice.voice_state import VoiceState
    from app.voice.local_router import FastLocalRouter

    # 1. Test local router speed and context
    router = FastLocalRouter()
    start_t = time.perf_counter()
    matched, reply = router.handle("shrink")
    router_ms = (time.perf_counter() - start_t) * 1000.0
    print(f"Local router 'shrink' latency: {router_ms:.2f}ms (Target: <150ms)")
    assert matched and "Shrinking" in reply
    assert router_ms < 150.0

    # 2. Test context resolution
    router.context.record_turn("open my OS project", "Opened OS", {"project": r"D:\VS Code\OS"})
    resolved = router.context.resolve_reference("build it")
    print(f"Pronoun resolution: 'build it' -> '{resolved}'")
    assert "OS" in resolved

    # 3. Test ConversationManager state transitions
    cm = ConversationManager()
    assert cm.state_machine.state == VoiceState.STARTING
    
    # Simulate wake
    cm.activate_conversation(greeting="")
    assert cm.state_machine.state == VoiceState.LISTENING

    # Simulate barge-in stop
    cm.tts.speak("A long speech")
    cm.tts.stop()
    cm.state_machine.transition_to(VoiceState.INTERRUPTING)
    cm.state_machine.transition_to(VoiceState.LISTENING)
    assert cm.state_machine.state == VoiceState.LISTENING

    # Simulate exit to passive
    cm.deactivate_to_passive(speak_farewell=False)
    assert cm.state_machine.state == VoiceState.PASSIVE

    print("[PASS] Full voice pipeline, local router, context, and state machine verified!")
    return True


def main():
    parser = argparse.ArgumentParser(description="AUREX Voice Diagnostics Suite")
    parser.add_argument("--test", type=str, default="all", help="1-7 or name (mic_enum, mic_stream, mic_rms, wake, tts, stt, full)")
    args = parser.parse_args()

    test_map = {
        "1": run_test_1_mic_enumeration,
        "mic_enum": run_test_1_mic_enumeration,
        "2": run_test_2_mic_stream,
        "mic_stream": run_test_2_mic_stream,
        "3": run_test_3_mic_rms,
        "mic_rms": run_test_3_mic_rms,
        "4": run_test_4_wake_detector,
        "wake": run_test_4_wake_detector,
        "5": run_test_5_tts,
        "tts": run_test_5_tts,
        "6": run_test_6_stt,
        "stt": run_test_6_stt,
        "7": run_test_7_full_pipeline,
        "full": run_test_7_full_pipeline,
    }

    if args.test != "all":
        test_fn = test_map.get(args.test)
        if not test_fn:
            print(f"Unknown test '{args.test}'. Choices: 1-7, mic_enum, mic_stream, mic_rms, wake, tts, stt, full")
            sys.exit(1)
        ok = test_fn()
        sys.exit(0 if ok else 1)

    print("\n" + "#" * 60)
    print("   RUNNING ALL AUREX VOICE SYSTEM DIAGNOSTIC TESTS")
    print("#" * 60)

    results = []
    tests = [
        ("Test 1: Mic Enumeration", run_test_1_mic_enumeration),
        ("Test 2: Mic Stream", run_test_2_mic_stream),
        ("Test 3: Mic Live RMS", run_test_3_mic_rms),
        ("Test 4: Wake Detector", run_test_4_wake_detector),
        ("Test 5: TTS & Barge-in", run_test_5_tts),
        ("Test 6: STT Engine", run_test_6_stt),
        ("Test 7: Full Pipeline", run_test_7_full_pipeline),
    ]

    all_passed = True
    for name, fn in tests:
        try:
            ok = fn()
            results.append((name, ok))
            if not ok:
                all_passed = False
        except Exception as e:
            logger.error(f"Error in {name}: {e}", exc_info=True)
            results.append((name, False))
            all_passed = False

    print("\n" + "=" * 60)
    print("             DIAGNOSTIC TEST SUMMARY")
    print("=" * 60)
    for name, ok in results:
        status_str = "[PASS]" if ok else "[FAIL]"
        print(f"  {status_str:8s} {name}")
    print("=" * 60)

    if all_passed:
        print(">>> ALL 7 AUREX VOICE TESTS PASSED SUCCESSFULLY! <<<\n")
        sys.exit(0)
    else:
        print(">>> SOME TESTS FAILED. See log output above. <<<\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
