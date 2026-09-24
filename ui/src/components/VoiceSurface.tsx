import React, { useState, useEffect, useRef, useCallback } from 'react';

// ─── Types ─────────────────────────────────────────────────────────────────────
type AssistantState = 'IDLE' | 'LISTENING' | 'THINKING' | 'PLANNING' | 'EXECUTING' | 'VERIFYING' | 'SPEAKING' | 'SUCCESS' | 'ERROR';

interface TaskStep {
  id: number;
  description: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  risk: string;
}

interface TaskPlan {
  id: string;
  goal: string;
  status: string;
  progress: string;
  done: number;
  total: number;
  steps: TaskStep[];
}

// ─── Constants ──────────────────────────────────────────────────────────────────
const isQtWebEngine = typeof navigator !== 'undefined' && /QtWebEngine/i.test(navigator.userAgent);
const getApiBase = () => {
  if (typeof window !== 'undefined' && window.location.origin.startsWith('http')) return window.location.origin;
  return 'http://127.0.0.1:8765';
};

// ─── Particle System ───────────────────────────────────────────────────────────
interface Particle {
  x: number; y: number;
  vx: number; vy: number;
  life: number; maxLife: number;
  size: number; alpha: number;
  hue: number; orbit: boolean;
  angle: number; radius: number; speed: number;
}

function createParticle(cx: number, cy: number, state: AssistantState): Particle {
  const orbit = state === 'THINKING' || state === 'PLANNING' || state === 'EXECUTING';
  const angle = Math.random() * Math.PI * 2;
  const radius = orbit ? 38 + Math.random() * 22 : Math.random() * 60;

  const hueMap: Record<AssistantState, number> = {
    IDLE: 210, LISTENING: 160, THINKING: 260, PLANNING: 280,
    EXECUTING: 200, VERIFYING: 180, SPEAKING: 230, SUCCESS: 140, ERROR: 0,
  };

  return {
    x: orbit ? cx + Math.cos(angle) * radius : cx + (Math.random() - 0.5) * 120,
    y: orbit ? cy + Math.sin(angle) * radius : cy + (Math.random() - 0.5) * 120,
    vx: orbit ? 0 : (Math.random() - 0.5) * 0.6,
    vy: orbit ? 0 : (Math.random() - 0.5) * 0.6,
    life: 0,
    maxLife: 80 + Math.random() * 120,
    size: 0.8 + Math.random() * 1.8,
    alpha: 0,
    hue: (hueMap[state] || 210) + (Math.random() - 0.5) * 30,
    orbit,
    angle,
    radius,
    speed: (0.006 + Math.random() * 0.012) * (Math.random() > 0.5 ? 1 : -1),
  };
}

