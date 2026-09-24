import React, { useState, useEffect, useRef, useCallback } from 'react';

// ─── Types ──────────────────────────────────────────────────────────────────────
type AState = 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

const isQt = typeof navigator !== 'undefined' && /QtWebEngine/i.test(navigator.userAgent);
const API  = () =>
  typeof window !== 'undefined' && window.location.origin.startsWith('http')
    ? window.location.origin
    : 'http://127.0.0.1:8765';

// ─── Wake-word patterns ─────────────────────────────────────────────────────────
const WAKE_PATTERNS = [
  /^(?:hey\s+)?aurex[,\.\s!]*/i,
  /^(?:hey\s+)?rex[,\.\s!]*/i,
  /^(?:hey\s+)?jarvis[,\.\s!]*/i,
  /^hi\s+aurex[,\.\s!]*/i,
  /^ok\s+aurex[,\.\s!]*/i,
];

function stripWake(text: string): { found: boolean; command: string } {
  const t = text.trim();
  for (const p of WAKE_PATTERNS) {
    const m = t.match(p);
    if (m) return { found: true, command: t.slice(m[0].length).trim() };
  }
  return { found: false, command: t };
}

// ─── Particle System (Zero green — luxury Violet, Cyan, Slate) ──────────────────
interface Pt {
  x: number; y: number; vx: number; vy: number;
  life: number; max: number; size: number; hue: number;
  orbit: boolean; angle: number; r: number; speed: number;
}

function mkPt(cx: number, cy: number, s: AState): Pt {
  const orbit = s === 'THINKING';
  const angle = Math.random() * Math.PI * 2;
  const r     = orbit ? 18 + Math.random() * 12 : 8 + Math.random() * 30;
  // Hues: IDLE=220 (Slate/Blue), LISTENING=265 (Violet), THINKING=280 (Royal Purple), SPEAKING=198 (Electric Cyan)
  const hues: Record<AState, number> = { IDLE: 220, LISTENING: 265, THINKING: 280, SPEAKING: 198 };
  return {
    x: orbit ? cx + Math.cos(angle) * r : cx + (Math.random() - 0.5) * 60,
    y: orbit ? cy + Math.sin(angle) * r : cy + (Math.random() - 0.5) * 60,
    vx: orbit ? 0 : (Math.random() - 0.5) * 0.3,
    vy: orbit ? 0 : -0.15 - Math.random() * 0.2,
    life: 0,
    max: 50 + Math.random() * 65,
    size: 0.6 + Math.random() * 1.2,
    hue: (hues[s] ?? 260) + (Math.random() - 0.5) * 16,
    orbit, angle, r,
    speed: (0.01 + Math.random() * 0.012) * (Math.random() > 0.5 ? 1 : -1),
  };
}

// ─── Orb Canvas (Particle core with orbital resonance) ──────────────────────────
interface OrbProps {
  state: AState;
  analyser: AnalyserNode | null;
}

