import React, { useState, useEffect, useRef, useCallback } from 'react';

// ─── Types ──────────────────────────────────────────────────────────────────
type AState = 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

const isQt = typeof navigator !== 'undefined' && /QtWebEngine/i.test(navigator.userAgent);
const API = () => (typeof window !== 'undefined' && window.location.origin.startsWith('http'))
  ? window.location.origin
  : 'http://127.0.0.1:8765';

// ─── Particle ────────────────────────────────────────────────────────────────
interface P {
  x: number; y: number; vx: number; vy: number;
  life: number; max: number; size: number; hue: number; orbit: boolean;
  angle: number; r: number; speed: number;
}
function mkParticle(cx: number, cy: number, s: AState): P {
  const orbit = s === 'THINKING';
  const angle = Math.random() * Math.PI * 2;
  const r = orbit ? 22 + Math.random() * 14 : 10 + Math.random() * 40;
  const hues: Record<AState, number> = { IDLE: 220, LISTENING: 160, THINKING: 265, SPEAKING: 210 };
  return {
    x: orbit ? cx + Math.cos(angle) * r : cx + (Math.random() - 0.5) * 80,
    y: orbit ? cy + Math.sin(angle) * r : cy + (Math.random() - 0.5) * 80,
    vx: orbit ? 0 : (Math.random() - 0.5) * 0.4,
    vy: orbit ? 0 : -0.2 - Math.random() * 0.3,
    life: 0, max: 60 + Math.random() * 80,
    size: 0.7 + Math.random() * 1.4,
    hue: (hues[s] || 220) + (Math.random() - 0.5) * 25,
    orbit, angle, r,
    speed: (0.008 + Math.random() * 0.014) * (Math.random() > 0.5 ? 1 : -1),
  };
}

