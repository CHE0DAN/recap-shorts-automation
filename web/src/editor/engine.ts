// 브라우저 미리보기 합성기. 백엔드 렌더러(recap_shorts/render/compose.py, layout.py)와 같은 규격·같은 수식을 캔버스로 옮긴 것.
// 원칙: (1) 시각 t 하나로 한 프레임을 순수하게 그린다,
// (2) 글꼴 로드 뒤 폭을 재서 줄바꿈을 정한다(텍스트 캐시), (3) 이미지는 호출하는 쪽이 캐시한다.
import type { Caption, IntroPreview, Shot, Timeline } from "../types";

// ---- layout.py 상수(1080x1920 기준) ----
export const W = 1080, H = 1920;
export const IMAGE_X = 0, IMAGE_Y = 465, IMAGE_W = 1080, IMAGE_H = 810;
const TITLE_CY = 465 / 2;
const CAPTION_CY = (1275 + 1455) / 2;
const SIDE = 60, TEXT_MAX_W = W - 2 * SIDE;
const CAP_MAX = 66, CAP_MIN = 46, CAP_STROKE = 6, CAP_LINE_H = 1.25;
const TITLE_MAX = 120, TITLE_MIN = 40;
const HOOK_X = 40, HOOK_Y = IMAGE_Y + 24, HOOK_H = 110, HOOK_PAD = 28, HOOK_MAX = 62, HOOK_MIN = 30;
const ENTER_SEC = 0.2, ENTER_BLUR = 6, ENTER_RISE = 24, ZOOM_END = 1.08;
const EMPH = "#FFC21A", TITLE2 = "#FFD400";

export const FONT_CAP = "RS Pretendard 800";
export const FONT_TITLE = "RS Pretendard 900";
const FALLBACK = `"Pretendard Variable", Pretendard, "Malgun Gothic", "Apple SD Gothic Neo", sans-serif`;

let fontsReady: Promise<void> | null = null;
/** assets/fonts 의 Pretendard 를 /fonts/ 에서 받고, 없으면 jsDelivr 의 웹폰트로 물러난다. */
export function ensureFonts(): Promise<void> {
  if (fontsReady) return fontsReady;
  const CDN = "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/static/woff2/";
  const load = async (family: string, weight: string, local: string, cdn: string) => {
    for (const src of [`/fonts/${local}`, CDN + cdn]) {
      try {
        const face = new FontFace(family, `url(${src})`, { weight });
        await face.load();
        document.fonts.add(face);
        return;
      } catch { /* 다음 후보 */ }
    }
  };
  fontsReady = Promise.all([
    load(FONT_CAP, "800", "Pretendard-ExtraBold.otf", "Pretendard-ExtraBold.woff2"),
    load(FONT_TITLE, "900", "Pretendard-Black.otf", "Pretendard-Black.woff2"),
  ]).then(() => { widthCache.clear(); });
  return fontsReady;
}
const font = (px: number, title = false) => `${title ? 900 : 800} ${px}px "${title ? FONT_TITLE : FONT_CAP}", ${FALLBACK}`;

// ---- 글자 폭 캐시 ----
const widthCache = new Map<string, number>();
let mctx: CanvasRenderingContext2D | null = null;
function textW(text: string, px: number, title = false): number {
  const key = `${title ? "t" : "c"}${px}|${text}`;
  let v = widthCache.get(key);
  if (v === undefined) {
    mctx ??= document.createElement("canvas").getContext("2d")!;
    mctx.font = font(px, title);
    v = mctx.measureText(text).width;
    widthCache.set(key, v);
  }
  return v;
}

// ---- 순수 계산(compose.py / captions.py) ----
export function coverBox(iw: number, ih: number, focus: [number, number] = [0.5, 0.5], ratio = IMAGE_W / IMAGE_H) {
  const fx = Math.min(1, Math.max(0, focus[0])), fy = Math.min(1, Math.max(0, focus[1]));
  let cw: number, ch: number;
  if (iw / ih > ratio) { ch = ih; cw = Math.round(ih * ratio); } else { cw = iw; ch = Math.round(iw / ratio); }
  const x0 = Math.max(0, Math.min(iw - cw, Math.round(fx * iw - cw / 2)));
  const y0 = Math.max(0, Math.min(ih - ch, Math.round(fy * ih - ch / 2)));
  return { x: x0, y: y0, w: cw, h: ch };
}
export const zoomScale = (t: number, start: number, end: number) => 1 + (ZOOM_END - 1) * Math.min(1, Math.max(0, (t - start) / Math.max(1e-9, end - start)));

function fitSize(text: string, maxW: number, hi: number, lo: number, title = false, stroke = 0) {
  for (let s = hi; s >= lo; s -= 2) if (textW(text, s, title) + 2 * stroke <= maxW) return s;
  return lo;
}

