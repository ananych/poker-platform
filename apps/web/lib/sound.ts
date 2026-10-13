"use client";

/**
 * Procedural audio (no audio files, no licensing): Web Audio sound effects plus a
 * generated lounge-jazz loop (Rhodes-like comping, walking bass, brushed hats and a
 * sparse vibraphone line). Browsers only allow audio after a user gesture, so the
 * context is created lazily on the first tap anywhere (see `unlockAudio`).
 */

export type Sfx = "deal" | "flip" | "chip" | "check" | "fold" | "turn" | "msg" | "win" | "allin";

export interface SoundPrefs { music: boolean; sfx: boolean; notify: boolean }
const KEY = "sound-prefs";
const DEFAULTS: SoundPrefs = { music: false, sfx: true, notify: false };

let prefs: SoundPrefs = DEFAULTS;
const listeners = new Set<() => void>();
let loaded = false;

function load() {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) prefs = { ...DEFAULTS, ...JSON.parse(raw) };
  } catch { /* ignore */ }
}

export function getPrefs(): SoundPrefs { load(); return prefs; }
export function subscribePrefs(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
export function setPrefs(patch: Partial<SoundPrefs>) {
  load();
  prefs = { ...prefs, ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* ignore */ }
  listeners.forEach((f) => f());
  if (patch.music !== undefined) {
    if (patch.music) startMusic(); else stopMusic();
  }
}

// ---------------------------------------------------------------------------
// audio graph
// ---------------------------------------------------------------------------
let ctx: AudioContext | null = null;
let master: GainNode, sfxBus: GainNode, musicBus: GainNode, noiseBuf: AudioBuffer;

function ensureCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (ctx) return ctx;
  const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  ctx = new AC();
  master = ctx.createGain(); master.gain.value = 0.9; master.connect(ctx.destination);
  sfxBus = ctx.createGain(); sfxBus.gain.value = 0.55; sfxBus.connect(master);
  musicBus = ctx.createGain(); musicBus.gain.value = 0; musicBus.connect(master);
  noiseBuf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
  const d = noiseBuf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  return ctx;
}

/** Call from any user gesture; safe to call repeatedly. */
export function unlockAudio() {
  load();
  const c = ensureCtx();
  if (!c) return;
  if (c.state !== "running") {
    void c.resume().then(() => { if (prefs.music) startMusic(); }).catch(() => {});
  } else if (prefs.music) startMusic();
}

function tone(bus: AudioNode, freq: number, t: number, dur: number, opts: {
  type?: OscillatorType; gain?: number; attack?: number; detune?: number; endFreq?: number;
} = {}) {
  const c = ctx!;
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = opts.type ?? "sine";
  o.frequency.setValueAtTime(freq, t);
  if (opts.endFreq) o.frequency.exponentialRampToValueAtTime(opts.endFreq, t + dur);
  if (opts.detune) o.detune.value = opts.detune;
  const peak = opts.gain ?? 0.3;
  const a = opts.attack ?? 0.005;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(peak, t + a);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(bus);
  o.start(t);
  o.stop(t + dur + 0.05);
}

function noise(bus: AudioNode, t: number, dur: number, opts: {
  type?: BiquadFilterType; freq?: number; endFreq?: number; q?: number; gain?: number;
} = {}) {
  const c = ctx!;
  const s = c.createBufferSource();
  s.buffer = noiseBuf;
  const f = c.createBiquadFilter();
  f.type = opts.type ?? "bandpass";
  f.frequency.setValueAtTime(opts.freq ?? 3000, t);
  if (opts.endFreq) f.frequency.exponentialRampToValueAtTime(opts.endFreq, t + dur);
  f.Q.value = opts.q ?? 1;
  const g = c.createGain();
  g.gain.setValueAtTime(opts.gain ?? 0.3, t);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  s.connect(f).connect(g).connect(bus);
  s.start(t, Math.random() * 0.5);
  s.stop(t + dur + 0.02);
}

