"""짤(스티커) 오버레이: 움직임 계산(순수 함수)과 그리기.

타임라인 overlays 항목 = {"kind":"sticker","file","start","end","anchor","size_frac","anim","beat","meme_id",
 (선택) "pop_s","overshoot","fade_s","shake_px","outline_px","margin_px"}.
size_frac = 이미지 상자 가로(1080) 대비 스티커 가로 비율. 좌표는 모두 이미지 상자(1080x810) 안.
"""
from __future__ import annotations

import math
import os
from typing import Optional

from PIL import Image, ImageChops, ImageFilter, ImageDraw

from . import layout as L

ANCHORS = ("box_br", "box_bl", "box_tr", "box_tl", "box_center")
MAX_H_FRAC = 0.62  # 스티커 세로가 상자 높이의 이 비율을 넘으면 줄인다
SHAKE_HZ = 14.0
SLIDE_FRAC = 0.30  # slide_up 이 올라오는 거리(상자 높이 비율)
PRE = 1.25  # 미리 만들어 두는 크기 배율(오버슈트 때 업스케일 방지)

DEFAULTS = {"pop_s": 0.18, "overshoot": 1.12, "fade_s": 0.12, "shake_px": 10.0, "outline_px": 6, "margin_px": 24}


def _p(ov: dict, k: str):
    return ov.get(k, DEFAULTS[k])


def pop_scale(rel: float, pop_s: float, overshoot: float) -> float:
    """등장 후 rel 초의 배율: 0 → overshoot(약 65% 지점) → 1."""
    if rel <= 0:
        return 0.0
    if pop_s <= 1e-6 or rel >= pop_s:
        return 1.0
    p = rel / pop_s
    k = 0.65
    if p < k:
        return overshoot * math.sin(p / k * math.pi / 2)
    q = (p - k) / (1 - k)
    q = q * q * (3 - 2 * q)
    return overshoot + (1.0 - overshoot) * q


def anchor_xy(anchor: str, w: float, h: float, margin: float = 24) -> tuple[float, float]:
    """스티커(w x h)의 왼쪽 위 좌표(이미지 상자 기준)."""
    W, H = L.IMAGE_W, L.IMAGE_H
    if anchor == "box_bl":
        return margin, H - h - margin
    if anchor == "box_tr":
        return W - w - margin, margin + L.HOOK_TOP_OFFSET + L.HOOK_H
    if anchor == "box_tl":
        return margin, margin + L.HOOK_TOP_OFFSET + L.HOOK_H
    if anchor == "box_center":
        return (W - w) / 2, (H - h) / 2
    return W - w - margin, H - h - margin  # box_br (기본)


def rest_size(img_w: int, img_h: int, size_frac: float) -> tuple[int, int]:
    w = max(8.0, size_frac * L.IMAGE_W)
    h = w * img_h / img_w
    if h > MAX_H_FRAC * L.IMAGE_H:
        h = MAX_H_FRAC * L.IMAGE_H
        w = h * img_w / img_h
    return int(round(w)), int(round(h))


def is_active(ov: dict, t: float) -> bool:
    return ov["start"] - 1e-9 <= t < ov["end"] - 1e-9


def is_animating(ov: dict, t: float) -> bool:
    """이 시각에 매 프레임 다시 그려야 하는가(등장·퇴장 구간이거나 흔들림)."""
    if not is_active(ov, t):
        return False
    rel = t - ov["start"]
    if ov.get("anim") == "none":
        return False
    return (rel < _p(ov, "pop_s") + 1e-9 or ov["end"] - t < _p(ov, "fade_s") + 1e-9
            or ov.get("anim") == "shake")


def overlay_state(ov: dict, t: float) -> Optional[dict]:
    """시각 t 의 {"scale","dx","dy","alpha"} (상자 좌표 이동 px). 구간 밖이면 None."""
    if not is_active(ov, t):
        return None
    rel = t - ov["start"]
    pop_s, fade_s = _p(ov, "pop_s"), _p(ov, "fade_s")
    anim = ov.get("anim", "pop")
    if anim == "none":  # 컷 전환: 효과 없이 그대로 나타났다 그대로 사라짐
        return {"scale": 1.0, "dx": 0.0, "dy": 0.0, "alpha": 1.0}
    scale, dx, dy = 1.0, 0.0, 0.0
    alpha = 1.0
    if anim in ("pop", "shake"):
        scale = pop_scale(rel, pop_s, _p(ov, "overshoot"))
        alpha = min(1.0, rel / max(pop_s * 0.4, 1e-6))
        if anim == "shake":
            dur = max(ov["end"] - ov["start"], 1e-6)
            amp = _p(ov, "shake_px") * (1.0 - 0.5 * rel / dur)
            dx = amp * math.sin(2 * math.pi * SHAKE_HZ * rel)
    elif anim == "slide_up":
        p = min(1.0, rel / max(pop_s, 1e-6))
        e = 1 - (1 - p) ** 3
        dy = (1 - e) * SLIDE_FRAC * L.IMAGE_H
        alpha = min(1.0, rel / max(pop_s * 0.5, 1e-6))
    if fade_s > 1e-6:
        alpha *= max(0.0, min(1.0, (ov["end"] - t) / fade_s))
    return {"scale": scale, "dx": dx, "dy": dy, "alpha": max(0.0, min(1.0, alpha))}