const Orb: React.FC<OrbProps> = ({ state, analyser }) => {
  const ref  = useRef<HTMLCanvasElement | null>(null);
  const raf  = useRef<number | null>(null);
  const tick = useRef(0);
  const pts  = useRef<Pt[]>([]);
  const stateRef = useRef(state);
  stateRef.current = state;

  const COL: Record<AState, { ring: string; orb: string }> = {
    IDLE:      { ring: '#94a3b8', orb: '148,163,184' },
    LISTENING: { ring: '#8b5cf6', orb: '139,92,246'  }, // Electric Violet (No green!)
    THINKING:  { ring: '#7c3aed', orb: '124,58,237'  }, // Deep Purple
    SPEAKING:  { ring: '#0284c7', orb: '2,132,199'   }, // Electric Cyan
  };

  useEffect(() => {
    let running = true;
    const speeds: Record<AState, number> = { IDLE: 0.022, LISTENING: 0.06, THINKING: 0.05, SPEAKING: 0.07 };

    const draw = () => {
      if (!running) return;
      const canvas = ref.current;
      if (!canvas) { raf.current = requestAnimationFrame(draw); return; }
      const ctx = canvas.getContext('2d');
      if (!ctx) { raf.current = requestAnimationFrame(draw); return; }
      const s  = stateRef.current;
      const c  = COL[s];
      const W  = canvas.width, H = canvas.height;
      const cx = W / 2,        cy = H / 2;
      const t  = tick.current;
      tick.current += speeds[s] ?? 0.04;

      ctx.clearRect(0, 0, W, H);

      // Mic level
      let mic = 0;
      if (analyser && s === 'LISTENING') {
        const f = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(f);
        let sum = 0;
        for (let b = 2; b < Math.min(28, f.length); b++) sum += f[b];
        mic = sum / (26 * 255);
      }

      // Particles
      const rate = s === 'IDLE' ? 0.08 : s === 'LISTENING' ? 1.2 + mic * 4 : 1.0;
      if (Math.random() < rate * 0.08) pts.current.push(mkPt(cx, cy, s));
      if (pts.current.length > 55) pts.current.splice(0, 3);

      for (let i = pts.current.length - 1; i >= 0; i--) {
        const p = pts.current[i];
        p.life++;
        if (p.orbit) {
          p.angle += p.speed;
          p.x = cx + Math.cos(p.angle) * p.r;
          p.y = cy + Math.sin(p.angle) * p.r;
        } else {
          p.x += p.vx;
          p.y += p.vy;
        }
        if (p.life >= p.max) { pts.current.splice(i, 1); continue; }
        const prog = p.life / p.max;
        const a = prog < 0.2 ? prog / 0.2 : prog > 0.75 ? (1 - prog) / 0.25 : 1;
        ctx.save();
        ctx.globalAlpha = a * (s === 'IDLE' ? 0.3 : 0.65);
        ctx.fillStyle = `hsl(${p.hue},75%,52%)`;
        ctx.shadowColor = `hsl(${p.hue},80%,55%)`;
        ctx.shadowBlur = 3;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      // Smooth concentric rings
      const rings = s === 'THINKING' ? 4 : s === 'IDLE' ? 2 : 3;
      for (let i = 0; i < rings; i++) {
        const br  = 10 + i * 7;
        const pls = s === 'IDLE' ? Math.sin(t * 0.65 + i) * 1 : Math.sin(t * 1.5 + i) * (2 + mic * 6);
        const rr  = Math.max(3, br + pls);
        const al  = s === 'IDLE' ? 0.10 + Math.sin(t * 0.8 + i) * 0.03 : 0.22 + Math.sin(t * 1.3 + i) * 0.08;
        ctx.beginPath();
        ctx.strokeStyle = c.ring;
        ctx.globalAlpha = al;
        ctx.lineWidth = s === 'IDLE' ? 0.6 : 0.9 + i * 0.12;
        ctx.arc(cx, cy, rr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Orbital thinking arcs
      if (s === 'THINKING') {
        for (let i = 0; i < 3; i++) {
          const st = t * 2.3 + (i * Math.PI * 2) / 3;
          ctx.beginPath();
          ctx.strokeStyle = c.ring;
          ctx.globalAlpha = 0.45 + 0.3 * Math.sin(t * 2 + i * 1.5);
          ctx.lineWidth = 1.4;
          ctx.arc(cx, cy, 24, st, st + 0.85);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      }

      // Waveform ring for LISTENING / SPEAKING
      if ((s === 'LISTENING' || s === 'SPEAKING') && analyser) {
        const fd = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(fd);
        const N = 40, wr0 = 26;
        ctx.beginPath();
        for (let i = 0; i < N; i++) {
          const ang = (i / N) * Math.PI * 2 - Math.PI / 2;
          const lv  = (fd[Math.floor((i / N) * fd.length * 0.4)] ?? 0) / 255;
          const wr  = wr0 + lv * 10;
          const px  = cx + Math.cos(ang) * wr, py = cy + Math.sin(ang) * wr;
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.strokeStyle = c.ring;
        ctx.globalAlpha = 0.4;
        ctx.lineWidth = 1.1;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Core orb
      const cR = s === 'IDLE' ? 7 + Math.sin(t * 0.5) * 0.8
        : s === 'LISTENING' ? 8 + Math.sin(t * 1.2) * (1.2 + mic * 5)
        : 8 + Math.sin(t * 1.1) * 1.4;

      // Glow
      const gg = ctx.createRadialGradient(cx, cy, 0, cx, cy, cR + 14);
      gg.addColorStop(0, `rgba(${c.orb},0.24)`);
      gg.addColorStop(0.5, `rgba(${c.orb},0.08)`);
      gg.addColorStop(1, `rgba(${c.orb},0)`);
      ctx.fillStyle = gg;
      ctx.beginPath();
      ctx.arc(cx, cy, cR + 14, 0, Math.PI * 2);
      ctx.fill();

      // Core fill
      const og = ctx.createRadialGradient(cx - cR * 0.28, cy - cR * 0.28, 0, cx, cy, cR);
      og.addColorStop(0, `rgba(${c.orb},0.94)`);
      og.addColorStop(0.6, `rgba(${c.orb},0.74)`);
      og.addColorStop(1, `rgba(${c.orb},0.32)`);
      ctx.fillStyle = og;
      ctx.beginPath();
      ctx.arc(cx, cy, cR, 0, Math.PI * 2);
      ctx.fill();

      // Specular highlight
      ctx.fillStyle = 'rgba(255,255,255,0.55)';
      ctx.beginPath();
      ctx.arc(cx - cR * 0.26, cy - cR * 0.28, cR * 0.27, 0, Math.PI * 2);
      ctx.fill();

      raf.current = requestAnimationFrame(draw);
    };
    raf.current = requestAnimationFrame(draw);
    return () => { running = false; if (raf.current) cancelAnimationFrame(raf.current); };
  }, [analyser]);

  useEffect(() => {
    const resize = () => {
      const c = ref.current;
      if (c) {
        c.width = c.parentElement?.clientWidth ?? 68;
        c.height = c.parentElement?.clientHeight ?? 68;
      }
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  return <canvas ref={ref} style={{ width: '100%', height: '100%', display: 'block' }} />;
};

// ─── Wave Bars (Rose → Indigo → Cyan gradient) ──────────────────────────────────
const WaveBars: React.FC<{ state: AState; analyser: AnalyserNode | null }> = ({ state, analyser }) => {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const raf = useRef<number | null>(null);
  const tick = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  const analyserRef = useRef(analyser);
  analyserRef.current = analyser;

  const N = 38;
  const env = useRef<number[]>([]);
  if (env.current.length === 0) {
    const centers = [{ c: 0.22, a: 0.82, w: 0.08 }, { c: 0.52, a: 0.95, w: 0.09 }, { c: 0.80, a: 0.86, w: 0.08 }];
    for (let i = 0; i < N; i++) {
      const n = i / (N - 1);
      let v = 0.08;
      for (const { c, a, w } of centers) v += a * Math.exp(-Math.pow(n - c, 2) / (2 * w * w));
      v *= 0.72 + 0.38 * Math.sin(i * 1.85) * Math.cos(i * 0.9);
      v *= Math.pow(Math.sin(n * Math.PI), 0.45);
      env.current.push(Math.max(0.08, Math.min(0.96, v)));
    }
  }

  useEffect(() => {
    let running = true;
    const speeds: Record<AState, number> = { IDLE: 0, LISTENING: 0.065, THINKING: 0.08, SPEAKING: 0.12 };

    const draw = () => {
      if (!running) return;
      const canvas = ref.current;
      if (!canvas) { raf.current = requestAnimationFrame(draw); return; }
      const ctx = canvas.getContext('2d');
      if (!ctx) { raf.current = requestAnimationFrame(draw); return; }

      const s = stateRef.current;
      const W = canvas.width, H = canvas.height;
      const cy = H / 2, maxH = (H - 4) / 2;
      ctx.clearRect(0, 0, W, H);

      tick.current += speeds[s] ?? 0;

      let mic = 0;
      if (analyserRef.current && s === 'LISTENING') {
        const f = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(f);
        let sum = 0;
        for (let b = 2; b < Math.min(28, f.length); b++) sum += f[b];
        mic = sum / (26 * 255);
      }

      const bspc = W / N, bw = Math.max(2.0, bspc * 0.58);
      const sx = (W - N * bspc) / 2;

      for (let i = 0; i < N; i++) {
        const norm = i / (N - 1);
        const bx = sx + i * bspc + bspc / 2;
        const t = tick.current;
        let amp = env.current[i];

        if (s === 'LISTENING') {
          const ripple = Math.sin(norm * 12 - t * 3.6) * 0.28 + Math.cos(norm * 6 + t * 2.1) * 0.08;
          amp = Math.max(0.08, Math.min(0.98, amp * (0.85 + mic * 2.4) + ripple * mic));
        } else if (s === 'THINKING') {
          amp = Math.max(0.12, Math.min(0.92, 0.42 + Math.sin(norm * 9 + t * 2.6) * 0.32 + Math.cos(norm * 15 - t * 3.2) * 0.18));
        } else if (s === 'SPEAKING') {
          amp = Math.max(0.12, Math.min(0.98, amp * 1.3 + Math.sin(t * 6 + i * 0.35) * 0.24 + Math.sin(t * 11 + i * 0.55) * 0.13));
        } else {
          amp = amp * 0.45;
        }

        const bh = Math.max(2, amp * maxH);

        // Rose → Violet → Cyan luxury gradient (Zero green)
        let r = 219, g = 39, b = 119;
        if (norm < 0.33) {
          const tt = norm / 0.33;
          r = Math.round(219 + (139 - 219) * tt);
          g = Math.round(39 + (92 - 39) * tt);
          b = Math.round(119 + (246 - 119) * tt);
        } else if (norm < 0.66) {
          const tt = (norm - 0.33) / 0.33;
          r = Math.round(139 + (2 - 139) * tt);
          g = Math.round(92 + (132 - 92) * tt);
          b = Math.round(246 + (199 - 246) * tt);
        } else {
          r = 2; g = 132; b = 199;
        }

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
  }, []);

  useEffect(() => {
    const resize = () => {
      const c = ref.current;
      if (c) {
        c.width = c.parentElement?.clientWidth ?? 220;
        c.height = c.parentElement?.clientHeight ?? 52;
      }
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  return <canvas ref={ref} style={{ width: '100%', height: '100%', display: 'block' }} />;
};

// ─── Main Component ──────────────────────────────────────────────────────────────
export const VoiceSurface: React.FC = () => {
  const [state, setState] = useState<AState>('IDLE');
  const [status, setStatus] = useState('Always listening...');
  const [query, setQuery] = useState('');
  const [reply, setReply] = useState('');
  const [shrunken, setShrunken] = useState(false);

  const stateRef = useRef<AState>('IDLE');
  const analyserRef  = useRef<AnalyserNode | null>(null);
  const analyserSnap = analyserRef.current;

  // Audio Context & Recording
  const acRef     = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef    = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const srRef     = useRef<any>(null);
  const speechBuf = useRef('');

  // Stable callback refs
  const execRef  = useRef<((cmd: string) => void) | undefined>(undefined);
  const audioRef = useRef<((blob: Blob) => void) | undefined>(undefined);

  const setS = useCallback((s: AState, txt: string) => {
    setState(s);
    setStatus(txt);
    stateRef.current = s;
  }, []);

  // ─── Speak (Browser fallback if not in Qt) ───────────────────────────────────
  const speak = useCallback((text: string) => {
    if (!text.trim()) return;
    if (isQt) {
      // In Qt desktop widget, backend Python TTS handles high-fidelity voice
      setS('SPEAKING', 'Speaking...');
      const wordCount = text.split(/\s+/).length;
      const durationMs = Math.max(1800, wordCount * 380);
      setTimeout(() => {
        setS('IDLE', 'Always listening...');
        setQuery('');
      }, durationMs);
      return;
    }

    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      const voices = window.speechSynthesis.getVoices();
      const preferred = voices.find(v =>
        v.name.includes('Ryan') || v.name.includes('Guy') || v.name.includes('David') ||
        (v.lang === 'en-GB' && !v.name.includes('Female'))
      ) || voices.find(v => v.lang.startsWith('en')) || null;
      if (preferred) u.voice = preferred;
      u.rate  = 0.95; // warm, natural pace
      u.pitch = 0.92; // deeper chest tone
      u.volume = 1.0;
      u.onstart = () => setS('SPEAKING', 'Speaking...');
      u.onend = () => { setS('IDLE', 'Always listening...'); setQuery(''); };
      u.onerror = () => setS('IDLE', 'Always listening...');
      window.speechSynthesis.speak(u);
    } else {
      setTimeout(() => setS('IDLE', 'Always listening...'), 2000);
    }
  }, [setS]);

  // ─── Execute command ─────────────────────────────────────────────────────────
  const executeCmd = useCallback(async (cmd: string) => {
    const clean = cmd.trim();
    if (!clean) { setS('IDLE', 'Always listening...'); return; }
    setQuery(clean);
    setS('THINKING', 'Thinking...');
    try {
      const res = await fetch(`${API()}/api/command`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(isQt ? { 'X-Client': 'desktop-widget' } : {}),
        },
        body: JSON.stringify({ command: clean, client: isQt ? 'desktop-widget' : 'web', speak: true }),
      });
      const data = await res.json();
      const r = (data.response || 'Done.').trim();
      setReply(r);
      speak(r);
    } catch {
      const fb = 'Connection error.';
      setReply(fb);
      speak(fb);
    }
  }, [speak, setS]);
  execRef.current = executeCmd;

  // ─── Send audio blob ─────────────────────────────────────────────────────────
  const sendAudio = useCallback(async (blob: Blob) => {
    setS('THINKING', 'Thinking...');
    try {
      const res = await fetch(`${API()}/api/voice`, {
        method: 'POST',
        headers: {
          'Content-Type': blob.type || 'audio/webm',
          ...(isQt ? { 'X-Client': 'desktop-widget' } : {}),
        },
        body: blob,
      });
      const data = await res.json();
      if (data.transcript) setQuery(data.transcript);
      const r = (data.response || 'Done.').trim();
      setReply(r);
      speak(r);
    } catch {
      setS('IDLE', 'Always listening...');
    }
  }, [speak, setS]);
  audioRef.current = sendAudio;

  // ─── Audio Setup + Web Speech Recognition (for browser mode) ────────────────
  useEffect(() => {
    let mounted = true;

    const setup = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 16000 },
        });
        if (!mounted) return;
        streamRef.current = stream;

        const ac = new (window.AudioContext || (window as any).webkitAudioContext)();
        acRef.current = ac;
        const src = ac.createMediaStreamSource(stream);
        const an  = ac.createAnalyser();
        an.fftSize = 128; an.smoothingTimeConstant = 0.6;
        src.connect(an);
        analyserRef.current = an;

        // MediaRecorder for manual push-to-talk audio submission
        const mr = new MediaRecorder(stream);
        mr.ondataavailable = (e) => { if (e.data?.size > 0) chunksRef.current.push(e.data); };
        mr.onstop = () => {
          const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
          chunksRef.current = [];
          if (blob.size > 2000) audioRef.current?.(blob);
          else setS('IDLE', 'Always listening...');
        };
        recRef.current = mr;

        // In browser mode: activate continuous Web Speech Recognition
        const SR = !isQt && ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
        if (SR) {
          const rec = new SR();
          rec.continuous      = true;
          rec.interimResults  = true;
          rec.lang            = 'en-US';
          rec.maxAlternatives = 1;

          let wakeActivated = false;
          let commandBuf    = '';
          let silenceTimer: ReturnType<typeof setTimeout> | null = null;

          rec.onresult = (ev: any) => {
            if (!mounted) return;
            const res = ev.results[ev.results.length - 1];
            const text = (res[0]?.transcript || '').trim();
            if (!text) return;

            if (res.isFinal) {
              if (silenceTimer) clearTimeout(silenceTimer);
              const { found, command } = stripWake(text);
              if (found || wakeActivated) {
                const finalCmd = command || commandBuf;
                wakeActivated = false;
                commandBuf = '';
                if (finalCmd.trim()) {
                  execRef.current?.(finalCmd.trim());
                } else {
                  // User just said "Hey AUREX"
                  setReply('Yes Hammad.');
                  speak('Yes Hammad.');
                }
              }
            } else {
              setQuery(text);
              const { found, command } = stripWake(text);
              if (found) {
                wakeActivated = true;
                setS('LISTENING', 'Listening...');
                commandBuf = command;
                if (silenceTimer) clearTimeout(silenceTimer);
                silenceTimer = setTimeout(() => {
                  if (wakeActivated && mounted) {
                    const toSend = commandBuf.trim();
                    wakeActivated = false;
                    commandBuf = '';
                    if (toSend) execRef.current?.(toSend);
                    else {
                      setReply('Yes Hammad.');
                      speak('Yes Hammad.');
                    }
                  }
                }, 1500);
              }
            }
          };

          rec.onerror = () => {
            if (mounted && stateRef.current !== 'THINKING' && stateRef.current !== 'SPEAKING') {
              try { rec.start(); } catch (_) {}
            }
          };

          rec.onend = () => {
            if (mounted && stateRef.current !== 'THINKING' && stateRef.current !== 'SPEAKING') {
              setTimeout(() => { if (mounted) try { rec.start(); } catch (_) {} }, 250);
            }
          };

          try { rec.start(); } catch (_) {}
          srRef.current = rec;
        }
      } catch (_) {
        // Audio capture not available or user denied permission
      }
    };

    setup();

    return () => {
      mounted = false;
      if (srRef.current) try { srRef.current.stop(); } catch (_) {}
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
    };
  }, [isQt, setS, speak]);

  // Restart browser SR after THINKING → IDLE transition
  useEffect(() => {
    if (state === 'IDLE' && srRef.current) {
      try { srRef.current.start(); } catch (_) {}
    }
  }, [state]);

  // ─── Manual Push-to-talk (Spacebar / Click) ──────────────────────────────────
  const manualStart = useCallback(async () => {
    if (stateRef.current === 'LISTENING' || stateRef.current === 'THINKING') return;
    setS('LISTENING', 'Listening...');
    setQuery('');
    setReply('');
    chunksRef.current = [];
    speechBuf.current = '';
    if (recRef.current?.state === 'inactive') {
      try { recRef.current.start(100); } catch (_) {}
    }
  }, [setS]);

  const manualStop = useCallback(() => {
    if (stateRef.current !== 'LISTENING') return;
    if (recRef.current?.state === 'recording') {
      try { recRef.current.stop(); } catch (_) {}
    }
    setTimeout(() => {
      const txt = speechBuf.current.trim();
      if (txt) {
        speechBuf.current = '';
        execRef.current?.(txt);
      } else {
        setS('IDLE', 'Always listening...');
      }
    }, 150);
  }, [setS]);

  // ─── Global Bridge & Keybindings ─────────────────────────────────────────────
  useEffect(() => {
    const kd = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat && (e.target as HTMLElement)?.tagName !== 'INPUT') {
        e.preventDefault();
        manualStart();
      }
    };
    const ku = (e: KeyboardEvent) => {
      if (e.code === 'Space' && (e.target as HTMLElement)?.tagName !== 'INPUT') {
        e.preventDefault();
        manualStop();
      }
    };
    window.addEventListener('keydown', kd);
    window.addEventListener('keyup', ku);

    // Bridge hooks callable from Python desktop_widget
    (window as any).__aurexStartListen  = manualStart;
    (window as any).__aurexStopListen   = manualStop;
    (window as any).__aurexShrink       = () => setShrunken(true);
    (window as any).__aurexExpand       = () => setShrunken(false);
    (window as any).__aurexSetState     = (s: AState, q?: string, r?: string) => {
      setS(s, s === 'LISTENING' ? 'Listening...' : s === 'THINKING' ? 'Thinking...' : s === 'SPEAKING' ? 'Speaking...' : 'Always listening...');
      if (q !== undefined) setQuery(q);
      if (r !== undefined) setReply(r);
    };
    (window as any).__aurexOnTranscript = (q: string, r: string) => {
      setQuery(q);
      setReply(r);
      setS('SPEAKING', 'Speaking...');
      const wordCount = (r || '').split(/\s+/).length;
      setTimeout(() => {
        setS('IDLE', 'Always listening...');
        setQuery('');
      }, Math.max(1800, wordCount * 360));
    };

    return () => {
      window.removeEventListener('keydown', kd);
      window.removeEventListener('keyup', ku);
    };
  }, [manualStart, manualStop, setS]);

  // ─── Dot Color (Refined Slate / Electric Violet / Cyan) ──────────────────────
  const dotColor = {
    IDLE:      '#94a3b8',
    LISTENING: '#8b5cf6', // Electric Violet (No green!)
    THINKING:  '#7c3aed', // Royal Violet
    SPEAKING:  '#0284c7', // Electric Cyan
  }[state];

  // ─── Shrunken Round Orb Mode ─────────────────────────────────────────────────
  if (shrunken) {
    return (
      <div
        onClick={() => {
          setShrunken(false);
          fetch(`${API()}/api/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: 'expand', client: 'desktop-widget' }),
          }).catch(() => {});
        }}
        title="Click to expand AUREX"
        style={{
          width: '72px',
          height: '72px',
          borderRadius: '50%',
          background: 'rgba(255, 255, 255, 0.94)',
          border: `2px solid ${dotColor}`,
          boxShadow: `0 10px 30px rgba(124, 58, 237, 0.22), 0 0 0 1px rgba(255, 255, 255, 0.8)`,
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          cursor: 'pointer',
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          pointerEvents: 'auto' as const,
          transition: 'border-color 0.3s ease, box-shadow 0.3s ease',
        }}
      >
        <div style={{ width: '100%', height: '100%' }}>
          <Orb state={state} analyser={analyserSnap} />
        </div>
      </div>
    );
  }

  // ─── Full Glass Card (Completely rounded all 4 corners, no bottom clipping) ──
  return (
    <div
      style={{
        width: '348px',
        background: 'rgba(255, 255, 255, 0.95)',
        border: '1px solid rgba(226, 232, 240, 0.92)',
        borderRadius: '24px',
        padding: '13px 16px 14px',
        boxShadow: '0 20px 48px rgba(15, 23, 42, 0.12), 0 3px 10px rgba(15, 23, 42, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.9)',
        backdropFilter: 'blur(30px)',
        WebkitBackdropFilter: 'blur(30px)',
        display: 'flex',
        flexDirection: 'column' as const,
        gap: '9px',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        userSelect: 'none' as const,
        pointerEvents: 'auto' as const,
        cursor: 'pointer',
        overflow: 'hidden',
        boxSizing: 'border-box' as const,
      }}
      onClick={() => {
        if (stateRef.current === 'IDLE') manualStart();
        else if (stateRef.current === 'LISTENING') manualStop();
      }}
      title="Click or Hold Space to speak · Say 'Hey AUREX' anytime"
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
          {/* Status Dot (Violet / Cyan / Slate — zero green) */}
          <span
            style={{
              width: '7.5px',
              height: '7.5px',
              borderRadius: '50%',
              background: dotColor,
              display: 'inline-block',
              flexShrink: 0,
              boxShadow: state !== 'IDLE' ? `0 0 8px ${dotColor}` : 'none',
              transition: 'background 0.3s ease, box-shadow 0.3s ease',
            }}
          />
          <span style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '1.8px', color: '#0F172A' }}>
            AUREX
          </span>
          <span style={{ fontSize: '11px', color: '#64748b', fontWeight: 500, marginLeft: '2px' }}>
            {status}
          </span>
        </div>

        {/* Shrink button */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            setShrunken(true);
            fetch(`${API()}/api/command`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ command: 'shrink', client: 'desktop-widget' }),
            }).catch(() => {});
          }}
          title="Shrink to round orb"
          style={{
            background: 'transparent',
            border: 'none',
            color: '#94a3b8',
            fontSize: '11px',
            cursor: 'pointer',
            padding: '2px 5px',
            borderRadius: '6px',
            transition: 'color 0.2s',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = '#7c3aed')}
          onMouseLeave={(e) => (e.currentTarget.style.color = '#94a3b8')}
        >
          ●
        </button>
      </div>

      {/* Orb + Wave Side by Side */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          background: 'rgba(241, 245, 249, 0.72)',
          borderRadius: '16px',
          padding: '7px 11px',
        }}
      >
        {/* Orb on Left */}
        <div style={{ width: '66px', height: '66px', flexShrink: 0 }}>
          <Orb state={state} analyser={analyserSnap} />
        </div>
        {/* Wave Bars on Right */}
        <div style={{ flex: 1, height: '52px' }}>
          <WaveBars state={state} analyser={analyserSnap} />
        </div>
      </div>

      {/* Transcript / Reply Display */}
      <div
        style={{
          minHeight: '20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center' as const,
          overflow: 'hidden',
          padding: '0 4px',
        }}
      >
        {query ? (
          <span
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: '#7c3aed',
              fontStyle: 'italic',
              whiteSpace: 'nowrap' as const,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: '100%',
            }}
          >
            "{query}"
          </span>
        ) : reply ? (
          <span
            style={{
              fontSize: '11.5px',
              fontWeight: 500,
              color: '#1e293b',
              whiteSpace: 'nowrap' as const,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: '100%',
            }}
          >
            {reply}
          </span>
        ) : (
          <span style={{ fontSize: '10.5px', color: '#94a3b8', fontWeight: 400 }}>
            Say "Hey AUREX" · Space to activate
          </span>
        )}
      </div>
    </div>
  );
};
