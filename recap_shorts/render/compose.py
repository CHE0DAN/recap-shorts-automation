"""Pillow 로 프레임 합성. 고정 레이어·훅·자막은 한 번만 그려 재사용한다."""
from __future__ import annotations

import bisect
import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from . import captions as cap
from . import intro as INTRO
from . import layout as L
from . import overlays as OV

ENTER_SEC = 0.2
ENTER_BLUR = 6.0
ENTER_RISE = 24
MEME_SHOT_MARGIN = 0  # 전체화면 짤 샷에서 상자 가장자리와 짤 사이(상자 높이에 딱 맞춤)
ZOOM_END = 1.08
BASE_SCALE = 1.5  # 확대용 원본 보관 배율(1620x1215)


# ---------- 순수 계산 (시험 대상) ----------

def cover_box(iw: int, ih: int, focus=(0.5, 0.5), ratio: float = L.IMAGE_RATIO):
    """원본(iw x ih)에서 ratio(가로/세로) 비율로 가장 크게 자르는 상자 (x0,y0,x1,y1).

    focus(0~1)가 상자 중심이 되도록 하되 이미지 밖으로 나가지 않게 민다.
    """
    fx = min(1.0, max(0.0, float(focus[0])))
    fy = min(1.0, max(0.0, float(focus[1])))
    if iw / ih > ratio:
        ch = ih
        cw = int(round(ih * ratio))
    else:
        cw = iw
        ch = int(round(iw / ratio))
    x0 = int(round(fx * iw - cw / 2))
    y0 = int(round(fy * ih - ch / 2))
    x0 = max(0, min(iw - cw, x0))
    y0 = max(0, min(ih - ch, y0))
    return (x0, y0, x0 + cw, y0 + ch)


def snap_captions_to_cuts(caps: list, cuts: list, tol: float = 0.15, min_len: float = 0.3) -> list:
    """카드의 시작·끝이 컷 시각과 tol 초 안이면 컷 시각으로 옮겨 같은 프레임에서 바뀌게 한다."""
    cuts = [c for c in cuts if c > 0]

    def near(t):
        if not cuts:
            return t
        c = min(cuts, key=lambda x: abs(x - t))
        return c if abs(c - t) <= tol else t

    out = []
    for c in caps:
        n = dict(c)
        s, e = near(c["start"]), near(c["end"])
        if e - s >= min_len:
            n["start"], n["end"] = s, e
        out.append(n)
    return out


def zoom_scale(t: float, start: float, end: float) -> float:
    d = max(1e-9, end - start)
    p = min(1.0, max(0.0, (t - start) / d))
    return 1.0 + (ZOOM_END - 1.0) * p


def enter_params(t_since_start: float):
    """(흐림 반경, 아래 이동 px, 불투명도)."""
    p = min(1.0, max(0.0, t_since_start / ENTER_SEC))
    return ENTER_BLUR * (1 - p), ENTER_RISE * (1 - p), p


# ---------- 그리기 도구 ----------

def _fit_size(text: str, max_w: int, size_max: int, size_min: int, stroke: int = 0, title: bool = False) -> int:
    for size in range(size_max, size_min - 1, -2):
        if L.load_font(size, title).getlength(text) + 2 * stroke <= max_w:
            return size
    return size_min


