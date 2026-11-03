// 눈금 + 줄마다 한 종류 + 재생선 방식으로 우리 형식에 맞춰 짠 타임라인:
// 문장 줄 / 그림 줄(썸네일 + 어울림 점수, 끌어서 맞바꾸기 + 같은 문장 안 경계 끌기) / 자막 줄 / 소리 파형 줄.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Waveform, { loadBuffer } from "../components/Waveform";
import { cx } from "../ui";
import type { SceneSentence, Timeline } from "../types";

const LABEL_W = 56;
const MIN_SHOT_S = 0.4;     // 사람이 끌어 옮긴 경계로 만든 샷의 최소 길이(서버 검사와 같음)
const SNAP_S = 0.2;         // 이 안에 어절 경계(gaps)가 있으면 그 자리에 붙임
const HANDLE_W = 10;        // 손잡이 히트 영역(px)

interface Drag { from: number; lo: number; hi: number; gaps: number[]; alt: boolean }

export function Playhead({ subscribe, pps, onTime }: { subscribe: (f: (t: number) => void) => () => void; pps: number; onTime?: (el: HTMLElement | null) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => subscribe((t) => { if (ref.current) ref.current.style.transform = `translateX(${t * pps}px)`; }), [subscribe, pps]);
  useEffect(() => { onTime?.(ref.current); }, [onTime]);
  return (
    <div ref={ref} className="pointer-events-none absolute inset-y-0 left-0 z-20 w-0">
      <div className="absolute inset-y-0 -left-px w-0.5 bg-accent" />
      <div className="absolute -left-[5px] -top-0.5 h-2.5 w-2.5 rounded-full bg-accent" />
    </div>
  );
}

/** 경계 끌기 중에 보여 줄 정보: 그 문장의 어절 경계 눈금과 지금 시각. */
function CutOverlay({ gaps, t, lo, hi, pps, snapT }: { gaps: number[]; t: number; lo: number; hi: number; pps: number; snapT: number | null }) {
  return (
    <>
      <div className="pointer-events-none absolute inset-x-0 top-0 bottom-0 bg-[color-mix(in_srgb,var(--c-accent)_6%,transparent)]"
        style={{ left: lo * pps, width: Math.max(0, (hi - lo) * pps) }} />
      {gaps.filter((g) => g > lo - 0.05 && g < hi + 0.05).map((g) => (
        <div key={g} className="pointer-events-none absolute top-0 bottom-0 w-px bg-[color-mix(in_srgb,var(--c-ink)_22%,transparent)]" style={{ left: g * pps }} />
      ))}
      {snapT != null && (
        <div className="pointer-events-none absolute top-0 bottom-0 w-[3px] rounded bg-accent/40" style={{ left: snapT * pps - 1.5 }} />
      )}
      <div className="pointer-events-none absolute -top-0.5 z-30 -translate-x-1/2 whitespace-nowrap rounded bg-accent px-1.5 text-[11px] font-semibold leading-4 text-white"
        style={{ left: t * pps }}>{t.toFixed(2)}초</div>
    </>
  );
}

