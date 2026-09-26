import asyncio
import io
import os
import random
import sys
import numpy as np
import scipy.signal
import soundfile as sf
import edge_tts
from pathlib import Path
from sklearn.neural_network import MLPClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import onnx
from onnx import helper, TensorProto
from openwakeword.model import Model

VOICES = [
    'en-US-GuyNeural', 'en-US-JennyNeural', 'en-US-AriaNeural', 'en-US-DavisNeural',
    'en-US-JaneNeural', 'en-US-JasonNeural', 'en-US-SaraNeural', 'en-US-TonyNeural',
    'en-GB-RyanNeural', 'en-GB-SoniaNeural', 'en-AU-WilliamNeural', 'en-CA-LiamNeural'
]

POS_CONFIGS = [
    ("Hey Aurex", "+0%", "+0Hz"),
    ("Hey Aurex.", "+0%", "+0Hz"),
    ("Hey, Aurex", "+0%", "+0Hz"),
    ("hey aurex", "-10%", "+0Hz"),
    ("Hey Aurex!", "+10%", "+0Hz"),
    ("Aurex", "+0%", "+0Hz"),
    ("Hey Aurex", "-15%", "-10Hz"),
    ("Hey Aurex", "+15%", "+10Hz"),
    ("Hey Aurex", "+5%", "+5Hz"),
    ("Hey Aurex", "-5%", "-5Hz"),
]

NEG_PHRASES = [
    "Hey Jarvis", "Alexa", "Hey Siri", "OK Google", "Computer", "Hello", "How are you",
    "What is the time", "Turn off the lights", "Open YouTube", "Hey there", "Can you hear me",
    "Good morning", "Yes please", "No thanks", "Stop", "Wait a minute", "What is that",
    "Let me see", "Play music", "Check the weather", "Who are you", "Thank you",
    "Hey Alex", "Hey Eric", "Hey Austin", "Hey Felix", "Aura", "Matrix"
]

async def synth(text, voice, rate="+0%", pitch="+0Hz"):
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    data = b""
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
    audio, sr = sf.read(io.BytesIO(data))
    if audio.ndim > 1:
        audio = audio[:, 0]
    if sr != 16000:
        audio = scipy.signal.resample(audio, int(len(audio) * 16000 / sr))
    return (audio * 32767).astype(np.int16)

def extract_features(oww, audio):
    feats = []
    step = 1280
    for i in range(0, len(audio) - step, step):
        oww.predict(audio[i:i+step])
        feat = oww.preprocessor.get_features(16)
        chunk = audio[i:i+step]
        energy = np.mean(np.abs(chunk))
        feats.append((feat.copy().reshape(-1), energy))
    return feats

