import React, { useState, useEffect, useRef, useCallback } from 'react';

// ─── Types ──────────────────────────────────────────────────────────────────────
type AState = 'IDLE' | 'LISTENING' | 'THINKING' | 'SPEAKING';

const isQt = typeof navigator !== 'undefined' && /QtWebEngine/i.test(navigator.userAgent);
const API  = () =>
  typeof window !== 'undefined' && window.location.origin.startsWith('http')
    ? window.location.origin
    : 'http://127.0.0.1:8765';

// ─── Luxury Fluid Harmonic Waveform ──────────────────────────────────────────────
interface WaveProps {
  state: AState;
  analyser: AnalyserNode | null;
}

const PremiumFluidWave: React.FC<WaveProps> = ({ state, analyser }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const tickRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  const analyserRef = useRef(analyser);
  analyserRef.current = analyser;

  const N = 44; // Number of harmonic bars
  const currentAmps = useRef<number[]>(new Array(N).fill(0.08));
  const targetAmps  = useRef<number[]>(new Array(N).fill(0.08));

  // Smooth Gaussian window envelope (peak at center, tapered at edges)
  const windowEnv = useRef<number[]>([]);
  if (windowEnv.current.length === 0) {
    for (let i = 0; i < N; i++) {
      const norm = i / (N - 1);
      const dist = norm - 0.5;
      const g = Math.exp(-(dist * dist) / (2 * 0.22 * 0.22));
      windowEnv.current.push(g);
    }
  }

  useEffect(() => {
    let running = true;
    // Luxurious, slow, unhurried harmonic speeds
    const speeds: Record<AState, number> = {
      IDLE:      0.016, // Gentle, breathing slow drift
      LISTENING: 0.042, // Responsive, organic rhythm
      THINKING:  0.038, // Thoughtful resonance
      SPEAKING:  0.065, // Vibrant, fluid speech undulation
    };

    const draw = () => {
      if (!running) return;
      const canvas = canvasRef.current;
      if (!canvas) { rafRef.current = requestAnimationFrame(draw); return; }
      const ctx = canvas.getContext('2d');
      if (!ctx) { rafRef.current = requestAnimationFrame(draw); return; }

      const s = stateRef.current;
      const W = canvas.width;
      const H = canvas.height;
      const cy = H / 2;
      const maxH = (H - 6) / 2;

      ctx.clearRect(0, 0, W, H);
      tickRef.current += speeds[s] ?? 0.02;
      const t = tickRef.current;

      // Microphone level
      let mic = 0;
      if (analyserRef.current && s === 'LISTENING') {
        const f = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(f);
        let sum = 0;
        for (let b = 2; b < Math.min(32, f.length); b++) sum += f[b];
        mic = sum / (30 * 255);
      }

      // Calculate target amplitudes based on state
      for (let i = 0; i < N; i++) {
        const norm = i / (N - 1);
        const w = windowEnv.current[i];
        let target = 0.08;

        if (s === 'IDLE') {
          // Slow, peaceful ambient breathing waves
          const wave1 = Math.sin(norm * 4.2 + t * 1.8) * 0.16;
          const wave2 = Math.cos(norm * 6.5 - t * 1.2) * 0.08;
          target = Math.max(0.06, (0.24 + wave1 + wave2) * w);
        } else if (s === 'LISTENING') {
          // Responsive acoustic ripple
          const ripple = Math.sin(norm * 8.0 - t * 2.8) * 0.22 + Math.cos(norm * 14.0 + t * 3.5) * 0.12;
          target = Math.max(0.08, Math.min(0.96, (0.35 + mic * 2.2 + ripple * (0.3 + mic)) * w));
        } else if (s === 'THINKING') {
          // Coordinated harmonic oscillations
          const sweep = Math.sin(norm * 10.0 + t * 2.5) * 0.35 + Math.sin(t * 3.2 + i * 0.3) * 0.18;
          target = Math.max(0.10, Math.min(0.92, (0.45 + sweep) * w));
        } else if (s === 'SPEAKING') {
          // Melodic, rich speech harmonics
          const harm1 = Math.sin(norm * 7.5 - t * 3.2) * 0.30;
          const harm2 = Math.sin(norm * 13.0 + t * 4.5) * 0.20;
          const pulse = Math.sin(t * 5.0) * 0.12;
          target = Math.max(0.12, Math.min(0.98, (0.55 + harm1 + harm2 + pulse) * w));
        }

        targetAmps.current[i] = target;
        // Luxurious lerp: smooth 0.08 interpolation avoids all jitter
        currentAmps.current[i] += (targetAmps.current[i] - currentAmps.current[i]) * 0.09;
      }

      // Draw smooth, rounded harmonic bars with luxury gradient
      const barSpacing = W / N;
      const barWidth = Math.max(2.2, barSpacing * 0.54);
      const startX = (W - N * barSpacing) / 2;

      for (let i = 0; i < N; i++) {
        const norm = i / (N - 1);
        const bx = startX + i * barSpacing + barSpacing / 2;
        const bh = Math.max(2.5, currentAmps.current[i] * maxH);

        // Luxury color transitions: Indigo (6366f1) → Violet (8b5cf6) → Cyan (06b6d4)
        let r = 99, g = 102, b = 241;
        if (s === 'IDLE') {
          // Refined cool slate to soft indigo
          r = Math.round(148 + (99 - 148) * norm);
          g = Math.round(163 + (102 - 163) * norm);
          b = Math.round(184 + (241 - 184) * norm);
        } else if (s === 'SPEAKING') {
          // Brilliant electric cyan to sky blue
          r = Math.round(6 + (56 - 6) * norm);
          g = Math.round(182 + (189 - 182) * norm);
          b = Math.round(212 + (248 - 212) * norm);
        } else {
          // Electric violet to royal purple
          if (norm < 0.5) {
            const tNorm = norm / 0.5;
            r = Math.round(99 + (139 - 99) * tNorm);
            g = Math.round(102 + (92 - 102) * tNorm);
            b = Math.round(241 + (246 - 241) * tNorm);
          } else {
            const tNorm = (norm - 0.5) / 0.5;
            r = Math.round(139 + (6 - 139) * tNorm);
            g = Math.round(92 + (182 - 92) * tNorm);
            b = Math.round(246 + (212 - 246) * tNorm);
          }
        }

        ctx.beginPath();
        ctx.strokeStyle = `rgb(${r},${g},${b})`;
        ctx.lineWidth = barWidth;
        ctx.lineCap = 'round';
        ctx.moveTo(bx, cy - bh);
        ctx.lineTo(bx, cy + bh);
        ctx.stroke();
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      running = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  useEffect(() => {
    const handleResize = () => {
      const c = canvasRef.current;
      if (c) {
        c.width = c.parentElement?.clientWidth ?? 316;
        c.height = c.parentElement?.clientHeight ?? 58;
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />;
};

// ─── Main Component ──────────────────────────────────────────────────────────────
export const VoiceSurface: React.FC = () => {
  const [state, setState] = useState<AState>('IDLE');
  const [status, setStatus] = useState('Always listening...');
  const [query, setQuery] = useState('');
  const [reply, setReply] = useState('');
  const [shrunken, setShrunken] = useState(false);

  const stateRef = useRef<AState>('IDLE');
  const analyserRef = useRef<AnalyserNode | null>(null);
  const analyserSnap = analyserRef.current;

  const setS = useCallback((s: AState, txt: string) => {
    setState(s);
    setStatus(txt);
    stateRef.current = s;
  }, []);

  // ─── Execute Command ─────────────────────────────────────────────────────────
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
      setS('SPEAKING', 'Speaking...');
      const wordCount = r.split(/\s+/).length;
      setTimeout(() => {
        setS('IDLE', 'Always listening...');
        setQuery('');
      }, Math.max(1800, wordCount * 350));
    } catch {
      setReply('Connection error.');
      setS('IDLE', 'Always listening...');
    }
  }, [setS]);

  // ─── Shrink / Expand Actions ────────────────────────────────────────────────
  const triggerShrink = useCallback(async () => {
    setShrunken(true);
    try {
      await fetch(`${API()}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: 'shrink', client: 'desktop-widget' }),
      });
    } catch (_) {}
  }, []);

  const triggerExpand = useCallback(async () => {
    setShrunken(false);
    try {
      await fetch(`${API()}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: 'expand', client: 'desktop-widget' }),
      });
    } catch (_) {}
  }, []);

  // ─── Global Hooks & Keybindings ─────────────────────────────────────────────
  useEffect(() => {
    (window as any).__aurexShrink = () => setShrunken(true);
    (window as any).__aurexExpand = () => setShrunken(false);
    (window as any).__aurexExecute = executeCmd;
    (window as any).__aurexSetState = (s: AState, q?: string, r?: string) => {
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
      }, Math.max(1800, wordCount * 350));
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat && (e.target as HTMLElement)?.tagName !== 'INPUT') {
        e.preventDefault();
        setS('LISTENING', 'Listening...');
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space' && (e.target as HTMLElement)?.tagName !== 'INPUT') {
        e.preventDefault();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [setS]);

  // Dot color theme
  const dotColor = {
    IDLE:      '#94a3b8',
    LISTENING: '#8b5cf6',
    THINKING:  '#7c3aed',
    SPEAKING:  '#06b6d4',
  }[state];

  // ─── Compact Pill Shrunken Mode ──────────────────────────────────────────────
  if (shrunken) {
    return (
      <div
        onClick={triggerExpand}
        title="Click to expand AUREX"
        style={{
          width: '164px',
          height: '42px',
          borderRadius: '21px',
          background: 'rgba(255, 255, 255, 0.96)',
          border: `1.5px solid ${dotColor}`,
          boxShadow: '0 10px 28px rgba(15, 23, 42, 0.12), 0 2px 6px rgba(15, 23, 42, 0.06)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          cursor: 'pointer',
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 12px',
          pointerEvents: 'auto' as const,
          userSelect: 'none' as const,
          transition: 'border-color 0.3s ease, box-shadow 0.3s ease',
          fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: dotColor,
              boxShadow: state !== 'IDLE' ? `0 0 6px ${dotColor}` : 'none',
              transition: 'background 0.3s ease',
            }}
          />
          <span style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '1.5px', color: '#0F172A' }}>
            AUREX
          </span>
        </div>
        <div style={{ width: '48px', height: '24px' }}>
          <PremiumFluidWave state={state} analyser={analyserSnap} />
        </div>
      </div>
    );
  }

  // ─── Full Luxury Card (No circle, full wide slow fluid wave, round bottom) ──
  return (
    <div
      style={{
        width: '348px',
        background: 'rgba(255, 255, 255, 0.96)',
        border: '1px solid rgba(226, 232, 240, 0.95)',
        borderRadius: '24px',
        padding: '13px 17px 14px',
        boxShadow: '0 20px 48px rgba(15, 23, 42, 0.10), 0 4px 12px rgba(15, 23, 42, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.9)',
        backdropFilter: 'blur(32px)',
        WebkitBackdropFilter: 'blur(32px)',
        display: 'flex',
        flexDirection: 'column' as const,
        gap: '9px',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        userSelect: 'none' as const,
        pointerEvents: 'auto' as const,
        cursor: 'default',
        overflow: 'hidden',
        boxSizing: 'border-box' as const,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
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
          <span style={{ fontSize: '11.5px', fontWeight: 800, letterSpacing: '1.8px', color: '#0F172A' }}>
            AUREX
          </span>
          <span style={{ fontSize: '11px', color: '#64748b', fontWeight: 500, marginLeft: '2px' }}>
            {status}
          </span>
        </div>

        {/* Shrink button */}
        <button
          onClick={triggerShrink}
          title="Shrink to compact badge"
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

      {/* Hero: Full-Width Slow Fluid Harmonic Wave */}
      <div
        style={{
          width: '100%',
          height: '58px',
          background: 'rgba(241, 245, 249, 0.75)',
          borderRadius: '16px',
          padding: '4px 10px',
          boxSizing: 'border-box' as const,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <PremiumFluidWave state={state} analyser={analyserSnap} />
      </div>

      {/* Transcript & Response Area */}
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