export interface CaptionLayout { size: number; lines: string[] }
const capCache = new Map<string, CaptionLayout>();
/** captions.fit_text: 한 줄 → 두 줄(넓은 쪽이 가장 좁아지는 어절 경계) → 세 줄. */
export function layoutCaption(text: string): CaptionLayout {
  const norm = text.split(/\s+/).filter(Boolean).join(" ");
  const hit = capCache.get(norm);
  if (hit) return hit;
  const words = norm.split(" ");
  const w = (s: string, size: number) => textW(s, size) + 2 * CAP_STROKE;
  let out: CaptionLayout | null = null;
  for (let size = CAP_MAX; size >= CAP_MIN && !out; size -= 2) {
    if (w(norm, size) <= TEXT_MAX_W) { out = { size, lines: [norm] }; break; }
    if (words.length >= 2) {
      let best: [number, string, string] | null = null;
      for (let k = 1; k < words.length; k++) {
        const l1 = words.slice(0, k).join(" "), l2 = words.slice(k).join(" ");
        const mw = Math.max(w(l1, size), w(l2, size));
        if (mw <= TEXT_MAX_W && (!best || mw < best[0])) best = [mw, l1, l2];
      }
      if (best) out = { size, lines: [best[1], best[2]] };
    }
  }
  if (!out && words.length >= 3) {
    for (let size = CAP_MAX; size >= CAP_MIN && !out; size -= 2) {
      let best: [number, string[]] | null = null;
      for (let a = 1; a < words.length - 1; a++) for (let b = a + 1; b < words.length; b++) {
        const ls = [words.slice(0, a).join(" "), words.slice(a, b).join(" "), words.slice(b).join(" ")];
        const mw = Math.max(...ls.map((x) => w(x, size)));
        if (mw <= TEXT_MAX_W && (!best || mw < best[0])) best = [mw, ls];
      }
      if (best) out = { size, lines: best[1] };
    }
  }
  if (!out) { const k = Math.max(1, Math.floor(words.length / 2)); out = { size: CAP_MIN, lines: words.length > 1 ? [words.slice(0, k).join(" "), words.slice(k).join(" ")] : [norm] }; }
  capCache.set(norm, out);
  return out;
}

export function shotAt(tl: Timeline, t: number): number {
  let lo = 0;
  for (let i = 0; i < tl.shots.length; i++) if (tl.shots[i].start <= t + 1e-9) lo = i; else break;
  return lo;
}
export const captionAt = (caps: Caption[], t: number) => caps.find((c) => c.start - 1e-9 <= t && t < c.end - 1e-9) ?? null;

// ---- 그리기 ----
export type ImageGetter = (file: string) => HTMLImageElement | null;

function drawShot(g: CanvasRenderingContext2D, shot: Shot, img: HTMLImageElement, t: number, flat: boolean) {
  const iw = img.naturalWidth, ih = img.naturalHeight;
  if (!iw || !ih) return;
  const b = coverBox(iw, ih, shot.focus ?? [0.5, 0.5]);
  let { x, y, w, h } = b;
  if (!flat && shot.motion === "zoom_in") {
    const s = zoomScale(t, shot.start, shot.end);
    const nw = w / s, nh = h / s;
    x += (w - nw) / 2; y += (h - nh) / 2; w = nw; h = nh;
  }
  g.drawImage(img, x, y, w, h, IMAGE_X, IMAGE_Y, IMAGE_W, IMAGE_H);
}

// ---- 인트로 카드(render/intro.py IntroCard 와 같은 수식) ----
export interface IntroDraw { p: IntroPreview; img: HTMLImageElement | null }
const smoothstep = (x: number) => { const p = Math.min(1, Math.max(0, x)); return p * p * (3 - 2 * p); };
export const introOn = (intro: IntroDraw | null | undefined, t: number) => !!intro && t < intro.p.t_cut - 1e-9;
function introScale(p: IntroPreview, t: number, e: number) {
  const base = 1 + p.zoom_pre_per_s * Math.min(t, p.t_pop);
  if (t <= p.t_pop) return base;
  return base * (1 + (p.pop_text_scale - 1) * e) * (1 + p.zoom_post_per_s * Math.max(0, t - p.t_pop - p.pop_s));
}
/** 0~t_cut: 그림 상자에 흰 판과 글자 묶음만(첫 샷·훅 띠·자막은 렌더처럼 안 그림). t_pop 에 판이 줄고 글자가 커진다. */
function drawIntro(g: CanvasRenderingContext2D, { p, img }: IntroDraw, t: number) {
  const e = p.pop_s > 0 ? smoothstep((t - p.t_pop) / p.pop_s) : Number(t >= p.t_pop);
  g.fillStyle = "#000";
  g.fillRect(IMAGE_X, IMAGE_Y, IMAGE_W, IMAGE_H);
  const ph = Math.round(IMAGE_H * (1 - (1 - p.panel_ratio_end) * e));
  g.fillStyle = p.panel_color;
  g.fillRect(IMAGE_X, IMAGE_Y + Math.floor((IMAGE_H - ph) / 2), IMAGE_W, ph);
  if (!img || !img.naturalWidth) return;
  const z = introScale(p, t, e) / p.ss;
  const gw = img.naturalWidth * z, gh = img.naturalHeight * z;
  g.drawImage(img, IMAGE_X + IMAGE_W / 2 - gw / 2, IMAGE_Y + IMAGE_H / 2 + p.group_cy - gh / 2, gw, gh);
}