async def main():
    print("Initializing openWakeWord feature extractor...")
    oww = Model(wakeword_models=['hey_jarvis'], inference_framework='onnx')

    X = []
    y = []

    print("Generating positive samples ('Hey Aurex')...")
    pos_count = 0
    for voice in VOICES:
        for phrase, rate, pitch in POS_CONFIGS:
            try:
                audio = await synth(phrase, voice, rate, pitch)
                feats = extract_features(oww, audio)
                if not feats:
                    continue
                # The peak energy near the end of speech contains the utterance features
                energies = [e for _, e in feats]
                max_e = max(energies) if energies else 1.0
                # Pick frames where speech has just occurred
                speech_indices = [idx for idx, e in enumerate(energies) if e > max_e * 0.2]
                if speech_indices:
                    end_idx = speech_indices[-1]
                    # Take the window at end of speech and 1 frame after
                    for offset in [0, 1]:
                        pick = min(end_idx + offset, len(feats) - 1)
                        X.append(feats[pick][0])
                        y.append(1)
                        pos_count += 1
            except Exception as e:
                print(f"Error synthesizing {phrase} ({voice}): {e}")

    print(f"Total positive feature vectors: {pos_count}")

    print("Generating negative samples...")
    neg_count = 0
    for phrase in NEG_PHRASES:
        for voice in random.sample(VOICES, 3):
            try:
                audio = await synth(phrase, voice)
                feats = extract_features(oww, audio)
                for f, _ in feats:
                    X.append(f)
                    y.append(0)
                    neg_count += 1
            except Exception as e:
                print(f"Error synthesizing negative {phrase}: {e}")

    # Add noise / silence vectors
    for _ in range(200):
        noise = np.random.randint(-1500, 1500, 16000 * 2, dtype=np.int16)
        feats = extract_features(oww, noise)
        for f, _ in feats:
            X.append(f)
            y.append(0)
            neg_count += 1

    print(f"Total negative feature vectors: {neg_count}")

    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int64)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    print(f"Training MLPClassifier on {len(X_train)} samples...")

    clf = MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=500, random_state=42, early_stopping=True)
    clf.fit(X_train, y_train)

    score = clf.score(X_test, y_test)
    print(f"Test accuracy: {score * 100:.2f}%")
    y_pred = clf.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=["Negative", "Hey Aurex"]))

    # Export to ONNX
    # clf.coefs_[0]: (1536, 128), clf.intercepts_[0]: (128,)
    # clf.coefs_[1]: (128, 64), clf.intercepts_[1]: (64,)
    # clf.coefs_[2]: (64, 1), clf.intercepts_[2]: (1,)
    w1, b1 = clf.coefs_[0].astype(np.float32), clf.intercepts_[0].astype(np.float32)
    w2, b2 = clf.coefs_[1].astype(np.float32), clf.intercepts_[1].astype(np.float32)
    w3, b3 = clf.coefs_[2].astype(np.float32), clf.intercepts_[2].astype(np.float32)

    X_info = helper.make_tensor_value_info('x.1', TensorProto.FLOAT, [1, 16, 96])
    Y_info = helper.make_tensor_value_info('output', TensorProto.FLOAT, [1, 1])

    w1_init = helper.make_tensor('w1', TensorProto.FLOAT, list(w1.shape), w1.tobytes(), raw=True)
    b1_init = helper.make_tensor('b1', TensorProto.FLOAT, list(b1.shape), b1.tobytes(), raw=True)
    w2_init = helper.make_tensor('w2', TensorProto.FLOAT, list(w2.shape), w2.tobytes(), raw=True)
    b2_init = helper.make_tensor('b2', TensorProto.FLOAT, list(b2.shape), b2.tobytes(), raw=True)
    w3_init = helper.make_tensor('w3', TensorProto.FLOAT, list(w3.shape), w3.tobytes(), raw=True)
    b3_init = helper.make_tensor('b3', TensorProto.FLOAT, list(b3.shape), b3.tobytes(), raw=True)

    nodes = [
        helper.make_node('Flatten', ['x.1'], ['flat']),
        helper.make_node('Gemm', ['flat', 'w1', 'b1'], ['layer1']),
        helper.make_node('Relu', ['layer1'], ['relu1']),
        helper.make_node('Gemm', ['relu1', 'w2', 'b2'], ['layer2']),
        helper.make_node('Relu', ['layer2'], ['relu2']),
        helper.make_node('Gemm', ['relu2', 'w3', 'b3'], ['layer3']),
        helper.make_node('Sigmoid', ['layer3'], ['output']),
    ]

    graph = helper.make_graph(
        nodes,
        'hey_aurex',
        [X_info],
        [Y_info],
        [w1_init, b1_init, w2_init, b2_init, w3_init, b3_init]
    )
    onnx_model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)], ir_version=8)

    out_path = Path(__file__).resolve().parent / "models" / "hey_aurex.onnx"
    onnx.save(onnx_model, str(out_path))
    print(f"Model successfully exported to: {out_path}")

    # Also copy to openwakeword/resources/models
    import openwakeword
    oww_models_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
    oww_target = oww_models_dir / "hey_aurex.onnx"
    onnx.save(onnx_model, str(oww_target))
    print(f"Copied model to openwakeword resources: {oww_target}")

    # Test the exported model with live prediction
    test_oww = Model(wakeword_models=[str(out_path)], inference_framework='onnx')
    print("Testing live predictions on test audio clips:")
    for phrase in ["Hey Aurex", "Aurex", "Hey Jarvis", "Turn on the lights", "Hello world"]:
        audio = await synth(phrase, 'en-US-JennyNeural')
        preds = test_oww.predict_clip(audio)
        score = max([p.get('hey_aurex', 0.0) for p in preds]) if preds else 0.0
        print(f"  '{phrase}': score = {score:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
