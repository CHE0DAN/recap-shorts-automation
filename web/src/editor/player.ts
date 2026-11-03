// 미리보기 재생기. 캔버스에 그리는 쪽(engine.ts)과 시각(clock)을 분리하고,
// 재생 중에는 소리 요소의 currentTime 을 시계로 쓴다(영상 요소 두 개로 컷을 이어 붙이던 부분은 우리 형식이 이미지 슬라이드라 필요 없음).
// 소리를 못 불러오면 벽시계로 대신 흘려 보낸다.
import { useCallback, useEffect, useRef, useState } from "react";
import { drawFrame, ensureFonts, H, W, type IntroDraw } from "./engine";
import type { IntroPreview, Timeline } from "../types";

export const PREVIEW_W = 720;
export const PREVIEW_H = 1280;

export function usePlayer(tl: Timeline | null, voiceUrl: string | null, resolve: (file: string) => string, bust: number,
  introP: IntroPreview | null = null) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const introRef = useRef<IntroDraw | null>(null);
  const tRef = useRef(0);
  const tlRef = useRef(tl);
  tlRef.current = tl;
  const resolveRef = useRef(resolve);
  resolveRef.current = resolve;
  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);
  const subs = useRef(new Set<(t: number) => void>());
  const images = useRef(new Map<string, HTMLImageElement>());
  const raf = useRef(0);
  const drawReq = useRef(0);
  const audio = useRef<HTMLAudioElement | null>(null);
  const audioOk = useRef(true);
  const wall = useRef({ t0: 0, w0: 0 });

  const draw = useCallback(() => {
    const c = canvasRef.current, doc = tlRef.current;
    const g = c?.getContext("2d");
    if (!c || !g || !doc) return;
    g.setTransform(c.width / W, 0, 0, c.height / H, 0, 0);
    try { drawFrame(g, doc, tRef.current, getImage, introRef.current); } catch (e) { console.error("미리보기 그리기 실패", e); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const requestDraw = useCallback(() => {
    if (drawReq.current) return;
    drawReq.current = requestAnimationFrame(() => { drawReq.current = 0; draw(); });
  }, [draw]);
  function getImage(file: string): HTMLImageElement | null {
    let img = images.current.get(file);
    if (!img) {
      img = new Image();
      img.decoding = "async";
      img.onload = () => requestDraw();
      img.src = resolveRef.current(file);
      images.current.set(file, img);
    }
    return img.complete && img.naturalWidth ? img : null;
  }

  // 글꼴·이미지 준비, 그림이 바뀌면 다시 그리기
  useEffect(() => { ensureFonts().then(requestDraw); }, [requestDraw]);
  useEffect(() => {
    if (!introP) { introRef.current = null; requestDraw(); return; }
    const img = new Image();
    img.onload = () => requestDraw();
    img.src = introP.group;
    introRef.current = { p: introP, img };
    requestDraw();
  }, [introP, requestDraw]);
  useEffect(() => { images.current.clear(); requestDraw(); }, [bust, requestDraw]);
  useEffect(() => {
    if (tl) for (const s of tl.shots) getImage(s.file);
    requestDraw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tl, requestDraw]);

  // 소리
  useEffect(() => {
    if (!voiceUrl) return;
    const a = new Audio(voiceUrl);
    a.preload = "auto";
    audioOk.current = true;
    a.onerror = () => { audioOk.current = false; };
    audio.current = a;
    return () => { a.pause(); a.src = ""; audio.current = null; };
  }, [voiceUrl, bust]);

  const emit = useCallback(() => subs.current.forEach((f) => f(tRef.current)), []);
  const duration = () => tlRef.current?.duration ?? 0;

  const pause = useCallback(() => {
    playingRef.current = false; setPlaying(false);
    cancelAnimationFrame(raf.current);
    audio.current?.pause();
  }, []);
  const loop = useCallback(() => {
    if (!playingRef.current) return;
    const a = audio.current;
    const t = a && audioOk.current && !a.paused ? a.currentTime : wall.current.t0 + (performance.now() - wall.current.w0) / 1000;
    tRef.current = Math.min(t, duration());
    draw(); emit();
    if (t >= duration()) { pause(); return; }
    raf.current = requestAnimationFrame(loop);
  }, [draw, emit, pause]);
  const seek = useCallback((t: number) => {
    const d = duration();
    tRef.current = Math.max(0, Math.min(d, t));
    wall.current = { t0: tRef.current, w0: performance.now() };
    if (audio.current && audioOk.current) { try { audio.current.currentTime = tRef.current; } catch { /* 아직 못 감음 */ } }
    draw(); emit();
  }, [draw, emit]);
  const play = useCallback(() => {
    if (tRef.current >= duration() - 0.05) tRef.current = 0;
    wall.current = { t0: tRef.current, w0: performance.now() };
    const a = audio.current;
    if (a && audioOk.current) {
      try { a.currentTime = tRef.current; } catch { /* */ }
      a.play().catch(() => { audioOk.current = false; wall.current = { t0: tRef.current, w0: performance.now() }; });
    }
    playingRef.current = true; setPlaying(true);
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(loop);
  }, [loop]);
  useEffect(() => () => { cancelAnimationFrame(raf.current); cancelAnimationFrame(drawReq.current); }, []);

  const subscribe = useCallback((f: (t: number) => void) => { subs.current.add(f); f(tRef.current); return () => { subs.current.delete(f); }; }, []);
  return { canvasRef, tRef, playing, play, pause, seek, subscribe, requestDraw };
}
