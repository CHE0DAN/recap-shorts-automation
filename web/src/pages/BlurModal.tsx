// 가리기 도구: 캡처 카드가 나온 원본 첨부 그림 위에 사각형을 끌어 그리면, 백엔드가 그 영역을 모자이크하고 카드를 다시 만든다.
// 좌표는 원본 그림 픽셀(naturalWidth/Height) 기준으로 보낸다. 같은 원본에서 나온 카드는 모두 같은 가림을 받는다.
import { X } from "lucide-react";
import { useRef, useState } from "react";
import { api, mediaUrl } from "../api";
import { Button, Modal, cx } from "../ui";
import type { AssetEntry } from "../types";

type Box = [number, number, number, number];

export default function BlurModal({ id, entry, assets, bust, onClose, onDone }: {
  id: string; entry: AssetEntry; assets: AssetEntry[]; bust: number; onClose: () => void; onDone: (cards: string[]) => void;
}) {
  const src = entry.src!;
  const siblings = assets.filter((a) => a.kind === "cap" && a.src === src);
  const [boxes, setBoxes] = useState<Box[]>((entry.blur_boxes as Box[] | undefined) ?? []);
  const [nat, setNat] = useState<[number, number] | null>(null);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const img = useRef<HTMLImageElement>(null);

  const toDisp = (n: number, axis: 0 | 1) => (nat ? `${(n / nat[axis]) * 100}%` : "0");
  const pos = (e: React.PointerEvent) => {
    const r = img.current!.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) };
  };
  const down = (e: React.PointerEvent) => {
    if (!nat) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = pos(e);
    setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
  };
  const move = (e: React.PointerEvent) => { if (drag) { const p = pos(e); setDrag({ ...drag, x1: p.x, y1: p.y }); } };
  const up = () => {
    if (drag && nat) {
      const [w, h] = nat;
      const b: Box = [Math.round(Math.min(drag.x0, drag.x1) * w), Math.round(Math.min(drag.y0, drag.y1) * h), Math.round(Math.max(drag.x0, drag.x1) * w), Math.round(Math.max(drag.y0, drag.y1) * h)];
      if (b[2] - b[0] >= 8 && b[3] - b[1] >= 8) setBoxes((p) => [...p, b]);
    }
    setDrag(null);
  };
  async function apply() {
    setBusy(true); setErr(null);
    try { const r = await api.blur(id, entry.file, boxes); onDone(r.cards); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  return (
    <Modal title="가리기" onClose={onClose} wide>
      <div className="scroll-thin flex-1 overflow-y-auto px-6 py-4">
        <p className="text-[15px]">얼굴, 아이디·닉네임, 전화번호처럼 알아볼 수 있는 곳을 끌어서 사각형으로 표시하세요. 적용하면 그 부분이 모자이크로 바뀌고, 이 그림에서 나온 카드 {siblings.length}장이 다시 만들어집니다.</p>
        <p className="mt-1 text-[13px] text-sub">원본 그림을 그대로 보여 줍니다. 점선은 카드로 쓰인 구간이고, 파란 점선이 지금 고른 카드입니다. 사각형을 누르면 지워집니다.</p>
        <div className="stage mt-4 flex justify-center rounded-[14px] border border-line p-4">
          <div className="relative inline-block select-none leading-[0]">
            <img ref={img} src={`${mediaUrl(id, src)}${bust ? `?v=${bust}` : ""}`} alt="원본 첨부 그림" draggable={false}
              onLoad={(e) => setNat([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} className="block max-h-[58vh] max-w-full rounded-md" />
            {nat && siblings.map((s) => {
              const c = s.crop ?? [0, 0, nat[0], nat[1]];
              return <div key={s.file} className={cx("pointer-events-none absolute border-2 border-dashed", s.file === entry.file ? "border-accent" : "border-white/70")}
                style={{ left: toDisp(c[0], 0), top: toDisp(c[1], 1), width: toDisp(c[2] - c[0], 0), height: toDisp(c[3] - c[1], 1) }} />;
            })}
            <div className="absolute inset-0 cursor-crosshair touch-none" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => setDrag(null)}>
              {nat && boxes.map((b, i) => (
                <div key={i} className="group absolute border-2 border-accent bg-[color-mix(in_srgb,var(--c-accent)_30%,transparent)]"
                  style={{ left: toDisp(b[0], 0), top: toDisp(b[1], 1), width: toDisp(b[2] - b[0], 0), height: toDisp(b[3] - b[1], 1) }}>
                  <button aria-label="이 사각형 지우기" onPointerDown={(e) => e.stopPropagation()} onClick={() => setBoxes((p) => p.filter((_, k) => k !== i))}
                    className="absolute -right-2.5 -top-2.5 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white"><X size={12} strokeWidth={2.5} /></button>
                </div>
              ))}
              {drag && <div className="absolute border-2 border-dashed border-accent bg-[color-mix(in_srgb,var(--c-accent)_20%,transparent)]"
                style={{ left: `${Math.min(drag.x0, drag.x1) * 100}%`, top: `${Math.min(drag.y0, drag.y1) * 100}%`, width: `${Math.abs(drag.x1 - drag.x0) * 100}%`, height: `${Math.abs(drag.y1 - drag.y0) * 100}%` }} />}
            </div>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-6 py-3">
        <span className="text-[13px] text-sub">{err ? <span className="text-bad-text">{err}</span> : `가릴 곳 ${boxes.length}군데${nat ? ` · 원본 ${nat[0]}×${nat[1]}` : ""}`}</span>
        <div className="flex gap-2">
          <Button variant="ghost" disabled={busy || boxes.length === 0} onClick={() => setBoxes([])}>모두 지우기</Button>
          <Button variant="secondary" disabled={busy || boxes.length > 0} onClick={apply}>가릴 곳 없음, 확인했습니다</Button>
          <Button variant="primary" disabled={busy || boxes.length === 0} onClick={apply}>{busy ? "적용하는 중" : "가리기 적용"}</Button>
        </div>
      </div>
    </Modal>
  );
}