def style_sticker(img: Image.Image, outline_px: int) -> Image.Image:
    """투명 PNG 면 흰 테두리 + 그림자, 사각 그림이면 둥근 모서리 + 흰 테두리."""
    im = img.convert("RGBA")
    a = im.getchannel("A")
    if a.getextrema()[0] == 255:  # 투명한 곳이 없는 사각 그림
        r = max(8, min(im.size) // 12)
        m = Image.new("L", im.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=r, fill=255)
        im.putalpha(m)
        a = m
    ol = max(0, int(outline_px))
    pad = ol + 14
    canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    full = Image.new("L", canvas.size, 0)
    full.paste(a, (pad, pad))
    if ol:
        ring = full.filter(ImageFilter.MaxFilter(2 * ol + 1))
        white = Image.new("RGBA", canvas.size, (255, 255, 255, 255))
        white.putalpha(ring)
    else:
        ring = full
        white = None
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
    sh_a = ImageChops.offset(ring, 3, 6).filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.45))
    shadow.putalpha(sh_a)
    canvas = Image.alpha_composite(canvas, shadow)
    if white is not None:
        canvas = Image.alpha_composite(canvas, white)
    top = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    top.paste(im, (pad, pad))
    return Image.alpha_composite(canvas, top)


class StickerCache:
    """파일별로 스타일(테두리·그림자)을 입힌 기준 그림을 한 번만 만든다."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self._base: dict[tuple, tuple[Image.Image, int, int]] = {}

    def _resolve(self, f: str) -> str:
        if os.path.isabs(f):
            return f
        p = os.path.join(self.base_dir, f)
        return p if os.path.exists(p) else f

    def base(self, ov: dict):
        """(기준 그림 RGBA, 가만히 있을 때의 가로, 세로). 기준 그림은 (가로,세로)에 테두리 여백을 더한 크기에 PRE 배."""
        key = (ov["file"], round(float(ov.get("size_frac", 0.38)), 4), int(_p(ov, "outline_px")))
        if key in self._base:
            return self._base[key]
        src = Image.open(self._resolve(ov["file"]))
        src.load()
        rw, rh = rest_size(src.width, src.height, float(ov.get("size_frac", 0.38)))
        ol = int(_p(ov, "outline_px"))
        target = (max(8, int(rw * PRE)), max(8, int(rh * PRE)))
        small = src.convert("RGBA").resize(target, Image.LANCZOS)
        styled = style_sticker(small, int(round(ol * PRE)))
        self._base[key] = (styled, rw, rh)
        if len(self._base) > 8:
            self._base.pop(next(iter(self._base)))
        return self._base[key]

    def draw(self, region: Image.Image, ov: dict, t: float) -> None:
        """region(이미지 상자 크기 RGB) 위에 스티커를 그린다."""
        st = overlay_state(ov, t)
        if st is None or st["scale"] <= 0.01 or st["alpha"] <= 0.01:
            return
        styled, rw, rh = self.base(ov)
        # 기준 그림은 PRE 배로 만들어 두었으므로 1/PRE 이 가만히 있을 때(배율 1)의 크기(테두리·그림자 여백 포함)
        full_w = styled.width / PRE
        full_h = styled.height / PRE
        w = max(2, int(round(full_w * st["scale"])))
        h = max(2, int(round(full_h * st["scale"])))
        im = styled.resize((w, h), Image.BILINEAR if w < styled.width else Image.LANCZOS)
        if st["alpha"] < 0.999:
            im.putalpha(im.getchannel("A").point(lambda v, a=st["alpha"]: int(v * a)))
        x0, y0 = anchor_xy(ov.get("anchor", "box_br"), full_w, full_h, float(_p(ov, "margin_px")))
        cx, cy = x0 + full_w / 2 + st["dx"], y0 + full_h / 2 + st["dy"]
        region.paste(im, (int(round(cx - w / 2)), int(round(cy - h / 2))), im)