export default function TimelineStrip({ tl, sentences, scoreOf, resolve, voiceUrl, subscribe, onSeek, sel, onSel, onSwap, activeSentence, onResize }: {
  tl: Timeline; sentences: SceneSentence[]; scoreOf: (shotIndex: number) => number | null; resolve: (f: string) => string; voiceUrl: string | null;
  subscribe: (f: (t: number) => void) => () => void; onSeek: (t: number) => void; sel: number; onSel: (i: number) => void; onSwap: (a: number, b: number) => void;
  activeSentence: number; onResize?: (i: number, t: number) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(900);
  const [audioDur, setAudioDur] = useState<number | null>(null);
  const [dragFrom, setDragFromS] = useState<number | null>(null);
  const dragRef = useRef<number | null>(null);   // 이벤트 사이에 다시 그려지지 않아도 읽을 수 있게 ref 에도 둔다
  const setDragFrom = (v: number | null) => { dragRef.current = v; setDragFromS(v); };
  const [over, setOver] = useState<number | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragLive = useRef<Drag | null>(null);   // 포인터 이벤트가 붙잡은 값(다시 그려지기 전에 와도 맞게)
  const setDragBoth = (d: Drag | null) => { dragLive.current = d; setDrag(d); };
  const [hover, setHover] = useState<number | null>(null);
  const [cutT, setCutT] = useState<number | null>(null);
  useLayoutEffect(() => {
    const e = box.current;
    if (!e) return;
    const ro = new ResizeObserver(() => setW(e.clientWidth));
    ro.observe(e); setW(e.clientWidth);
    return () => ro.disconnect();
  }, []);
  useEffect(() => { if (voiceUrl) loadBuffer(voiceUrl).then((b) => setAudioDur(b.duration)).catch(() => setAudioDur(null)); }, [voiceUrl]);

  const avail = Math.max(300, w - LABEL_W);
  const pps = Math.max(30, avail / tl.duration);
  const width = tl.duration * pps;
  const ticks = Array.from({ length: Math.floor(tl.duration) + 1 }, (_, i) => i);
  const seekAt = (e: React.MouseEvent) => {
    const r = e.currentTarget.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(tl.duration, (e.clientX - r.left) / pps)));
  };

  // ---- 경계 끌기: 포인터 캡처로 줄어든 폭에서도 계속 받는다. Alt 를 누르면 어절 경계에 안 붙음 ----
  const startDrag = (e: React.PointerEvent, i: number) => {
    if (!onResize || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const a = tl.shots[i], b = tl.shots[i + 1];
    const own = sentenceOwner(sentences, a.start);
    const sent = sentences.find((s) => s.index === own);
    // 서버는 문장 구간(span) 기준으로 0.4초를 검사한다 — 마지막 샷은 목소리 지연(picture_lead_s)만큼 span 보다 길게 나와 있어 b.end 만 보면 400
    const lo = Math.max(a.start, sent?.span?.[0] ?? a.start) + MIN_SHOT_S;
    const hi = Math.min(b.end, sent?.span?.[1] ?? b.end) - MIN_SHOT_S;
    if (hi <= lo) return;   // 둘 다 0.4초보다 짧아 옮길 자리가 없으면 손잡이를 만들지 않았을 것
    const gaps = (sent?.gaps ?? []).filter((g) => g > lo - 0.8 && g < hi + 0.8);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDragBoth({ from: i, lo, hi, gaps, alt: e.altKey });
    setCutT(Math.max(lo, Math.min(hi, tOf(e.clientX))));
  };
  const tOf = (clientX: number) => {
    const e = box.current;
    if (!e) return 0;
    const r = e.getBoundingClientRect();
    // 가로 스크롤이 있을 수 있으니 '그림 줄'의 왼쪽을 기준으로(라벨 너머 = LABEL_W)
    return Math.max(0, (clientX - r.left + e.scrollLeft - LABEL_W) / pps);
  };
  const snap = (t: number, d: Drag): number => {
    if (d.alt) return t;
    // 옮길 수 있는 범위(앞 샷 0.4초·뒤 샷 0.4초) 안의 어절 경계에만 붙는다 — 밖의 경계에 붙이면 서버가 400 을 낸다
    const near = d.gaps.filter((g) => g >= d.lo - 1e-9 && g <= d.hi + 1e-9 && Math.abs(g - t) <= SNAP_S);
    if (!near.length) return t;
    return near.reduce((best, g) => (Math.abs(g - t) < Math.abs(best - t) ? g : best), near[0]);
  };
  const moveDrag = (e: React.PointerEvent, d: Drag) => {
    const t = Math.max(d.lo, Math.min(d.hi, tOf(e.clientX)));
    const alt = e.altKey;
    if (alt !== d.alt) setDragBoth({ ...d, alt });
    setCutT(snap(t, { ...d, alt }));
  };
  const endDrag = (e: React.PointerEvent, d: Drag) => {
    const t = Math.max(d.lo, Math.min(d.hi, tOf(e.clientX)));
    // 붙은 뒤에도 0.4초를 지켜야 한다 — 마지막 어절 경계가 하한보다 앞이면 서버가 400 을 낸다
    const at = Math.max(d.lo, Math.min(d.hi, snap(t, { ...d, alt: e.altKey })));
    setDragBoth(null); setCutT(null);
    onResize?.(d.from, Math.round(at * 1000) / 1000);
  };

  return (
    <div ref={box} className="scroll-thin overflow-x-auto pb-2">
      <div className="relative" style={{ width: LABEL_W + width }}>
        <div className="grid" style={{ gridTemplateColumns: `${LABEL_W}px ${width}px` }}>
          {/* 눈금 */}
          <div />
          <div className="relative h-6 cursor-pointer select-none border-b border-line" onClick={seekAt}>
            {ticks.map((s) => (
              <div key={s} className="absolute bottom-0 border-l border-line-strong" style={{ left: s * pps, height: s % 5 === 0 ? 10 : 5 }}>
                {s % 5 === 0 && <span className="absolute -top-[15px] left-1 whitespace-nowrap text-[11px] text-sub">{s}초</span>}
              </div>
            ))}
          </div>

          <RowLabel>문장</RowLabel>
          <div className="relative h-[54px] border-b border-line" onClick={seekAt}>
            {sentences.map((s) => (
              <div key={s.index} title={s.text} className={cx("absolute top-1 bottom-1 overflow-hidden rounded-md border px-1.5 py-0.5 text-[11px] leading-tight", s.index === activeSentence ? "border-accent bg-[color-mix(in_srgb,var(--c-accent)_10%,transparent)]" : "border-line bg-fill")}
                style={{ left: s.start * pps + 1, width: Math.max(8, (s.end - s.start) * pps - 2) }}>
                <span className="text-sub">{s.index === 0 ? "훅" : s.index}</span> <span className="line-clamp-2 break-keep">{s.text}</span>
              </div>
            ))}
          </div>

          <RowLabel>그림</RowLabel>
          <div className="relative h-[76px] border-b border-line" onClick={seekAt}>
            {tl.shots.map((s, i) => {
              const sc = scoreOf(i);
              const low = sc != null && sc < 0.35;
              return (
                <div key={i} draggable
                  onDragStart={(e) => { if (drag) { e.preventDefault(); return; } setDragFrom(i); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); }}
                  onDragEnd={() => { setDragFrom(null); setOver(null); }}
                  onDragOver={(e) => { e.preventDefault(); if (over !== i) setOver(i); }}
                  onDrop={(e) => { e.preventDefault(); const from = dragRef.current; if (from != null && from !== i) onSwap(from, i); setDragFrom(null); setOver(null); }}
                  onClick={(e) => { e.stopPropagation(); onSel(i); onSeek(s.start + Math.min(0.25, (s.end - s.start) / 2)); }}
                  title={`${i + 1}번 그림 · ${s.start.toFixed(1)}–${s.end.toFixed(1)}초 (${(s.end - s.start).toFixed(2)}초)${s.kind === "meme" ? " · 전체화면 짤" : ""}${s.cut === "user" ? " · 사람이 옮긴 경계" : ""}\n끌어서 다른 그림과 맞바꾸기`}
                  className={cx("absolute top-1 bottom-1 cursor-grab overflow-hidden rounded-md bg-fill active:cursor-grabbing", sel === i ? "ring-2 ring-accent" : "ring-1 ring-inset ring-line-strong", over === i && dragFrom !== i && "ring-2 ring-accent", dragFrom === i && "opacity-50")}
                  style={{ left: s.start * pps + 1, width: Math.max(8, (s.end - s.start) * pps - 2) }}>
                  <img src={resolve(s.file)} alt="" draggable={false} loading="lazy" className="h-full w-full object-cover" />
                  {sc != null && <span className={cx("absolute bottom-0.5 left-0.5 rounded px-1 text-[11px] font-medium leading-4 text-white", low ? "bg-[#b36b00]" : "bg-black/65")}>{sc.toFixed(2)}</span>}
                  {s.cut === "user" && <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-accent ring-1 ring-white/70" title="사람이 옮긴 경계" />}
                  {drag?.from === i && cutT != null && <span className="pointer-events-none absolute right-0 top-0 bottom-0 w-[3px] bg-accent" />}
                </div>
              );
            })}
            {/* 경계 손잡이: 같은 문장의 연속한 두 일반 샷 사이에만(짤 옆·문장 경계에는 없음).
                썸네일의 HTML5 드래그와 안 부딪히게 썸네일의 자식이 아니라 형제로 둔다. */}
            {onResize && tl.shots.map((s, i) => {
              const n = tl.shots[i + 1];
              if (!n || s.kind === "meme" || n.kind === "meme") return null;
              const a = sentenceOwner(sentences, s.start), b = sentenceOwner(sentences, n.start);
              if (a == null || a !== b) return null;
              if (n.end - s.start <= MIN_SHOT_S * 2) return null;   // 옮길 자리가 없음
              const live = drag?.from === i;
              return (
                <div key={`h${i}`} role="separator" aria-orientation="vertical" aria-label={`${i + 1}·${i + 2}번 그림 경계 옮기기`}
                  onPointerDown={(e) => startDrag(e, i)}
                  onPointerMove={(e) => { const d = dragLive.current; if (d && d.from === i) moveDrag(e, d); }}
                  onPointerUp={(e) => { const d = dragLive.current; if (d && d.from === i) endDrag(e, d); }}
                  onPointerCancel={() => { setDragBoth(null); setCutT(null); }}
                  onClick={(e) => e.stopPropagation()}   // 놓을 때 줄 클릭(탐색)까지 가지 않게
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover((h) => (h === i ? null : h))}
                  className="absolute top-0 bottom-0 z-10 -translate-x-1/2 touch-none"
                  style={{ left: s.end * pps, width: HANDLE_W, cursor: "col-resize" }}>
                  <div className={cx("mx-auto h-full w-[2px] rounded transition-colors", live ? "bg-accent" : hover === i ? "bg-accent/80" : "bg-transparent")} />
                </div>
              );
            })}
            {drag && cutT != null && (
              <CutOverlay gaps={drag.gaps} t={cutT} lo={drag.lo} hi={drag.hi} pps={pps}
                snapT={!drag.alt && drag.gaps.some((g) => Math.abs(g - cutT) < 1e-6) ? cutT : null} />
            )}
          </div>

          <RowLabel>자막</RowLabel>
          <div className="relative h-8 border-b border-line" onClick={seekAt}>
            {tl.captions.map((c, i) => (
              <div key={i} title={c.text} className="absolute top-1 bottom-1 overflow-hidden whitespace-nowrap rounded bg-fill px-1 text-[11px] leading-5 text-sub" style={{ left: c.start * pps + 1, width: Math.max(4, (c.end - c.start) * pps - 2) }}>{c.text}</div>
            ))}
          </div>

          <RowLabel>목소리</RowLabel>
          <div className="relative h-12 cursor-pointer" onClick={seekAt}>
            {voiceUrl && <div style={{ width: (audioDur ?? tl.duration) * pps }}><Waveform url={voiceUrl} bars={Math.max(40, Math.round(((audioDur ?? tl.duration) * pps) / 4))} height={44} /></div>}
          </div>
        </div>
        <div className="pointer-events-none absolute inset-y-0" style={{ left: LABEL_W, width }}>
          <Playhead subscribe={subscribe} pps={pps} />
        </div>
      </div>
    </div>
  );
}

/** 샷이 속한 문장 index: 시작이 그 문장 시작 이상인 마지막 문장(훅은 0초부터 — 장면 편집기의 sentenceIdxOf 와 같은 규칙). */
function sentenceOwner(sentences: SceneSentence[], t: number): number | null {
  let k: number | null = null;
  for (const s of sentences) if ((s.index === sentences[0]?.index ? 0 : s.start) <= t + 0.002) k = s.index;
  return k;
}

function RowLabel({ children }: { children: string }) {
  return <div className="flex items-center border-b border-line text-[11px] font-medium text-sub last:border-0">{children}</div>;
}