// ---------------------------------------------------------------------------
// sound effects
// ---------------------------------------------------------------------------
export function play(name: Sfx) {
  load();
  if (!prefs.sfx) return;
  const c = ensureCtx();
  if (!c || c.state !== "running") return;
  const t = c.currentTime + 0.01;
  const b = sfxBus;
  switch (name) {
    case "deal":
      noise(b, t, 0.07, { freq: 2500, q: 0.8, gain: 0.35 });
      noise(b, t + 0.12, 0.07, { freq: 2800, q: 0.8, gain: 0.3 });
      break;
    case "flip":
      noise(b, t, 0.09, { freq: 1800, endFreq: 4000, q: 0.7, gain: 0.3 });
      break;
    case "chip":
    case "allin": {
      const n = name === "allin" ? 9 : 4;
      for (let i = 0; i < n; i++) {
        const tt = t + i * 0.045 + Math.random() * 0.02;
        tone(b, 2600 + Math.random() * 1400, tt, 0.06, { type: "triangle", gain: 0.12 });
        noise(b, tt, 0.03, { freq: 6000, q: 2, gain: 0.08 });
      }
      break;
    }
    case "check":
      tone(b, 140, t, 0.09, { gain: 0.45, endFreq: 90 });
      noise(b, t, 0.04, { type: "lowpass", freq: 900, gain: 0.25 });
      tone(b, 140, t + 0.13, 0.09, { gain: 0.4, endFreq: 90 });
      noise(b, t + 0.13, 0.04, { type: "lowpass", freq: 900, gain: 0.2 });
      break;
    case "fold":
      noise(b, t, 0.22, { freq: 3000, endFreq: 500, q: 0.6, gain: 0.18 });
      break;
    case "turn":
      tone(b, 880, t, 0.5, { gain: 0.22 });
      tone(b, 1318.5, t + 0.12, 0.6, { gain: 0.2 });
      break;
    case "msg":
      tone(b, 620, t, 0.09, { gain: 0.18, endFreq: 940 });
      break;
    case "win": {
      [523.25, 659.25, 783.99, 1046.5].forEach((f, i) =>
        tone(b, f, t + i * 0.09, 0.7, { gain: 0.18, type: "sine" }));
      tone(b, 1567.98, t + 0.36, 0.9, { gain: 0.08, type: "triangle" });
      for (let i = 0; i < 6; i++) {
        tone(b, 2800 + Math.random() * 1200, t + 0.45 + i * 0.05, 0.06, { type: "triangle", gain: 0.08 });
      }
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// generated background music
// ---------------------------------------------------------------------------
const BPM = 76;
const BEAT = 60 / BPM;
const midi = (n: number) => 440 * 2 ** ((n - 69) / 12);

// 8-bar loop in F: | Gm9 | C13 | Fmaj9 | Dm9 | Bbmaj7 | A7b9 | Dm9 | G13 C7 |
const BARS: { chord: number[]; bass: number[] }[] = [
  { chord: [58, 62, 65, 69], bass: [43, 46, 50, 49] },   // Gm9 (G Bb D Db)
  { chord: [58, 62, 64, 69], bass: [36, 40, 43, 41] },   // C13
  { chord: [57, 60, 64, 67], bass: [41, 45, 48, 50] },   // Fmaj9
  { chord: [57, 60, 64, 65], bass: [38, 41, 45, 44] },   // Dm9
  { chord: [57, 62, 65, 69], bass: [46, 50, 53, 45] },   // Bbmaj7
  { chord: [55, 58, 61, 67], bass: [45, 49, 52, 50] },   // A7b9
  { chord: [57, 60, 64, 65], bass: [38, 41, 45, 43] },   // Dm9
  { chord: [53, 57, 59, 64], bass: [43, 47, 36, 40] },   // G13 -> C7
];
const SCALE = [65, 67, 69, 72, 74, 77, 79, 81]; // F major pentatonic-ish, vibes range

let musicTimer: ReturnType<typeof setInterval> | null = null;
let nextBeatTime = 0;
let beatIndex = 0;

function rhodes(freq: number, t: number, dur: number, gain: number) {
  const c = ctx!;
  const f = c.createBiquadFilter();
  f.type = "lowpass"; f.frequency.value = 1800;
  f.connect(musicBus);
  tone(f, freq, t, dur, { gain, attack: 0.012 });
  tone(f, freq * 2, t, dur * 0.5, { gain: gain * 0.25, attack: 0.008, type: "triangle" });
  tone(f, freq, t, dur, { gain: gain * 0.4, detune: 7, type: "triangle" });
}

function scheduleBeat(t: number, i: number) {
  const bar = BARS[Math.floor(i / 4) % BARS.length];
  const beat = i % 4;
  const swing = BEAT * 0.62; // swung eighth offset
  // walking bass
  tone(musicBus, midi(bar.bass[beat]), t, BEAT * 0.9, { gain: 0.32, attack: 0.01, type: "sine" });
  tone(musicBus, midi(bar.bass[beat]) * 2, t, BEAT * 0.25, { gain: 0.05, type: "triangle" });
  // comping: beat 1 and the "and" of 2 (Charleston-ish)
  if (beat === 0 || (beat === 1 && Math.random() < 0.85) || (beat === 3 && Math.random() < 0.3)) {
    const at = beat === 0 ? t : t + swing;
    bar.chord.forEach((n, k) => rhodes(midi(n), at + k * 0.008, beat === 0 ? BEAT * 1.6 : BEAT * 0.9, 0.06));
  }
  // brushes: swish on 2 and 4, light ticks on swung eighths
  if (beat % 2 === 1) noise(musicBus, t, 0.18, { freq: 5000, q: 0.5, gain: 0.05 });
  noise(musicBus, t + swing, 0.04, { freq: 8000, q: 1.5, gain: 0.025 });
  // sparse vibraphone melody
  if (Math.random() < 0.32) {
    const n = SCALE[Math.floor(Math.random() * SCALE.length)];
    const at = t + (Math.random() < 0.5 ? 0 : swing);
    tone(musicBus, midi(n), at, BEAT * 1.4, { gain: 0.07, attack: 0.004 });
    tone(musicBus, midi(n) * 4, at, BEAT * 0.3, { gain: 0.01 });
  }
}

function startMusic() {
  const c = ensureCtx();
  if (!c || musicTimer) return;
  if (c.state !== "running") {
    void c.resume().then(() => { if (prefs.music && c.state === "running") startMusic(); }).catch(() => {});
    return;
  }
  musicBus.gain.cancelScheduledValues(c.currentTime);
  musicBus.gain.setValueAtTime(musicBus.gain.value, c.currentTime);
  musicBus.gain.linearRampToValueAtTime(0.5, c.currentTime + 1.5);
  nextBeatTime = c.currentTime + 0.1;
  musicTimer = setInterval(() => {
    while (nextBeatTime < c.currentTime + 0.3) {
      scheduleBeat(nextBeatTime, beatIndex++);
      nextBeatTime += BEAT;
    }
  }, 60);
}

function stopMusic() {
  if (!ctx) return;
  if (musicTimer) { clearInterval(musicTimer); musicTimer = null; }
  musicBus.gain.cancelScheduledValues(ctx.currentTime);
  musicBus.gain.setValueAtTime(musicBus.gain.value, ctx.currentTime);
  musicBus.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.6);
}

// ---------------------------------------------------------------------------
// attention helpers
// ---------------------------------------------------------------------------
export function vibrate(pattern: number | number[]) {
  try { navigator.vibrate?.(pattern); } catch { /* unsupported */ }
}

/** Desktop/Android background notification while the tab is hidden (no push server). */
export function notify(title: string, body?: string) {
  load();
  if (!prefs.notify || typeof Notification === "undefined") return;
  if (document.visibilityState === "visible" || Notification.permission !== "granted") return;
  try {
    const n = new Notification(title, { body, tag: "poker", silent: false });
    n.onclick = () => { window.focus(); n.close(); };
  } catch { /* some mobile browsers only allow SW notifications */ }
}

export async function requestNotify(): Promise<boolean> {
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  return (await Notification.requestPermission()) === "granted";
}