// ─── Component ───────────────────────────────────────────────────────────────
export const VoiceSurface: React.FC = () => {
  const [state, setState] = useState<AState>('IDLE');
  const [status, setStatus] = useState('Standing by');
  const [query, setQuery] = useState('');
  const [reply, setReply] = useState('');

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const tick = useRef(0);
  const particles = useRef<P[]>([]);
  const stateRef = useRef<AState>('IDLE');

  // Audio refs
  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const speechRef = useRef('');
  const srRef = useRef<any>(null);

  // Stable fn refs to avoid stale closures
  const executeRef = useRef<((cmd: string) => Promise<void>) | undefined>(undefined);
  const sendAudioRef = useRef<((blob: Blob) => Promise<void>) | undefined>(undefined);
  const speakRef = useRef<((t: string) => void) | undefined>(undefined);

  // State colors — all work on white background
  const COL: Record<AState, { dot: string; ring: string; orb: string; glow: string }> = {
    IDLE:      { dot: '#94a3b8', ring: '#cbd5e1', orb: '200,210,230', glow: 'rgba(148,163,184,0.15)' },
    LISTENING: { dot: '#059669', ring: '#10b981', orb: '5,150,105',   glow: 'rgba(5,150,105,0.18)' },
    THINKING:  { dot: '#7c3aed', ring: '#7c3aed', orb: '124,58,237',  glow: 'rgba(124,58,237,0.18)' },
    SPEAKING:  { dot: '#0284c7', ring: '#0ea5e9', orb: '2,132,199',   glow: 'rgba(2,132,199,0.18)' },
  };

  const setS = useCallback((s: AState, txt: string) => {
    setState(s); setStatus(txt); stateRef.current = s;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Audio Setup ────────────────────────────────────────────────────────────
  const setupAudio = useCallback(async () => {
    if (ctxRef.current && streamRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      streamRef.current = stream;

      const ac = new (window.AudioContext || (window as any).webkitAudioContext)();
      ctxRef.current = ac;
      const src = ac.createMediaStreamSource(stream);
      const an = ac.createAnalyser();
      an.fftSize = 128; an.smoothingTimeConstant = 0.6;
      src.connect(an);
      analyserRef.current = an;

      const mr = new MediaRecorder(stream);
      mr.ondataavailable = (e) => { if (e.data?.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
        chunksRef.current = [];
        if (blob.size > 1500) sendAudioRef.current?.(blob);
        else setS('IDLE', 'Standing by');
      };
      recRef.current = mr;

      const SR = !isQt && ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
      if (SR) {
        const r = new SR();
        r.continuous = true; r.interimResults = true; r.lang = 'en-US';
        r.onresult = (ev: any) => {
          let t = '';
          for (let i = ev.resultIndex; i < ev.results.length; i++) t += ev.results[i][0].transcript;
          t = t.trim();
          if (t) { setQuery(t); speechRef.current = t; }
        };
        r.onend = () => { if (stateRef.current === 'LISTENING') try { r.start(); } catch (_) {} };
        srRef.current = r;
      }
    } catch (e) { console.warn('Audio setup:', e); }
  }, [setS]);

  // ─── Listen ──────────────────────────────────────────────────────────────────
  const startListen = useCallback(async () => {
    if (stateRef.current === 'LISTENING' || stateRef.current === 'THINKING') return;
    await setupAudio();
    setS('LISTENING', 'Listening...');
    setQuery(''); setReply(''); speechRef.current = ''; chunksRef.current = [];
    if (recRef.current?.state === 'inactive') try { recRef.current.start(100); } catch (_) {}
    if (srRef.current) try { srRef.current.start(); } catch (_) {}
  }, [setupAudio, setS]);

  const stopListen = useCallback(() => {
    if (stateRef.current !== 'LISTENING') return;
    if (recRef.current?.state === 'recording') try { recRef.current.stop(); } catch (_) {}
    if (srRef.current) try { srRef.current.stop(); } catch (_) {}
    setTimeout(() => {
      const txt = speechRef.current.trim();
      if (txt) { speechRef.current = ''; executeRef.current?.(txt); }
      else if (chunksRef.current.length > 0) {
        const blob = new Blob(chunksRef.current, { type: recRef.current?.mimeType || 'audio/webm' });
        chunksRef.current = [];
        if (blob.size > 1500) sendAudioRef.current?.(blob);
        else setS('IDLE', 'Standing by');
      } else setS('IDLE', 'Standing by');
    }, 120);
  }, [setS]);

  // ─── Speak ────────────────────────────────────────────────────────────────────
  const speak = useCallback((text: string) => {
    if (isQt) {
      setS('SPEAKING', 'Speaking...');
      setTimeout(() => setS('IDLE', 'Standing by'), Math.max(1600, Math.min(9000, text.split(/\s+/).length * 350)));
      return;
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05; u.pitch = 0.95;
      u.onstart = () => setS('SPEAKING', 'Speaking...');
      const done = () => setS('IDLE', 'Standing by');
      u.onend = done; u.onerror = done;
      window.speechSynthesis.speak(u);
    } else setS('IDLE', 'Standing by');
  }, [setS]);
  speakRef.current = speak;

  // ─── Execute Command ─────────────────────────────────────────────────────────
  const executeCmd = useCallback(async (cmd: string) => {
    const clean = cmd.trim();
    if (!clean) { setS('IDLE', 'Standing by'); return; }
    setQuery(clean);
    setS('THINKING', 'Processing...');
    try {
      const res = await fetch(`${API()}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(isQt ? { 'X-Client': 'desktop-widget' } : {}) },
        body: JSON.stringify({ command: clean, client: isQt ? 'desktop-widget' : 'web', speak: isQt }),
      });
      const data = await res.json();
      const r = data.response || 'Done.';
      setReply(r);
      speakRef.current?.(r);
    } catch {
      const fb = `Processed: "${clean}".`;
      setReply(fb);
      speakRef.current?.(fb);
    }
  }, [setS]);
  executeRef.current = executeCmd;

  // ─── Send Audio ───────────────────────────────────────────────────────────────
  const sendAudio = useCallback(async (blob: Blob) => {
    setS('THINKING', 'Processing...');
    try {
      const res = await fetch(`${API()}/api/voice`, {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'audio/webm', ...(isQt ? { 'X-Client': 'desktop-widget' } : {}) },
        body: blob,
      });
      const data = await res.json();
      if (data.transcript) setQuery(data.transcript);
      const r = data.response || 'Done.';
      setReply(r);
      speakRef.current?.(r);
    } catch {
      setS('IDLE', 'Standing by');
    }
  }, [setS]);
  sendAudioRef.current = sendAudio;

  // ─── Keys ─────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const kd = (e: KeyboardEvent) => {
      if ((e.code === 'Space' || (e.ctrlKey && e.code === 'Space')) && !e.repeat) {
        e.preventDefault(); startListen();
      }
    };
    const ku = (e: KeyboardEvent) => {
      if (e.code === 'Space') { e.preventDefault(); stopListen(); }
    };
    window.addEventListener('keydown', kd);
    window.addEventListener('keyup', ku);
    (window as any).__aurexStartListen = startListen;
    (window as any).__aurexStopListen = stopListen;
    return () => { window.removeEventListener('keydown', kd); window.removeEventListener('keyup', ku); };
  }, [startListen, stopListen]);

  // ─── Draw ─────────────────────────────────────────────────────────────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;
    const s = stateRef.current;
    const t = tick.current;
    const c = COL[s];

    // Clear — slight alpha trail on dark, full clear for light
    ctx.clearRect(0, 0, W, H);

    // Mic level
    let mic = 0;
    if (analyserRef.current && s === 'LISTENING') {
      const f = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(f);
      let sum = 0;
      for (let b = 2; b < Math.min(30, f.length); b++) sum += f[b];
      mic = sum / (28 * 255);
    }

    // Particles — spawn
    const rate = s === 'IDLE' ? 0.15 : s === 'LISTENING' ? 1.5 + mic * 6 : 1.2;
    if (Math.random() < rate * 0.08) particles.current.push(mkParticle(cx, cy, s));
    if (particles.current.length > 80) particles.current.splice(0, 3);

    for (let i = particles.current.length - 1; i >= 0; i--) {
      const p = particles.current[i];
      p.life++;
      if (p.orbit) { p.angle += p.speed; p.x = cx + Math.cos(p.angle) * p.r; p.y = cy + Math.sin(p.angle) * p.r; }
      else { p.x += p.vx; p.y += p.vy; }
      if (p.life >= p.max) { particles.current.splice(i, 1); continue; }
      const prog = p.life / p.max;
      const alpha = prog < 0.2 ? prog / 0.2 : prog > 0.75 ? (1 - prog) / 0.25 : 1;
      ctx.save();
      ctx.globalAlpha = alpha * (s === 'IDLE' ? 0.35 : 0.65);
      ctx.fillStyle = `hsl(${p.hue},75%,50%)`;
      ctx.shadowColor = `hsl(${p.hue},85%,55%)`;
      ctx.shadowBlur = 3;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // Rings
    const rings = s === 'IDLE' ? 2 : s === 'THINKING' ? 4 : 3;
    for (let i = 0; i < rings; i++) {
      const baseR = 14 + i * 8;
      const pulse = s === 'IDLE'
        ? Math.sin(t * 0.7 + i * 1.2) * 1.2
        : Math.sin(t * 1.6 + i * 1.1) * (2.5 + mic * 8);
      const rr = Math.max(3, baseR + pulse);
      const alpha = s === 'IDLE' ? 0.12 + Math.sin(t * 0.9 + i) * 0.04 : 0.22 + Math.sin(t * 1.4 + i) * 0.08;

      ctx.beginPath();
      ctx.strokeStyle = c.ring;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = s === 'IDLE' ? 0.7 : 1.0 + i * 0.15;
      ctx.arc(cx, cy, rr, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // Rotating arcs for THINKING
    if (s === 'THINKING') {
      const ar = 28;
      for (let i = 0; i < 3; i++) {
        const st = t * 2.4 + (i * Math.PI * 2) / 3;
        ctx.beginPath();
        ctx.strokeStyle = c.ring;
        ctx.globalAlpha = 0.5 + 0.3 * Math.sin(t * 2 + i * 1.5);
        ctx.lineWidth = 1.5;
        ctx.arc(cx, cy, ar, st, st + 0.9);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    // Audio waveform ring for LISTENING / SPEAKING
    if ((s === 'LISTENING' || s === 'SPEAKING') && analyserRef.current) {
      const fd = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(fd);
      const N = 48, baseWR = 30;
      ctx.beginPath();
      for (let i = 0; i < N; i++) {
        const ang = (i / N) * Math.PI * 2 - Math.PI / 2;
        const bin = Math.floor((i / N) * fd.length * 0.4);
        const lvl = (fd[bin] || 0) / 255;
        const wr = baseWR + lvl * 12;
        const px = cx + Math.cos(ang) * wr, py = cy + Math.sin(ang) * wr;
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.strokeStyle = c.ring;
      ctx.globalAlpha = 0.45;
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // Core orb
    const cR = s === 'IDLE'
      ? 8 + Math.sin(t * 0.55) * 1
      : s === 'LISTENING' ? 9 + Math.sin(t * 1.3) * (1.5 + mic * 7)
      : s === 'THINKING'  ? 8 + Math.sin(t * 1.2) * 1.5
      : 9 + Math.sin(t * 1.8) * 2;

    // Glow
    const gGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, cR + 16);
    gGrad.addColorStop(0, `rgba(${c.orb},0.25)`);
    gGrad.addColorStop(0.5, `rgba(${c.orb},0.08)`);
    gGrad.addColorStop(1, `rgba(${c.orb},0)`);
    ctx.fillStyle = gGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, cR + 16, 0, Math.PI * 2);
    ctx.fill();

    // Orb fill
    const oGrad = ctx.createRadialGradient(cx - cR * 0.28, cy - cR * 0.28, 0, cx, cy, cR);
    oGrad.addColorStop(0, `rgba(${c.orb},0.95)`);
    oGrad.addColorStop(0.6, `rgba(${c.orb},0.75)`);
    oGrad.addColorStop(1, `rgba(${c.orb},0.35)`);
    ctx.fillStyle = oGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, cR, 0, Math.PI * 2);
    ctx.fill();

    // Specular highlight
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.beginPath();
    ctx.arc(cx - cR * 0.28, cy - cR * 0.3, cR * 0.28, 0, Math.PI * 2);
    ctx.fill();
  }, []); // stable — reads stateRef and tick ref dynamically

  // ─── Animation loop ──────────────────────────────────────────────────────────
  useEffect(() => {
    const speeds: Record<AState, number> = { IDLE: 0.022, LISTENING: 0.065, THINKING: 0.052, SPEAKING: 0.075 };
    let running = true;
    const loop = () => {
      if (!running) return;
      tick.current += speeds[stateRef.current] ?? 0.04;
      draw();
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => { running = false; if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [draw]);

  // ─── Canvas resize ───────────────────────────────────────────────────────────
  useEffect(() => {
    const resize = () => {
      const c = canvasRef.current;
      if (c) { c.width = c.parentElement?.clientWidth ?? 80; c.height = c.parentElement?.clientHeight ?? 80; }
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  // ─── Render ──────────────────────────────────────────────────────────────────
  const dotColors: Record<AState, string> = {
    IDLE: '#94a3b8', LISTENING: '#059669', THINKING: '#7c3aed', SPEAKING: '#0284c7',
  };
  const dotShadow: Record<AState, string> = {
    IDLE: 'none', LISTENING: '0 0 8px rgba(5,150,105,0.7)', THINKING: '0 0 8px rgba(124,58,237,0.7)', SPEAKING: '0 0 8px rgba(2,132,199,0.7)',
  };

  return (
    <div
      style={{
        width: '350px',
        backgroundColor: 'rgba(255,255,255,0.88)',
        border: '1px solid rgba(226,232,240,0.95)',
        borderRadius: '20px',
        padding: '14px 18px',
        boxShadow: `0 16px 36px rgba(15,23,42,0.10), 0 2px 6px rgba(15,23,42,0.04)`,
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        display: 'flex',
        flexDirection: 'column' as const,
        gap: '10px',
        pointerEvents: 'auto' as const,
        userSelect: 'none' as const,
        fontFamily: "'Inter','SF Pro Display',system-ui,sans-serif",
      }}
      onClick={() => { if (stateRef.current === 'IDLE') startListen(); else if (stateRef.current === 'LISTENING') stopListen(); }}
      title="Click or hold Space to speak"
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
          <span style={{
            width: '8px', height: '8px', borderRadius: '50%',
            backgroundColor: dotColors[state],
            boxShadow: dotShadow[state],
            transition: 'all 0.25s ease', flexShrink: 0,
          }} />
          <span style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '1.6px', color: '#0F172A', textTransform: 'uppercase' as const }}>
            AUREX
          </span>
          <span style={{ fontSize: '11px', color: '#475569', fontWeight: 500 }}>{status}</span>
        </div>
      </div>

      {/* Orb + Wave row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px',
        backgroundColor: 'rgba(241,245,249,0.65)', borderRadius: '12px', padding: '6px 10px' }}>
        {/* Orb */}
        <div style={{ width: '64px', height: '64px', flexShrink: 0, position: 'relative' as const }}>
          <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
        </div>

        {/* Right side: waveform bars */}
        <div style={{ flex: 1, height: '48px', display: 'flex', alignItems: 'center', overflow: 'hidden' }}>
          <WaveBars state={state} analyser={analyserRef.current} />
        </div>
      </div>

      {/* Transcript */}
      <div style={{ minHeight: '22px', display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center' as const, overflow: 'hidden' }}>
        {query ? (
          <span style={{ fontSize: '12.5px', fontWeight: 600, color: '#0284C7', fontStyle: 'italic', whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>"{query}"</span>
        ) : reply ? (
          <span style={{ fontSize: '12px', fontWeight: 600, color: '#0F172A', whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>{reply}</span>
        ) : (
          <span style={{ fontSize: '11px', color: '#64748B', fontWeight: 500 }}>Hold Spacebar to speak</span>
        )}
      </div>
    </div>
  );
};

// ─── Wave Bars (classic style, audio-reactive) ──────────────────────────────
const WaveBars: React.FC<{ state: AState; analyser: AnalyserNode | null }> = ({ state, analyser }) => {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const raf = useRef<number | null>(null);
  const tick = useRef(0);

  const NUM = 40;
  const envelope = useRef<number[]>([]);
  if (envelope.current.length === 0) {
    const centers = [{ c: 0.22, a: 0.82, w: 0.08 }, { c: 0.52, a: 0.94, w: 0.09 }, { c: 0.80, a: 0.86, w: 0.08 }];
    for (let i = 0; i < NUM; i++) {
      const n = i / (NUM - 1);
      let v = 0.08;
      for (const { c, a, w } of centers) v += a * Math.exp(-Math.pow(n - c, 2) / (2 * w * w));
      v *= 0.72 + 0.38 * Math.sin(i * 1.85) * Math.cos(i * 0.9);
      v *= Math.pow(Math.sin(n * Math.PI), 0.45);
      envelope.current.push(Math.max(0.08, Math.min(0.96, v)));
    }
  }

  useEffect(() => {
    let running = true;
    const draw = () => {
      if (!running) return;
      const canvas = ref.current;
      if (!canvas) { raf.current = requestAnimationFrame(draw); return; }
      const ctx = canvas.getContext('2d');
      if (!ctx) { raf.current = requestAnimationFrame(draw); return; }
      const W = canvas.width, H = canvas.height, cy = H / 2, maxH = (H - 4) / 2;
      ctx.clearRect(0, 0, W, H);

      let mic = 0;
      if (analyser && state === 'LISTENING') {
        const f = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(f);
        let s = 0;
        for (let b = 2; b < Math.min(28, f.length); b++) s += f[b];
        mic = s / (26 * 255);
      }

      const sp = state === 'IDLE' ? 0 : state === 'LISTENING' ? 0.07 : state === 'SPEAKING' ? 0.13 : 0.08;
      tick.current += sp;

      const bspc = W / NUM, bw = Math.max(2.2, bspc * 0.62);
      const sx = (W - NUM * bspc) / 2;

      for (let i = 0; i < NUM; i++) {
        const norm = i / (NUM - 1);
        const bx = sx + i * bspc + bspc / 2;
        let amp = envelope.current[i];

        if (state === 'LISTENING') {
          const ripple = Math.sin(norm * 12 - tick.current * 3.6) * 0.28 + Math.cos(norm * 6 + tick.current * 2.1) * 0.08;
          amp = Math.max(0.08, Math.min(0.98, amp * (0.85 + mic * 2.4) + ripple * mic));
        } else if (state === 'THINKING') {
          amp = Math.max(0.12, Math.min(0.92, 0.45 + Math.sin(norm * 9 + tick.current * 2.6) * 0.35 + Math.cos(norm * 15 - tick.current * 3.2) * 0.2));
        } else if (state === 'SPEAKING') {
          amp = Math.max(0.12, Math.min(0.98, amp * 1.35 + Math.sin(tick.current * 6 + i * 0.35) * 0.26 + Math.sin(tick.current * 11.5 + i * 0.55) * 0.14));
        } else {
          amp = amp * 0.5;
        }

        const bh = Math.max(2, amp * maxH);
        let r = 219, g = 39, b = 119;
        if (norm < 0.33) { const t2 = norm / 0.33; r = Math.round(219 + (124 - 219) * t2); g = Math.round(39 + (58 - 39) * t2); b = Math.round(119 + (237 - 119) * t2); }
        else if (norm < 0.66) { const t2 = (norm - 0.33) / 0.33; r = Math.round(124 + (2 - 124) * t2); g = Math.round(58 + (132 - 58) * t2); b = Math.round(237 + (199 - 237) * t2); }
        else { r = 2; g = 132; b = 199; }

        ctx.beginPath();
        ctx.strokeStyle = `rgb(${r},${g},${b})`;
        ctx.lineWidth = bw;
        ctx.lineCap = 'round';
        ctx.moveTo(bx, cy - bh);
        ctx.lineTo(bx, cy + bh);
        ctx.stroke();
      }
      raf.current = requestAnimationFrame(draw);
    };
    raf.current = requestAnimationFrame(draw);
    return () => { running = false; if (raf.current) cancelAnimationFrame(raf.current); };
  }, [state, analyser]);

  useEffect(() => {
    const resize = () => {
      const c = ref.current;
      if (c) { c.width = c.parentElement?.clientWidth ?? 200; c.height = c.parentElement?.clientHeight ?? 48; }
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  return <canvas ref={ref} style={{ width: '100%', height: '100%' }} />;
};