def make_fixed_layer(title_lines) -> Image.Image:
    img = Image.new("RGB", (L.W, L.H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    lines = list(title_lines)[:2]
    while len(lines) < 2:
        lines.append("")
    sizes = [_fit_size(t, L.TEXT_MAX_W, L.TITLE_SIZE_MAX, L.TITLE_SIZE_MIN, title=True) for t in lines if t]
    size = min(sizes) if sizes else L.TITLE_SIZE_MAX
    line_h = int(size * 1.3)
    cy = (L.TITLE_Y0 + L.TITLE_Y1) / 2
    ys = [cy - line_h / 2, cy + line_h / 2]
    cols = [L.TITLE_COLOR_1, L.TITLE_COLOR_2]
    font = L.load_font(size, True)
    for t, y, c in zip(lines, ys, cols):
        if t:
            d.text((L.W / 2, y), t, font=font, fill=c, anchor="mm")
    return img


def make_hook_overlay(text: str) -> Image.Image:
    """이미지 상자 크기(1080x810) RGBA 위에 흰 둥근 띠 + 검은 글씨 한 줄."""
    ov = Image.new("RGBA", (L.IMAGE_W, L.IMAGE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    x0, x1 = L.HOOK_MARGIN_X, L.IMAGE_W - L.HOOK_MARGIN_X
    y0 = L.HOOK_TOP_OFFSET
    y1 = y0 + L.HOOK_H
    d.rounded_rectangle((x0, y0, x1, y1), radius=24, fill=(255, 255, 255, 255))
    size = _fit_size(text, (x1 - x0) - 2 * L.HOOK_PAD_X, L.HOOK_SIZE_MAX, L.HOOK_SIZE_MIN)
    d.text(((x0 + x1) / 2, (y0 + y1) / 2), text, font=L.load_font(size),
           fill=(0, 0, 0, 255), anchor="mm")
    return ov


def make_caption_overlay(text: str, emphasis: Optional[str]) -> Image.Image:
    """전체 화면 크기 RGBA. 자막 띠 안 가운데에 외곽선 글씨."""
    ov = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
    words = text.split()
    norm = " ".join(words)
    fit = cap.fit_text(norm) or cap.fit_text(norm, max_lines=3)  # 2줄이 기본, 넘치면 3줄
    if fit is None:  # 최소 크기로도 안 들어가는 긴 어절: 최소 크기, 줄바꿈은 가운데 근처
        size = L.CAPTION_SIZE_MIN
        k = max(1, len(words) // 2) if len(words) > 1 else len(words)
        lines = [" ".join(words[:k])] + ([" ".join(words[k:])] if words[k:] else [])
    else:
        size, lines, _ = fit
    sep = 1
    mask = cap.emphasis_mask(norm, emphasis)
    font = L.load_font(size)
    line_h = int(size * L.CAPTION_LINE_H)
    band_cy = (L.CAPTION_Y0 + L.CAPTION_Y1) / 2
    top = band_cy - line_h * len(lines) / 2
    d = ImageDraw.Draw(ov)
    off = 0
    sw = L.CAPTION_STROKE
    for li, line in enumerate(lines):
        cy = top + line_h * (li + 0.5)
        runs: list[tuple[str, bool]] = []
        for ci, ch in enumerate(line):
            e = mask[off + ci]
            if runs and runs[-1][1] == e:
                runs[-1] = (runs[-1][0] + ch, e)
            else:
                runs.append((ch, e))
        acc = (L.W - font.getlength(line)) / 2
        xs = []
        for r, _e in runs:
            xs.append(acc)
            acc += font.getlength(r)
        # 1패스: 외곽선, 2패스: 채우기 (이웃 구간 외곽선이 글자를 덮지 않게)
        for (r, _e), rx in zip(runs, xs):
            d.text((rx, cy), r, font=font, fill=L.OUTLINE_COLOR, anchor="lm",
                   stroke_width=sw, stroke_fill=L.OUTLINE_COLOR)
        for (r, e), rx in zip(runs, xs):
            d.text((rx, cy), r, font=font,
                   fill=L.EMPHASIS_COLOR if e else L.CAPTION_COLOR, anchor="lm")
        off += len(line) + sep
    return ov


# ---------- 합성기 ----------

class Composer:
    def __init__(self, timeline: dict, base_dir: str):
        self.tl = timeline
        self.base_dir = base_dir
        self.fps = int(timeline.get("fps", L.FPS))
        self.shots = sorted(timeline["shots"], key=lambda s: s["start"])
        self.shot_starts = [s["start"] for s in self.shots]
        caps = [dict(c) for c in timeline.get("captions", [])]
        if (timeline.get("options") or {}).get("snap_captions_to_cuts"):
            caps = snap_captions_to_cuts(caps, [s["start"] for s in self.shots])
        self.caps = sorted(caps, key=lambda c: c["start"])
        self.cap_starts = [c["start"] for c in self.caps]
        hook = timeline.get("hook") or None
        self.hook = hook
        self.fixed = make_fixed_layer(timeline.get("title_lines", ["", ""]))
        self._hook_ov = make_hook_overlay(hook["text"]) if hook and hook.get("text") else None
        ic = timeline.get("intro") or None
        self.intro = INTRO.IntroCard(ic) if ic and ic.get("style", "card") == "card" else None
        self._cap_ov: dict[int, Image.Image] = {}
        self._img_cache: dict[int, tuple] = {}
        self._meme_parts: dict[int, tuple] = {}
        self.overlays = sorted(timeline.get("overlays") or [], key=lambda o: o["start"])
        self._stickers = OV.StickerCache(base_dir)
        self._last_key = None
        self._last_bytes = b""

    # --- 이미지 ---
    def _resolve(self, f: str) -> str:
        if os.path.isabs(f) and os.path.exists(f):
            return f
        p = os.path.join(self.base_dir, f)
        return p if os.path.exists(p) else f

    def _shot_images(self, idx: int):
        """(확대용 큰 4:3, 1080x810 정지본)."""
        if idx in self._img_cache:
            return self._img_cache[idx]
        shot = self.shots[idx]
        if len(self._img_cache) > 3:
            self._img_cache.pop(next(iter(self._img_cache)))
        if shot.get("kind") == "meme":
            flat = self._meme_box(idx, 1.0)
            self._img_cache[idx] = (flat, flat)
            return self._img_cache[idx]
        src = Image.open(self._resolve(shot["file"])).convert("RGB")
        box = cover_box(src.width, src.height, shot.get("focus") or (0.5, 0.5))
        crop = src.crop(box)
        big = crop.resize((int(L.IMAGE_W * BASE_SCALE), int(L.IMAGE_H * BASE_SCALE)), Image.LANCZOS)
        flat = crop.resize((L.IMAGE_W, L.IMAGE_H), Image.LANCZOS)
        self._img_cache[idx] = (big, flat)
        return self._img_cache[idx]

    def _meme_box(self, idx: int, scale: float) -> Image.Image:
        """전체화면 짤 샷: 단색 배경 위에 contain-fit 한 짤을 가운데 놓는다(scale 은 등장 효과용 배율)."""
        shot = self.shots[idx]
        if idx not in self._meme_parts:
            src = Image.open(self._resolve(shot["file"]))
            src.load()
            src = src.convert("RGBA")
            margin = int(shot.get("margin", MEME_SHOT_MARGIN))
            mw, mh = L.IMAGE_W - 2 * margin, L.IMAGE_H - 2 * margin
            fit = shot.get("fit", "auto")
            wide = src.width / src.height >= float(shot.get("wide_aspect", 1.25))
            if fit == "cover" or (fit == "auto" and wide):  # 가로로 넓은 짤: 상자를 가득 채움(가운데 자름)
                r = max(mw / src.width, mh / src.height)
                big = src.resize((max(1, int(round(src.width * r))), max(1, int(round(src.height * r)))), Image.LANCZOS)
                # 짤(밈)은 얼굴(그림 위쪽) 기준으로 확대해 자른다
                fy = min(1.0, max(0.0, float(shot.get("fit_focus_y", 0.5))))
                x0, y0 = (big.width - mw) // 2, int(round((big.height - mh) * fy))
                self._meme_parts[idx] = big.crop((x0, y0, x0 + mw, y0 + mh))
            else:  # 정사각·세로 짤: 상자 높이에 맞춰 가운데, 남는 좌우는 배경색
                r = min(mw / src.width, mh / src.height)
                self._meme_parts[idx] = src.resize((max(1, int(src.width * r)), max(1, int(src.height * r))), Image.LANCZOS)
            if len(self._meme_parts) > 4:
                self._meme_parts.pop(next(iter(self._meme_parts)))
        im = self._meme_parts[idx]
        bg = Image.new("RGB", (L.IMAGE_W, L.IMAGE_H), tuple(shot.get("bg") or (20, 20, 20)))
        if scale != 1.0:
            if scale <= 0.01:
                return bg
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
        bg.paste(im, ((L.IMAGE_W - im.width) // 2, (L.IMAGE_H - im.height) // 2), im)
        return bg

    def _shot_index(self, t: float) -> int:
        i = bisect.bisect_right(self.shot_starts, t + 1e-9) - 1
        return max(0, i)

    def _cap_index(self, t: float) -> int:
        i = bisect.bisect_right(self.cap_starts, t + 1e-9) - 1
        if i >= 0 and t < self.caps[i]["end"] - 1e-9:
            return i
        return -1

    def _intro_on(self, t: float) -> bool:
        return self.intro is not None and t < self.intro.t_cut - 1e-9

    def _hook_on(self, t: float) -> bool:
        return bool(self._hook_ov) and self.hook["start"] - 1e-9 <= t < self.hook["end"] - 1e-9

    def image_box(self, idx: int, t: float) -> Image.Image:
        shot = self.shots[idx]
        big, flat = self._shot_images(idx)
        motion = shot.get("motion", "static")
        if shot.get("kind") == "meme":
            if shot.get("anim", "pop") == "pop" and self._meme_popping(shot, t):
                return self._meme_box(idx, OV.pop_scale(t - shot["start"], shot.get("pop_s", 0.18),
                                                        shot.get("overshoot", 1.12)))
            return flat
        if motion == "zoom_in":
            s = zoom_scale(t, shot["start"], shot["end"])
            bw, bh = big.width / s, big.height / s
            x0, y0 = (big.width - bw) / 2, (big.height - bh) / 2
            return big.resize((L.IMAGE_W, L.IMAGE_H), Image.BICUBIC, box=(x0, y0, x0 + bw, y0 + bh))
        if motion == "enter" and t - shot["start"] < ENTER_SEC:
            blur, dy, a = enter_params(t - shot["start"])
            im = flat.filter(ImageFilter.GaussianBlur(blur)) if blur > 0.05 else flat
            # 앞 샷 위로 겹쳐 들어온다(검은 화면에서 나타나면 0.2초 동안 상자가 깜빡여 보임)
            under = self._shot_images(idx - 1)[1] if idx > 0 else Image.new("RGB", (L.IMAGE_W, L.IMAGE_H), (0, 0, 0))
            canvas = under.copy()
            canvas.paste(im, (0, int(round(dy))))
            return Image.blend(under, canvas, a)
        return flat

    @staticmethod
    def _meme_popping(shot: dict, t: float) -> bool:
        return shot.get("anim", "pop") == "pop" and t - shot["start"] < shot.get("pop_s", 0.18) + 1e-9

    def _overlay_key(self, t: float, i: int) -> tuple:
        """지금 보이는 스티커 목록 + (움직이는 중이면 프레임 번호) — 같으면 앞 프레임을 재사용."""
        return tuple((n, i if OV.is_animating(o, t) else -1) for n, o in enumerate(self.overlays) if OV.is_active(o, t))

    def _caption_overlay(self, ci: int) -> Image.Image:
        if ci not in self._cap_ov:
            c = self.caps[ci]
            self._cap_ov[ci] = make_caption_overlay(c["text"], c.get("emphasis"))
        return self._cap_ov[ci]

    def frame_key(self, i: int):
        t = i / self.fps
        if self._intro_on(t):       # 인트로: 상자에는 카드만, 훅 띠·자막·스티커 없음. 글자가 계속 커져 프레임마다 다름
            return ("intro", i)
        si = self._shot_index(t)
        motion = self.shots[si].get("motion", "static")
        hook = self._hook_on(t)
        ci = -1 if hook else self._cap_index(t)
        if self.shots[si].get("kind") == "meme":
            phase = i if self._meme_popping(self.shots[si], t) else -1
        elif motion == "zoom_in":
            phase = i
        elif motion == "enter" and t - self.shots[si]["start"] < ENTER_SEC:
            phase = i
        else:
            phase = -1
        return (si, phase, hook, ci, self._overlay_key(t, i))

    def frame_bytes(self, i: int) -> bytes:
        """프레임 i 의 rgb24 바이트. 앞 프레임과 같은 모양이면 그대로 재사용."""
        key = self.frame_key(i)
        if key == self._last_key:
            return self._last_bytes
        if key[0] == "intro":
            frame = self.fixed.copy()
            frame.paste(self.intro.frame(i / self.fps), (0, L.IMAGE_Y0))
            self._last_key, self._last_bytes = key, frame.tobytes()
            return self._last_bytes
        si, _, hook, ci, ovk = key
        t = i / self.fps
        frame = self.fixed.copy()
        frame.paste(self.image_box(si, t), (0, L.IMAGE_Y0))
        if hook or ovk:
            region = frame.crop((0, L.IMAGE_Y0, L.W, L.IMAGE_Y1))
            if hook:
                region.paste(self._hook_ov, (0, 0), self._hook_ov)
            for n, _ph in ovk:  # 스티커는 훅 띠 위, 자막 아래
                self._stickers.draw(region, self.overlays[n], t)
            frame.paste(region, (0, L.IMAGE_Y0))
        if ci >= 0:
            ov = self._caption_overlay(ci)
            frame.paste(ov, (0, 0), ov)
        self._last_key, self._last_bytes = key, frame.tobytes()
        return self._last_bytes

    def frame_image(self, i: int) -> Image.Image:
        return Image.frombytes("RGB", (L.W, L.H), self.frame_bytes(i))