// ─── Main Component ─────────────────────────────────────────────────────────────
export const VoiceSurface: React.FC = () => {
  const [state, setState] = useState<AssistantState>('IDLE');
  const [statusText, setStatusText] = useState('Standing by');
  const [userQuery, setUserQuery] = useState('');
  const [assistantReply, setAssistantReply] = useState('');
  const [screenAware, setScreenAware] = useState(false);
  const [plan, setPlan] = useState<TaskPlan | null>(null);
  const [currentStep, setCurrentStep] = useState('');
  const [isMinimal, setIsMinimal] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const tickRef = useRef<number>(0);
  const particlesRef = useRef<Particle[]>([]);
  const stateRef = useRef<AssistantState>('IDLE');
  stateRef.current = state;

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const latestSpeechRef = useRef<string>('');
  const recognitionRef = useRef<any>(null);

  const planPollRef = useRef<number | null>(null);

  // ─── Helpers ──────────────────────────────────────────────────────────────────

  const applyState = useCallback((s: AssistantState, text: string) => {
    setState(s);
    setStatusText(text);
    stateRef.current = s;
  }, []);

  const stateColors: Record<AssistantState, { primary: string; glow: string; ring: string }> = {
    IDLE:      { primary: 'rgba(148,163,184,0.6)',  glow: 'rgba(148,163,184,0.15)', ring: '#64748b' },
    LISTENING: { primary: 'rgba(52,211,153,0.85)',  glow: 'rgba(52,211,153,0.25)',  ring: '#10b981' },
    THINKING:  { primary: 'rgba(167,139,250,0.85)', glow: 'rgba(167,139,250,0.3)',  ring: '#7c3aed' },
    PLANNING:  { primary: 'rgba(192,132,252,0.9)',  glow: 'rgba(192,132,252,0.35)', ring: '#a855f7' },
    EXECUTING: { primary: 'rgba(56,189,248,0.9)',   glow: 'rgba(56,189,248,0.3)',   ring: '#0ea5e9' },
    VERIFYING: { primary: 'rgba(34,211,238,0.85)',  glow: 'rgba(34,211,238,0.3)',   ring: '#06b6d4' },
    SPEAKING:  { primary: 'rgba(99,179,237,0.9)',   glow: 'rgba(99,179,237,0.3)',   ring: '#3b82f6' },
    SUCCESS:   { primary: 'rgba(74,222,128,0.9)',   glow: 'rgba(74,222,128,0.35)',  ring: '#22c55e' },
    ERROR:     { primary: 'rgba(248,113,113,0.9)',  glow: 'rgba(248,113,113,0.3)',  ring: '#ef4444' },
  };

  // ─── Audio Setup ──────────────────────────────────────────────────────────────

  const setupAudio = useCallback(async () => {
    if (audioCtxRef.current && streamRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      streamRef.current = stream;

      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.75;
      src.connect(analyser);
      analyserRef.current = analyser;

      const mr = new MediaRecorder(stream);
      mr.ondataavailable = (e) => { if (e.data?.size > 0) audioChunksRef.current.push(e.data); };
      mr.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: mr.mimeType || 'audio/webm' });
        audioChunksRef.current = [];
        if (blob.size > 1500) sendAudioToAgent(blob);
        else { applyState('IDLE', 'Standing by'); }
      };
      recorderRef.current = mr;

      const SR = !isQtWebEngine && ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
      if (SR) {
        const rec = new SR();
        rec.continuous = true; rec.interimResults = true; rec.lang = 'en-US';
        rec.onresult = (ev: any) => {
          let txt = '';
          for (let i = ev.resultIndex; i < ev.results.length; i++) txt += ev.results[i][0].transcript;
          txt = txt.trim();
          if (txt) { setUserQuery(txt); latestSpeechRef.current = txt; }
        };
        rec.onend = () => { if (stateRef.current === 'LISTENING') try { rec.start(); } catch (_) {} };
        recognitionRef.current = rec;
      }
    } catch (e) { console.warn('Audio setup:', e); }
  }, []);

  // ─── Listen Controls ──────────────────────────────────────────────────────────

  const startListening = useCallback(async () => {
    if (stateRef.current === 'LISTENING' || stateRef.current === 'THINKING') return;
    await setupAudio();
    applyState('LISTENING', 'Listening...');
    setUserQuery(''); latestSpeechRef.current = ''; audioChunksRef.current = [];
    if (recorderRef.current?.state === 'inactive') try { recorderRef.current.start(100); } catch (_) {}
    if (recognitionRef.current) try { recognitionRef.current.start(); } catch (_) {}
  }, [setupAudio, applyState]);

  const stopListening = useCallback(() => {
    if (stateRef.current !== 'LISTENING') return;
    if (recorderRef.current?.state === 'recording') try { recorderRef.current.stop(); } catch (_) {}
    if (recognitionRef.current) try { recognitionRef.current.stop(); } catch (_) {}

    setTimeout(() => {
      const text = latestSpeechRef.current.trim();
      if (text) { latestSpeechRef.current = ''; executeCommand(text); }
      else if (audioChunksRef.current.length > 0) {
        const blob = new Blob(audioChunksRef.current, { type: recorderRef.current?.mimeType || 'audio/webm' });
        audioChunksRef.current = [];
        if (blob.size > 1500) sendAudioToAgent(blob);
        else applyState('IDLE', 'Standing by');
      } else applyState('IDLE', 'Standing by');
    }, 120);
  }, [applyState]);

  // ─── API Calls ───────────────────────────────────────────────────────────────

  const sendAudioToAgent = async (blob: Blob) => {
    applyState('THINKING', 'Processing...');
    try {
      const res = await fetch(`${getApiBase()}/api/voice`, {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'audio/webm', ...(isQtWebEngine ? { 'X-Client': 'desktop-widget' } : {}) },
        body: blob,
      });
      if (!res.ok) throw new Error(`Status: ${res.status}`);
      const data = await res.json();
      if (data.transcript) setUserQuery(data.transcript);
      handleResponse(data.response || 'Task completed.');
    } catch (err) {
      console.warn('Voice error:', err);
      applyState('IDLE', 'Standing by');
    }
  };

  const executeCommand = async (command: string) => {
    const clean = command.trim();
    if (!clean) { applyState('IDLE', 'Standing by'); return; }
    setUserQuery(clean);
    applyState('THINKING', 'Processing...');
    try {
      const res = await fetch(`${getApiBase()}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(isQtWebEngine ? { 'X-Client': 'desktop-widget' } : {}) },
        body: JSON.stringify({ command: clean, client: isQtWebEngine ? 'desktop-widget' : 'web', speak: isQtWebEngine }),
      });
      if (!res.ok) throw new Error(`Status: ${res.status}`);
      const data = await res.json();
      handleResponse(data.response || 'Task executed.');
    } catch (err) {
      handleResponse(`Processed: "${clean}".`);
    }
  };

  const handleResponse = (reply: string) => {
    setAssistantReply(reply);
    // Infer state from response text
    const r = reply.toLowerCase();
    if (r.includes('plan') || r.includes('step 1')) {
      applyState('PLANNING', 'Planning...');
      pollPlan();
    } else if (r.includes('executing') || r.includes('completed') || r.includes('✓')) {
      applyState('EXECUTING', 'Executing...');
      pollPlan();
    } else if (r.includes('error') || r.includes('failed')) {
      applyState('ERROR', 'Error');
    } else if (r.includes('done') || r.includes('finished') || r.includes('completed')) {
      applyState('SUCCESS', 'Done');
      setTimeout(() => applyState('IDLE', 'Standing by'), 3000);
      return;
    } else {
      speakResponse(reply);
      return;
    }
    speakResponse(reply);
  };

  const speakResponse = (text: string) => {
    if (isQtWebEngine) {
      applyState('SPEAKING', 'Speaking...');
      const words = text.split(/\s+/).length;
      setTimeout(() => applyState('IDLE', 'Standing by'), Math.max(1600, Math.min(9000, words * 350)));
      return;
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utt = new SpeechSynthesisUtterance(text);
      utt.rate = 1.05; utt.pitch = 0.95;
      utt.onstart = () => applyState('SPEAKING', 'Speaking...');
      const done = () => applyState('IDLE', 'Standing by');
      utt.onend = done; utt.onerror = done;
      window.speechSynthesis.speak(utt);
    } else {
      applyState('IDLE', 'Standing by');
    }
  };

  // ─── Screen Awareness Toggle ──────────────────────────────────────────────────

  const toggleScreenAware = async () => {
    const endpoint = screenAware ? '/api/screen/disable' : '/api/screen/enable';
    try {
      const res = await fetch(`${getApiBase()}${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
      const data = await res.json();
      setScreenAware(!!data.screen_aware);
    } catch (e) {
      setScreenAware(!screenAware);
    }
  };

  // ─── Plan Polling ─────────────────────────────────────────────────────────────

  const pollPlan = useCallback(() => {
    if (planPollRef.current) clearInterval(planPollRef.current);
    planPollRef.current = window.setInterval(async () => {
      try {
        const res = await fetch(`${getApiBase()}/api/plan/current`);
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.steps) {
          setPlan(data);
          const running = data.steps.find((s: TaskStep) => s.status === 'running');
          if (running) setCurrentStep(running.description);
          if (data.status === 'completed' || data.status === 'failed') {
            clearInterval(planPollRef.current!);
            planPollRef.current = null;
            setTimeout(() => setPlan(null), 8000);
          }
        }
      } catch (_) {}
    }, 1200) as unknown as number;
  }, []);

  // ─── Keyboard Hotkeys ─────────────────────────────────────────────────────────

  useEffect(() => {
    const kd = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat) { e.preventDefault(); startListening(); }
      if ((e.ctrlKey || e.metaKey) && e.code === 'Space') { e.preventDefault(); startListening(); }
    };
    const ku = (e: KeyboardEvent) => {
      if (e.code === 'Space') { e.preventDefault(); stopListening(); }
    };
    window.addEventListener('keydown', kd);
    window.addEventListener('keyup', ku);
    (window as any).__aurexStartListen = startListening;
    (window as any).__aurexStopListen = stopListening;
    return () => { window.removeEventListener('keydown', kd); window.removeEventListener('keyup', ku); };
  }, [startListening, stopListening]);

  // ─── Status Poll ─────────────────────────────────────────────────────────────

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`${getApiBase()}/api/status`);
        const data = await res.json();
        setScreenAware(!!data.screen_aware);
      } catch (_) {}
    }, 5000);
    return () => clearInterval(poll);
  }, []);

  // ─── Canvas Drawing ───────────────────────────────────────────────────────────

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;
    const s = stateRef.current;
    const t = tickRef.current;
    const col = stateColors[s];

    // Clear with slight trail
    ctx.fillStyle = 'rgba(8, 10, 20, 0.18)';
    ctx.fillRect(0, 0, W, H);

    // ── Mic level ────────────────────────────────────────────────────────────
    let micLevel = 0;
    if (analyserRef.current && s === 'LISTENING') {
      const freqs = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(freqs);
      let sum = 0;
      for (let b = 2; b < Math.min(48, freqs.length); b++) sum += freqs[b];
      micLevel = sum / (46 * 255);
    }

    // ── Particle update ───────────────────────────────────────────────────────
    // Spawn particles
    const spawnRate = s === 'IDLE' ? 0.3 : s === 'EXECUTING' ? 4 : s === 'LISTENING' ? 2 + micLevel * 8 : 2;
    if (Math.random() < spawnRate * 0.1) {
      particlesRef.current.push(createParticle(cx, cy, s));
    }
    if (particlesRef.current.length > 180) particlesRef.current.splice(0, 5);

    for (let i = particlesRef.current.length - 1; i >= 0; i--) {
      const p = particlesRef.current[i];
      p.life++;

      if (p.orbit) {
        p.angle += p.speed;
        p.x = cx + Math.cos(p.angle) * p.radius;
        p.y = cy + Math.sin(p.angle) * p.radius;
      } else {
        p.x += p.vx;
        p.y += p.vy;
        p.vy -= 0.003; // gentle float up
      }

      const progress = p.life / p.maxLife;
      p.alpha = progress < 0.15 ? progress / 0.15 : progress > 0.8 ? (1 - progress) / 0.2 : 1;

      if (p.life >= p.maxLife) { particlesRef.current.splice(i, 1); continue; }

      ctx.save();
      ctx.globalAlpha = p.alpha * (s === 'IDLE' ? 0.3 : 0.7);
      ctx.fillStyle = `hsl(${p.hue}, 80%, 72%)`;
      ctx.shadowColor = `hsl(${p.hue}, 90%, 65%)`;
      ctx.shadowBlur = 4;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // ── Dynamic concentric rings ───────────────────────────────────────────────
    const ringCount = s === 'IDLE' ? 2 : s === 'THINKING' || s === 'PLANNING' ? 4 : 3;
    for (let r = 0; r < ringCount; r++) {
      const phase = t * (0.4 + r * 0.15) + r * (Math.PI * 2 / ringCount);
      const baseR = 20 + r * 12;
      const pulse = s === 'IDLE' ? Math.sin(t * 0.8 + r) * 2 : Math.sin(t * 1.8 + r * 1.3) * (4 + micLevel * 14);
      const ringR = baseR + pulse;
      const alpha = s === 'IDLE' ? 0.08 + Math.sin(phase) * 0.04 : 0.18 + Math.sin(phase) * 0.10;
      const lineW = s === 'IDLE' ? 0.6 : 1.0 + r * 0.2;

      const grad = ctx.createRadialGradient(cx, cy, ringR * 0.5, cx, cy, ringR + 4);
      grad.addColorStop(0, `hsla(${parseInt(col.ring.slice(1), 16)}, 80%, 70%, 0)`);
      grad.addColorStop(0.6, col.primary.replace('0.', `${alpha.toFixed(2)}.`).replace(/0\.\d+\)/, `${alpha})`));
      grad.addColorStop(1, `${col.ring}00`);

      ctx.beginPath();
      ctx.strokeStyle = col.ring;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = lineW;
      ctx.arc(cx, cy, Math.max(4, ringR), 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // ── Core orb ──────────────────────────────────────────────────────────────
    const coreR = s === 'IDLE'
      ? 10 + Math.sin(t * 0.6) * 1.5
      : s === 'LISTENING'
      ? 12 + Math.sin(t * 1.4) * (2 + micLevel * 10)
      : s === 'EXECUTING'
      ? 11 + Math.sin(t * 2.4) * 3
      : 11 + Math.sin(t * 1.1) * 2;

    // Glow layers
    for (let g = 3; g >= 0; g--) {
      const gR = coreR + g * 8;
      const gAlpha = 0.04 + (3 - g) * 0.025;
      const orbGrad = ctx.createRadialGradient(cx - coreR * 0.25, cy - coreR * 0.25, 0, cx, cy, gR);
      orbGrad.addColorStop(0, col.primary.replace(/[\d.]+\)$/, '0.9)'));
      orbGrad.addColorStop(0.5, col.primary.replace(/[\d.]+\)$/, `${gAlpha * 2})`));
      orbGrad.addColorStop(1, 'transparent');
      ctx.beginPath();
      ctx.globalAlpha = 1;
      ctx.fillStyle = orbGrad;
      ctx.arc(cx, cy, gR, 0, Math.PI * 2);
      ctx.fill();
    }

    // Core fill
    const coreGrad = ctx.createRadialGradient(cx - coreR * 0.3, cy - coreR * 0.3, 0, cx, cy, coreR);
    coreGrad.addColorStop(0, 'rgba(255,255,255,0.95)');
    coreGrad.addColorStop(0.4, col.primary.replace(/[\d.]+\)$/, '0.9)'));
    coreGrad.addColorStop(1, col.primary.replace(/[\d.]+\)$/, '0.3)'));
    ctx.beginPath();
    ctx.fillStyle = coreGrad;
    ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
    ctx.fill();

    // Core highlight
    ctx.beginPath();
    ctx.fillStyle = 'rgba(255,255,255,0.4)';
    ctx.arc(cx - coreR * 0.25, cy - coreR * 0.3, coreR * 0.3, 0, Math.PI * 2);
    ctx.fill();

    // ── Rotating arc segments for THINKING / PLANNING / EXECUTING ─────────────
    if (s === 'THINKING' || s === 'PLANNING' || s === 'EXECUTING' || s === 'VERIFYING') {
      const arcR = 34;
      const segments = s === 'EXECUTING' ? 6 : 4;
      for (let i = 0; i < segments; i++) {
        const start = t * (s === 'EXECUTING' ? 3.2 : 2.1) + (i * Math.PI * 2) / segments;
        const arc = (Math.PI * 2 / segments) * 0.55;
        const alpha = 0.5 + 0.5 * Math.sin(t * 2 + i);
        ctx.beginPath();
        ctx.strokeStyle = col.ring;
        ctx.globalAlpha = alpha * 0.7;
        ctx.lineWidth = 1.8;
        ctx.arc(cx, cy, arcR, start, start + arc);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    // ── Audio waveform ring for LISTENING / SPEAKING ───────────────────────────
    if ((s === 'LISTENING' || s === 'SPEAKING') && analyserRef.current) {
      const freqs = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(freqs);
      const baseR2 = 42;
      const N = 64;
      ctx.beginPath();
      for (let i = 0; i < N; i++) {
        const angle2 = (i / N) * Math.PI * 2 - Math.PI / 2;
        const binIdx = Math.floor((i / N) * freqs.length * 0.5);
        const level = (freqs[binIdx] || 0) / 255;
        const r2 = baseR2 + level * 18;
        const x2 = cx + Math.cos(angle2) * r2;
        const y2 = cy + Math.sin(angle2) * r2;
        if (i === 0) ctx.moveTo(x2, y2);
        else ctx.lineTo(x2, y2);
      }
      ctx.closePath();
      ctx.strokeStyle = col.ring;
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // ── Success burst ──────────────────────────────────────────────────────────
    if (s === 'SUCCESS') {
      const burstR = 28 + (t % 80) * 1.2;
      ctx.beginPath();
      ctx.strokeStyle = '#22c55e';
      ctx.globalAlpha = Math.max(0, 1 - (t % 80) / 80);
      ctx.lineWidth = 2;
      ctx.arc(cx, cy, burstR, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

  }, [stateColors]);

  // ─── Animation Loop ───────────────────────────────────────────────────────────

  useEffect(() => {
    let running = true;
    const tickSpeed: Record<AssistantState, number> = {
      IDLE: 0.025, LISTENING: 0.07, THINKING: 0.055, PLANNING: 0.06,
      EXECUTING: 0.09, VERIFYING: 0.065, SPEAKING: 0.08, SUCCESS: 0.12, ERROR: 0.04,
    };

    const loop = () => {
      if (!running) return;
      tickRef.current += tickSpeed[stateRef.current] || 0.04;
      draw();
      animFrameRef.current = requestAnimationFrame(loop);
    };
    animFrameRef.current = requestAnimationFrame(loop);
    return () => { running = false; if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current); };
  }, [draw]);

  // ─── Canvas Resize ────────────────────────────────────────────────────────────

  useEffect(() => {
    const resize = () => {
      const c = canvasRef.current;
      if (c) { c.width = c.parentElement?.clientWidth || 200; c.height = c.parentElement?.clientHeight || 200; }
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  // ─── State Label ─────────────────────────────────────────────────────────────

  const stateLabel: Partial<Record<AssistantState, string>> = {
    PLANNING: 'PLANNING', EXECUTING: 'EXECUTING', VERIFYING: 'VERIFYING',
    THINKING: 'THINKING', LISTENING: 'LISTENING', SUCCESS: 'COMPLETED', ERROR: 'ERROR',
  };

  const col = stateColors[state];

  if (isMinimal) {
    return (
      <div
        style={{ ...styles.minimalWrap, borderColor: col.ring, boxShadow: `0 0 24px ${col.glow}` }}
        onClick={() => setIsMinimal(false)}
        title="Click to expand AUREX"
      >
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height: '100%', borderRadius: '50%' }}
        />
      </div>
    );
  }

  return (
    <div style={{ ...styles.card, boxShadow: `0 20px 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.06), inset 0 0 60px ${col.glow}` }}>

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={{ ...styles.statusDot, background: col.ring, boxShadow: `0 0 8px ${col.ring}` }} />
          <span style={styles.brandText}>AUREX</span>
          {stateLabel[state] && (
            <span style={{ ...styles.statePill, borderColor: col.ring, color: col.ring }}>
              {stateLabel[state]}
            </span>
          )}
        </div>
        <div style={styles.headerRight}>
          {/* Screen aware badge */}
          <button
            style={{ ...styles.iconBtn, color: screenAware ? '#10b981' : '#475569', background: screenAware ? 'rgba(16,185,129,0.12)' : 'rgba(255,255,255,0.04)' }}
            onClick={toggleScreenAware}
            title={screenAware ? 'Screen Aware ON — click to disable' : 'Enable Screen Awareness'}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="2" y="3" width="20" height="14" rx="2" />
              <path d="M8 21h8M12 17v4" />
            </svg>
            {screenAware && <span style={styles.screenBadge}>SCREEN AWARE</span>}
          </button>
          {/* Minimal mode */}
          <button style={styles.iconBtn} onClick={() => setIsMinimal(true)} title="Minimal Mode">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Orb Canvas ─────────────────────────────────────────────────────── */}
      <div
        style={{ ...styles.orbWrap }}
        onClick={() => { if (state === 'IDLE') startListening(); else if (state === 'LISTENING') stopListening(); }}
        title="Click or hold Space to activate"
      >
        <canvas ref={canvasRef} style={styles.orbCanvas} />
        {/* Step indicator overlay */}
        {(state === 'EXECUTING' || state === 'VERIFYING') && plan && (
          <div style={styles.stepOverlay}>
            <span style={styles.stepLabel}>{plan.progress}</span>
          </div>
        )}
      </div>

      {/* ── Status text ────────────────────────────────────────────────────── */}
      <div style={styles.statusRow}>
        <span style={{ ...styles.statusText, color: col.ring }}>{statusText}</span>
        {currentStep && (state === 'EXECUTING' || state === 'VERIFYING') && (
          <span style={styles.stepText}>{currentStep}</span>
        )}
      </div>

      {/* ── Plan Panel ─────────────────────────────────────────────────────── */}
      {plan && plan.steps?.length > 0 && (
        <div style={styles.planPanel}>
          <div style={styles.planHeader}>
            <span style={styles.planIcon}>⬡</span>
            <span style={styles.planTitle}>TASK PLAN</span>
            <span style={styles.planProgress}>{plan.progress}</span>
          </div>
          <div style={styles.stepsList}>
            {plan.steps.map((step) => {
              const icons: Record<string, string> = { done: '✓', running: '→', failed: '✗', pending: '○', skipped: '–' };
              const colors: Record<string, string> = { done: '#22c55e', running: '#38bdf8', failed: '#ef4444', pending: '#475569', skipped: '#334155' };
              return (
                <div key={step.id} style={{ ...styles.stepItem, color: colors[step.status] || '#475569' }}>
                  <span style={styles.stepIcon}>{icons[step.status] || '○'}</span>
                  <span style={styles.stepDesc}>{step.description}</span>
                  {step.risk === 'HIGH' && <span style={styles.riskBadge}>HIGH</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Transcript ─────────────────────────────────────────────────────── */}
      <div style={styles.transcript}>
        {userQuery ? (
          <span style={styles.queryText}>"{userQuery}"</span>
        ) : assistantReply ? (
          <span style={styles.replyText}>{assistantReply}</span>
        ) : (
          <span style={styles.hintText}>Hold Space · Click orb · Say Hey AUREX</span>
        )}
      </div>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <div style={styles.footer}>
        <span style={styles.footerHint}>Ctrl+Space to activate · Double-clap supported</span>
      </div>
    </div>
  );
};

// ─── Styles ────────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  card: {
    width: '360px',
    background: 'rgba(8, 10, 20, 0.92)',
    border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: '24px',
    padding: '18px 20px 14px',
    backdropFilter: 'blur(32px)',
    WebkitBackdropFilter: 'blur(32px)',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    fontFamily: "'Inter', 'SF Pro Display', system-ui, sans-serif",
    userSelect: 'none',
    pointerEvents: 'auto',
    transition: 'box-shadow 0.4s ease',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  statusDot: {
    width: '7px',
    height: '7px',
    borderRadius: '50%',
    transition: 'all 0.3s ease',
    flexShrink: 0,
  },
  brandText: {
    fontSize: '11px',
    fontWeight: 800,
    letterSpacing: '3px',
    color: 'rgba(255,255,255,0.9)',
    textTransform: 'uppercase',
  },
  statePill: {
    fontSize: '9px',
    fontWeight: 700,
    letterSpacing: '1.5px',
    padding: '2px 7px',
    borderRadius: '100px',
    border: '1px solid',
    opacity: 0.9,
    textTransform: 'uppercase',
    transition: 'all 0.3s ease',
  },
  iconBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '5px',
    padding: '4px 8px',
    borderRadius: '8px',
    border: 'none',
    cursor: 'pointer',
    fontSize: '10px',
    fontWeight: 600,
    letterSpacing: '0.5px',
    transition: 'all 0.2s ease',
    outline: 'none',
  },
  screenBadge: {
    fontSize: '8px',
    fontWeight: 700,
    letterSpacing: '1px',
    opacity: 0.9,
  },
  orbWrap: {
    width: '100%',
    height: '200px',
    borderRadius: '16px',
    background: 'rgba(255,255,255,0.02)',
    overflow: 'hidden',
    cursor: 'pointer',
    position: 'relative',
    border: '1px solid rgba(255,255,255,0.04)',
  },
  orbCanvas: {
    width: '100%',
    height: '100%',
    display: 'block',
  },
  stepOverlay: {
    position: 'absolute',
    bottom: '10px',
    right: '12px',
    pointerEvents: 'none',
  },
  stepLabel: {
    fontSize: '10px',
    fontWeight: 700,
    color: 'rgba(56,189,248,0.8)',
    letterSpacing: '1px',
  },
  statusRow: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '3px',
  },
  statusText: {
    fontSize: '11px',
    fontWeight: 600,
    letterSpacing: '2px',
    textTransform: 'uppercase',
    transition: 'color 0.3s ease',
  },
  stepText: {
    fontSize: '11px',
    color: 'rgba(255,255,255,0.4)',
    fontWeight: 400,
    textAlign: 'center',
    maxWidth: '280px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  planPanel: {
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '12px',
    padding: '10px 12px',
  },
  planHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '7px',
    marginBottom: '8px',
  },
  planIcon: {
    fontSize: '11px',
    color: '#7c3aed',
  },
  planTitle: {
    fontSize: '10px',
    fontWeight: 700,
    letterSpacing: '2px',
    color: 'rgba(255,255,255,0.6)',
    flex: 1,
  },
  planProgress: {
    fontSize: '10px',
    fontWeight: 600,
    color: '#38bdf8',
    letterSpacing: '0.5px',
  },
  stepsList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  stepItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '7px',
    fontSize: '11px',
    fontWeight: 500,
    transition: 'color 0.25s ease',
  },
  stepIcon: {
    fontSize: '11px',
    flexShrink: 0,
    width: '14px',
    textAlign: 'center',
  },
  stepDesc: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  riskBadge: {
    fontSize: '8px',
    fontWeight: 700,
    color: '#f97316',
    border: '1px solid rgba(249,115,22,0.4)',
    padding: '1px 4px',
    borderRadius: '4px',
    flexShrink: 0,
  },
  transcript: {
    minHeight: '28px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    textAlign: 'center',
    padding: '0 8px',
  },
  queryText: {
    fontSize: '12px',
    fontWeight: 500,
    color: 'rgba(99,179,237,0.9)',
    fontStyle: 'italic',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: '100%',
  },
  replyText: {
    fontSize: '11.5px',
    fontWeight: 400,
    color: 'rgba(255,255,255,0.7)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    maxWidth: '100%',
    lineHeight: '1.5',
  } as any,
  hintText: {
    fontSize: '10.5px',
    color: 'rgba(255,255,255,0.2)',
    fontWeight: 400,
    letterSpacing: '0.3px',
  },
  footer: {
    display: 'flex',
    justifyContent: 'center',
    paddingTop: '2px',
  },
  footerHint: {
    fontSize: '9px',
    color: 'rgba(255,255,255,0.12)',
    letterSpacing: '0.5px',
  },
  minimalWrap: {
    width: '64px',
    height: '64px',
    borderRadius: '50%',
    background: 'rgba(8,10,20,0.9)',
    border: '2px solid',
    backdropFilter: 'blur(20px)',
    cursor: 'pointer',
    overflow: 'hidden',
    transition: 'box-shadow 0.3s ease',
  },
};
