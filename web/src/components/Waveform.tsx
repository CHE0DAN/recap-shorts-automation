// 오디오를 한 번 해독해 막대 높이로 줄인다. wav 주소 하나를 받고, 색은 CSS 변수에서 읽어 다크 모드를 따른다.
import { useEffect, useRef, useState } from "react";

let ctx: AudioContext | null = null;
export function audioCtx(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  return ctx;
}
const cache = new Map<string, Promise<AudioBuffer>>();
export function loadBuffer(url: string): Promise<AudioBuffer> {
  if (!cache.has(url)) {
    const p = fetch(url).then((r) => { if (!r.ok) throw new Error(`${r.status}`); return r.arrayBuffer(); }).then((b) => audioCtx().decodeAudioData(b));
    p.catch(() => cache.delete(url));
    cache.set(url, p);
  }
  return cache.get(url)!;
}
export function peaksOf(buf: AudioBuffer, bars: number): number[] {
  const ch = buf.getChannelData(0);
  const out = new Array<number>(bars).fill(0);
  const step = Math.max(1, Math.floor(ch.length / bars / 200));
  for (let i = 0; i < bars; i++) {
    const s0 = Math.floor((i / bars) * ch.length), s1 = Math.floor(((i + 1) / bars) * ch.length);
    let m = 0;
    for (let k = s0; k < s1; k += step) m = Math.max(m, Math.abs(ch[k]));
    out[i] = m;
  }
  const mx = Math.max(0.05, ...out);
  return out.map((v) => v / mx);
}
export const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888";

export default function Waveform({ url, bars = 64, height = 40, progress, onSeek }: { url: string; bars?: number; height?: number; progress?: number; onSeek?: (frac: number) => void }) {
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [scheme, setScheme] = useState(0);
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let dead = false;
    setPeaks(null);
    loadBuffer(url).then((b) => { if (!dead) setPeaks(peaksOf(b, bars)); }).catch(() => { if (!dead) setPeaks(null); });
    return () => { dead = true; };
  }, [url, bars]);
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const f = () => setScheme((n) => n + 1);
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = height;
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    const g = c.getContext("2d")!;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, w, h);
    const p = peaks ?? new Array<number>(bars).fill(0.1);
    const bw = w / bars;
    const base = cssVar("--c-line-strong"), on = cssVar("--c-accent");
    p.forEach((v, i) => {
      const bh = Math.max(2, v * (h - 2));
      g.fillStyle = progress != null && (i + 0.5) / bars <= progress ? on : base;
      g.beginPath();
      g.roundRect(i * bw + bw * 0.2, (h - bh) / 2, Math.max(1.5, bw * 0.6), bh, 1);
      g.fill();
    });
  }, [peaks, bars, height, progress, scheme]);
  return <canvas ref={ref} style={{ width: "100%", height, cursor: onSeek ? "pointer" : undefined }}
    onClick={onSeek ? (e) => { const r = e.currentTarget.getBoundingClientRect(); onSeek((e.clientX - r.left) / r.width); } : undefined} />;
}