/** t 시각의 한 프레임을 (0,0)-(1080,1920) 좌표에 그린다. 호출하는 쪽이 g.setTransform 으로 배율을 준다. */
export function drawFrame(g: CanvasRenderingContext2D, tl: Timeline, t: number, getImage: ImageGetter, intro?: IntroDraw | null) {
  g.save();
  g.fillStyle = "#000";
  g.fillRect(0, 0, W, H);
  g.textBaseline = "middle";
  g.textAlign = "center";

  // 고정 제목 두 줄
  const lines = [...tl.title_lines].slice(0, 2);
  const sizes = lines.filter(Boolean).map((l) => fitSize(l, TEXT_MAX_W, TITLE_MAX, TITLE_MIN, true));
  const size = sizes.length ? Math.min(...sizes) : TITLE_MAX;
  const lh = Math.floor(size * 1.3);
  g.font = font(size, true);
  lines.forEach((l, i) => { if (!l) return; g.fillStyle = i === 0 ? "#fff" : TITLE2; g.fillText(l, W / 2, TITLE_CY + (i === 0 ? -lh / 2 : lh / 2)); });

  if (introOn(intro, t)) { drawIntro(g, intro!, t); g.restore(); return; }

  // 이미지 상자
  g.save();
  g.beginPath(); g.rect(IMAGE_X, IMAGE_Y, IMAGE_W, IMAGE_H); g.clip();
  if (tl.shots.length) {
    const i = shotAt(tl, Math.min(t, Math.max(0, tl.duration - 1e-3)));
    const shot = tl.shots[i];
    const img = getImage(shot.file);
    const since = t - shot.start;
    if (shot.motion === "enter" && since < ENTER_SEC && since >= 0) {
      const p = since / ENTER_SEC;
      const prev = i > 0 ? getImage(tl.shots[i - 1].file) : null;
      if (prev) drawShot(g, tl.shots[i - 1], prev, t, true);
      if (img) {
        g.save();
        g.globalAlpha = p;
        const blur = ENTER_BLUR * (1 - p);
        if (blur > 0.05) g.filter = `blur(${blur}px)`;
        g.translate(0, Math.round(ENTER_RISE * (1 - p)));
        drawShot(g, shot, img, t, true);
        g.restore();
      }
    } else if (img) drawShot(g, shot, img, t, false);
  }
  g.restore();

  // 훅 흰 띠
  if (tl.hook?.text && t >= tl.hook.start - 1e-9 && t < tl.hook.end - 1e-9) {
    const x0 = HOOK_X, x1 = W - HOOK_X;
    g.fillStyle = "#fff";
    g.beginPath(); g.roundRect(x0, HOOK_Y, x1 - x0, HOOK_H, 24); g.fill();
    const hs = fitSize(tl.hook.text, x1 - x0 - 2 * HOOK_PAD, HOOK_MAX, HOOK_MIN);
    g.font = font(hs); g.fillStyle = "#000";
    g.fillText(tl.hook.text, W / 2, HOOK_Y + HOOK_H / 2);
  }

  // 자막 카드
  const cap = captionAt(tl.captions, t);
  if (cap) drawCaption(g, cap);
  g.restore();
}

function drawCaption(g: CanvasRenderingContext2D, cap: Caption) {
  const { size, lines } = layoutCaption(cap.text);
  const norm = lines.join(" ");
  const mask = new Array<boolean>(norm.length).fill(false);
  const e = cap.emphasis?.trim();
  if (e) { const at = norm.indexOf(e); if (at >= 0) for (let j = at; j < at + e.length; j++) mask[j] = true; }
  const lh = Math.floor(size * CAP_LINE_H);
  const top = CAPTION_CY - (lh * lines.length) / 2;
  g.font = font(size);
  g.textAlign = "left";
  g.lineJoin = "round";
  g.lineWidth = CAP_STROKE * 2;
  g.strokeStyle = "#000";
  let off = 0;
  lines.forEach((line, li) => {
    const cy = top + lh * (li + 0.5);
    const runs: { s: string; e: boolean }[] = [];
    [...line].forEach((ch, ci) => {
      const em = mask[off + ci];
      if (runs.length && runs[runs.length - 1].e === em) runs[runs.length - 1].s += ch; else runs.push({ s: ch, e: em });
    });
    let x = (W - textW(line, size)) / 2;
    const xs = runs.map((r) => { const v = x; x += textW(r.s, size); return v; });
    runs.forEach((r, k) => g.strokeText(r.s, xs[k], cy));      // 1패스 외곽선
    runs.forEach((r, k) => { g.fillStyle = r.e ? EMPH : "#fff"; g.fillText(r.s, xs[k], cy); });  // 2패스 채우기
    off += line.length + 1;
  });
}
