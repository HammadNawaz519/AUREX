import React, { useState, useEffect, useRef, useCallback } from 'react';

type AssistantState = 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

export const VoiceSurface: React.FC = () => {
  const [state, setState] = useState<AssistantState>('IDLE');
  const [statusText, setStatusText] = useState<string>('Standing by');
  const [userQuery, setUserQuery] = useState<string>('');
  const [assistantReply, setAssistantReply] = useState<string>('');

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const tickRef = useRef<number>(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const latestSpeechRef = useRef<string>('');
  const recognitionRef = useRef<any>(null);
  const stateRef = useRef<AssistantState>('IDLE');
  stateRef.current = state;

  const numBars = 52;

  // Tripartite harmonic envelope matching the reference image
  const idleEnvelope = useRef<number[]>([]);
  if (idleEnvelope.current.length === 0) {
    const centers = [
      { c: 0.22, amp: 0.84, w: 0.08 },
      { c: 0.52, amp: 0.96, w: 0.09 },
      { c: 0.80, amp: 0.88, w: 0.08 }
    ];
    for (let i = 0; i < numBars; i++) {
      const norm = i / (numBars - 1);
      let val = 0.08;
      for (const { c, amp, w } of centers) {
        val += amp * Math.exp(-Math.pow(norm - c, 2) / (2.0 * Math.pow(w, 2)));
      }
      const subMod = 0.72 + 0.38 * Math.sin(i * 1.85) * Math.cos(i * 0.9);
      const barH = val * subMod;
      const edgeTaper = Math.pow(Math.sin(norm * Math.PI), 0.45);
      idleEnvelope.current.push(Math.max(0.08, Math.min(0.96, barH * edgeTaper)));
    }
  }

  const getApiBase = () => {
    if (typeof window !== 'undefined' && window.location.origin.startsWith('http')) {
      return window.location.origin;
    }
    return 'http://127.0.0.1:8765';
  };

  // Setup Web Audio Analyzer & MediaRecorder
  const setupAudio = async () => {
    if (audioContextRef.current && mediaStreamRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true }
      });
      mediaStreamRef.current = stream;

      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 128;
      analyser.smoothingTimeConstant = 0.5;
      source.connect(analyser);
      analyserRef.current = analyser;

      const mr = new MediaRecorder(stream);
      mr.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };
      mr.onstop = () => {
        const mime = mr.mimeType || 'audio/webm';
        const blob = new Blob(audioChunksRef.current, { type: mime });
        audioChunksRef.current = [];
        if (blob.size > 1500) {
          sendAudioToAgent(blob);
        } else {
          setState('IDLE');
          setStatusText('Standing by');
        }
      };
      mediaRecorderRef.current = mr;

      const isQtWebEngine = typeof navigator !== 'undefined' && /QtWebEngine/i.test(navigator.userAgent);
      const SpeechRec = !isQtWebEngine && ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);

      if (SpeechRec) {
        try {
          const rec = new SpeechRec();
          rec.continuous = true;
          rec.interimResults = true;
          rec.lang = 'en-US';

          rec.onresult = (event: any) => {
            let current = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
              current += event.results[i][0].transcript;
            }
            current = current.trim();
            if (current) {
              setUserQuery(current);
              latestSpeechRef.current = current;
            }
          };

          rec.onend = () => {
            if (stateRef.current === 'LISTENING') {
              try { rec.start(); } catch (_) {}
            }
          };

          recognitionRef.current = rec;
        } catch (_) {}
      }
    } catch (e) {
      console.warn('Audio setup notice:', e);
    }
  };

  // Start Listening when Spacebar pressed
  const startListening = async () => {
    if (stateRef.current === 'LISTENING' || stateRef.current === 'THINKING') return;

    await setupAudio();

    setState('LISTENING');
    setStatusText('Listening...');
    setUserQuery('');
    latestSpeechRef.current = '';
    audioChunksRef.current = [];

    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'inactive') {
      try {
        mediaRecorderRef.current.start(100);
      } catch (_) {}
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.start();
      } catch (_) {}
    }
  };

  // Stop Listening when Spacebar released
  const stopListening = () => {
    if (stateRef.current !== 'LISTENING') return;

    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      try {
        mediaRecorderRef.current.stop();
      } catch (_) {}
    }

    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch (_) {}
    }

    setTimeout(() => {
      const text = latestSpeechRef.current.trim();
      if (text) {
        latestSpeechRef.current = '';
        executeCommand(text);
      } else if (audioChunksRef.current.length > 0) {
        const mime = mediaRecorderRef.current?.mimeType || 'audio/webm';
        const blob = new Blob(audioChunksRef.current, { type: mime });
        audioChunksRef.current = [];
        if (blob.size > 1500) {
          sendAudioToAgent(blob);
        } else {
          setState('IDLE');
          setStatusText('Standing by');
        }
      } else {
        setState('IDLE');
        setStatusText('Standing by');
      }
    }, 120);
  };

  // Spacebar Hotkey Listener (Press/Hold to Listen)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat) {
        e.preventDefault();
        startListening();
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        e.preventDefault();
        stopListening();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    // Global desktop window bindings
    (window as any).__aurexStartListen = startListening;
    (window as any).__aurexStopListen = stopListening;

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, []);

  // Dispatch Recorded Audio Blob to Groq Whisper & Agent
  const sendAudioToAgent = async (blob: Blob) => {
    setState('THINKING');
    setStatusText('Executing...');

    try {
      const res = await fetch(`${getApiBase()}/api/voice`, {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'audio/webm' },
        body: blob
      });

      if (!res.ok) throw new Error(`Status: ${res.status}`);

      const data = await res.json();
      if (data.transcript) {
        setUserQuery(data.transcript);
      }
      const reply = data.response || 'Task completed.';
      setAssistantReply(reply);
      speakResponse(reply);
    } catch (err: any) {
      console.warn('Voice agent error:', err);
      setState('IDLE');
      setStatusText('Standing by');
    }
  };

  // Dispatch Text Command to Agent
  const executeCommand = async (command: string) => {
    const clean = command.trim();
    if (!clean) {
      setState('IDLE');
      setStatusText('Standing by');
      return;
    }

    setUserQuery(clean);
    setState('THINKING');
    setStatusText('Executing...');

    try {
      const res = await fetch(`${getApiBase()}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: clean })
      });

      if (!res.ok) throw new Error(`Status: ${res.status}`);

      const data = await res.json();
      const reply = data.response || 'Task executed.';
      setAssistantReply(reply);
      speakResponse(reply);
    } catch (err: any) {
      console.warn('Command error:', err);
      const fallback = `Processed: "${clean}".`;
      setAssistantReply(fallback);
      speakResponse(fallback);
    }
  };

  // Speak Response & Return to IDLE
  const speakResponse = (text: string) => {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      utterance.pitch = 1.0;

      utterance.onstart = () => {
        setState('SPEAKING');
        setStatusText('Speaking...');
      };

      const onDone = () => {
        setState('IDLE');
        setStatusText('Standing by');
      };

      utterance.onend = onDone;
      utterance.onerror = onDone;

      window.speechSynthesis.speak(utterance);
    } else {
      setState('IDLE');
      setStatusText('Standing by');
    }
  };

  // Draw the sound wave in Light Theme
  const drawWave = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    const cy = h / 2.0;
    const maxBarH = (h - 6) / 2.0;

    ctx.clearRect(0, 0, w, h);

    let micFreqs: Uint8Array | null = null;
    let micLevel = 0.05;

    if (analyserRef.current && state === 'LISTENING') {
      micFreqs = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(micFreqs as any);

      let sum = 0;
      const binLimit = Math.min(36, micFreqs.length);
      for (let b = 2; b < binLimit; b++) {
        sum += micFreqs[b];
      }
      micLevel = sum / (binLimit - 2) / 255.0;
    }

    const totalSpacing = w - 16;
    const barSpacing = totalSpacing / numBars;
    const barWidth = Math.max(2.4, Math.min(4.0, barSpacing * 0.64));
    const startX = (w - numBars * barSpacing) / 2.0;

    for (let i = 0; i < numBars; i++) {
      const norm = i / (numBars - 1);
      const bx = startX + i * barSpacing + barSpacing / 2.0;
      let amp = idleEnvelope.current[i];

      if (state === 'LISTENING') {
        const base = idleEnvelope.current[i];
        const ripple = Math.sin(norm * 14.0 - tickRef.current * 3.5) * 0.25;
        amp = Math.max(0.08, Math.min(0.98, base * (0.85 + micLevel * 2.4) + ripple * micLevel));
      } else if (state === 'THINKING') {
        const wave1 = Math.sin(norm * 9.0 + tickRef.current * 2.6) * 0.35;
        const wave2 = Math.cos(norm * 15.0 - tickRef.current * 3.2) * 0.2;
        amp = Math.max(0.12, Math.min(0.92, 0.45 + wave1 + wave2));
      } else if (state === 'SPEAKING') {
        const vocal =
          Math.sin(tickRef.current * 6.5 + i * 0.32) * 0.3 +
          Math.sin(tickRef.current * 12.0 + i * 0.52) * 0.18;
        amp = Math.max(0.12, Math.min(0.98, idleEnvelope.current[i] * 1.35 + vocal));
      } else {
        amp = idleEnvelope.current[i] * 0.5;
      }

      const barHalfH = Math.max(2.0, amp * maxBarH);

      // Light Theme High-Contrast Gradient: Rose Pink (#DB2777) -> Royal Violet (#7C3AED) -> Cyan Sky (#0284C7)
      let r = 219, g = 39, b = 119;
      if (norm < 0.33) {
        const t = norm / 0.33;
        r = Math.round(219 + (124 - 219) * t);
        g = Math.round(39 + (58 - 39) * t);
        b = Math.round(119 + (237 - 119) * t);
      } else if (norm < 0.66) {
        const t = (norm - 0.33) / 0.33;
        r = Math.round(124 + (2 - 124) * t);
        g = Math.round(58 + (132 - 58) * t);
        b = Math.round(237 + (199 - 237) * t);
      } else {
        const t = (norm - 0.66) / 0.34;
        r = Math.round(2 + (2 - 2) * t);
        g = Math.round(132 + (132 - 132) * t);
        b = Math.round(199 + (199 - 199) * t);
      }

      ctx.beginPath();
      ctx.strokeStyle = `rgb(${r}, ${g}, ${b})`;
      ctx.lineWidth = barWidth;
      ctx.lineCap = 'round';
      ctx.moveTo(bx, cy - barHalfH);
      ctx.lineTo(bx, cy + barHalfH);
      ctx.stroke();
    }
  }, [state]);

  // Animation Loop: runs actively when state !== IDLE, halts/low-ticks on IDLE
  useEffect(() => {
    if (state === 'IDLE') {
      drawWave();
      return;
    }

    let isRunning = true;
    const loop = () => {
      if (!isRunning) return;
      if (state === 'LISTENING') tickRef.current += 0.08;
      else if (state === 'SPEAKING') tickRef.current += 0.14;
      else if (state === 'THINKING') tickRef.current += 0.09;

      drawWave();
      animFrameRef.current = requestAnimationFrame(loop);
    };

    animFrameRef.current = requestAnimationFrame(loop);
    return () => {
      isRunning = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [state, drawWave]);

  // Handle Canvas Resize
  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = canvas.parentElement?.clientWidth || 318;
        canvas.height = 48;
        drawWave();
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [drawWave]);

  return (
    <div
      style={styles.card}
      onClick={() => {
        if (state === 'IDLE') startListening();
        else if (state === 'LISTENING') stopListening();
      }}
      title="Press Spacebar or Click to Speak"
    >
      {/* 1. Header Row (Ultra-clean, No Live Label, No Cross) */}
      <div style={styles.headerRow}>
        <div style={styles.titleBadge}>
          <span
            style={{
              ...styles.pulseDot,
              backgroundColor:
                state === 'LISTENING'
                  ? '#059669'
                  : state === 'THINKING'
                  ? '#7C3AED'
                  : state === 'SPEAKING'
                  ? '#0284C7'
                  : '#94A3B8',
              boxShadow:
                state === 'LISTENING'
                  ? '0 0 10px rgba(5, 150, 105, 0.7)'
                  : state === 'THINKING'
                  ? '0 0 10px rgba(124, 58, 237, 0.7)'
                  : state === 'SPEAKING'
                  ? '0 0 10px rgba(2, 132, 199, 0.7)'
                  : 'none'
            }}
          />
          <span style={styles.titleText}>AUREX</span>
          <span style={styles.statusLabel}>{statusText}</span>
        </div>
      </div>

      {/* 2. Compact Sound Wave */}
      <div style={styles.waveBox}>
        <canvas ref={canvasRef} style={styles.canvas} />
      </div>

      {/* 3. Instant Speech Feedback & Action Status */}
      <div style={styles.transcriptBox}>
        {userQuery ? (
          <div style={styles.queryText}>"{userQuery}"</div>
        ) : assistantReply ? (
          <div style={styles.replyText}>{assistantReply}</div>
        ) : (
          <div style={styles.hintText}>Hold Spacebar to speak</div>
        )}
      </div>
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  card: {
    width: '350px',
    backgroundColor: 'rgba(255, 255, 255, 0.88)',
    border: '1px solid rgba(226, 232, 240, 0.95)',
    borderRadius: '20px',
    padding: '14px 18px',
    boxShadow: '0 16px 36px rgba(15, 23, 42, 0.10), 0 2px 6px rgba(15, 23, 42, 0.04)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    pointerEvents: 'auto',
    cursor: 'pointer',
    userSelect: 'none'
  },
  headerRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    height: '20px'
  },
  titleBadge: {
    display: 'flex',
    alignItems: 'center',
    gap: '7px'
  },
  pulseDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    transition: 'all 0.25s ease'
  },
  titleText: {
    fontSize: '11px',
    fontWeight: 800,
    letterSpacing: '1.6px',
    color: '#0F172A',
    textTransform: 'uppercase'
  },
  statusLabel: {
    fontSize: '11px',
    color: '#475569',
    fontWeight: 500,
    marginLeft: '2px'
  },
  waveBox: {
    width: '100%',
    height: '48px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: '10px',
    backgroundColor: 'rgba(241, 245, 249, 0.65)',
    overflow: 'hidden'
  },
  canvas: {
    width: '100%',
    height: '100%'
  },
  transcriptBox: {
    minHeight: '22px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    textAlign: 'center',
    overflow: 'hidden'
  },
  queryText: {
    fontSize: '12.5px',
    fontWeight: 600,
    color: '#0284C7',
    fontStyle: 'italic',
    whiteSpace: 'nowrap',
    textOverflow: 'ellipsis',
    overflow: 'hidden',
    maxWidth: '100%'
  },
  replyText: {
    fontSize: '12px',
    fontWeight: 600,
    color: '#0F172A',
    whiteSpace: 'nowrap',
    textOverflow: 'ellipsis',
    overflow: 'hidden',
    maxWidth: '100%'
  },
  hintText: {
    fontSize: '11px',
    color: '#64748B',
    fontWeight: 500
  }
};
