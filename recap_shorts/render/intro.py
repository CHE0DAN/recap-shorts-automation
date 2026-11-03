"""인트로 카드 (설정: config/fx.json 의 intro 절).

0 ~ t_cut 동안 그림 상자에는 이 카드만 보인다: 흰 판이 상자를 꽉 채우고(머리줄 + 제목 두 줄), t_pop 에 4프레임(0.067초)
동안 판 높이가 panel_h_start → panel_h_end 로 줄며 글자 묶음이 ×pop_text_scale 로 커진다(ease-in-out).
튀기 전 글자 묶음은 초당 zoom_pre_per_s, 튄 뒤는 zoom_post_per_s 로 천천히 커진다.
기준 크기(1080x1028 상자 기준)는 우리 상자 높이 / ref_box_h 로 줄여 쓴다.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from . import layout as L

SS = 1.3                      # 글자 묶음을 이 배율로 그려 두고 줄여 쓴다(커질 때도 또렷하게)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def hex_rgb(h, default=(255, 255, 255)) -> tuple:
    try:
        h = str(h).lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return default


def smoothstep(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def _regular_font(size: int, candidates) -> ImageFont.FreeTypeFont:
    for c in list(candidates or []):
        path = c if os.path.isabs(c) else os.path.join(ROOT, c)
        if os.path.exists(path):
            return ImageFont.truetype(path, int(size))
    return ImageFont.truetype(L.find_font(), int(size))


EMOJI_FONTS = ["C:/Windows/Fonts/seguiemj.ttf", "/System/Library/Fonts/Apple Color Emoji.ttc",
               "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"]


def emoji_image(ch: str, height_px: int, candidates=None) -> Image.Image | None:
    """컬러 이모지 한 글자 → 높이 height_px 의 RGBA 그림. 이모지 글꼴이 없으면 None(아이콘 없이 글자만)."""
    for c in list(candidates or []) + EMOJI_FONTS:
        path = c if os.path.isabs(c) else os.path.join(ROOT, c)
        if not os.path.exists(path):
            continue
        try:
            f = ImageFont.truetype(path, 109 if path.endswith("NotoColorEmoji.ttf") else 96)
            x0, y0, x1, y1 = f.getbbox(ch)
            im = Image.new("RGBA", (x1 - x0 + 4, y1 - y0 + 4), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((2 - x0, 2 - y0), ch, font=f, embedded_color=True)
            box = im.getbbox()
            if not box:
                continue
            im = im.crop(box)
            h = max(1, int(height_px))
            return im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)
        except Exception:  # noqa: BLE001  이 글꼴로 못 그리면 다음 후보
            continue
    return None


class IntroCard:
    def __init__(self, intro: dict, box_w: int = L.IMAGE_W, box_h: int = L.IMAGE_H):
        self.c = intro
        self.w, self.h = box_w, box_h
        self.t_pop, self.t_cut = float(intro["t_pop"]), float(intro["t_cut"])
        self.pop_s = float(intro.get("pop_s", 0.067))
        self.pts = float(intro.get("pop_text_scale", 1.084))
        self.zpre = float(intro.get("zoom_pre_per_s", 0.014))
        self.zpost = float(intro.get("zoom_post_per_s", 0.006))
        ref = float(intro.get("ref_box_h", 1028))
        self.r_end = float(intro.get("panel_h_end", 792)) / float(intro.get("panel_h_start", ref))
        self.panel = hex_rgb(intro.get("panel_color", "#FFFFFF"))
        s = box_h / ref
        self.s = s
        # 글자 크기는 상자 '폭' 기준(기준과 출력 모두 1080) — 높이 비율(0.79)로 줄이면 기준보다 글자가 절반쯤 작아 보인다
        sf = box_w / float(intro.get("ref_box_w", 1080))
        lines = [t for t in intro.get("lines", []) if t][:2]
        fonts = intro.get("font_regular")
        # 가장 크게 커졌을 때(튄 뒤 t_cut)도 좌우 여백 안에 들어오게 제목 글꼴을 줄인다
        zmax = (1 + self.zpre * self.t_pop) * self.pts * (1 + self.zpost * max(0.0, self.t_cut - self.t_pop))
        avail = (box_w - 2 * float(intro.get("side_margin_px", 40))) / zmax
        tsize = max(12, round(float(intro.get("title_px", 64)) * sf))
        label = str(intro.get("label", ""))
        # 머리줄 앞 아이콘(이모지 한 글자, 예: 🤣) — 머리줄을 '🤣 | 유머 • 정보 게시판 >' 꼴로 고정할 때 쓴다
        icon = str(intro.get("label_icon") or "")
        icon_k = float(intro.get("label_icon_scale", 34 / 30))       # 글자 약 30px 에 아이콘 약 34px
        hsize = max(10, round(float(intro.get("header_px", 30)) * sf))
        while tsize > 12 and max((_regular_font(tsize, fonts).getlength(t) for t in lines), default=0) > avail:
            tsize -= 1
        while hsize > 10 and _regular_font(hsize, fonts).getlength(label) + (hsize * (icon_k + 0.35) if icon else 0) > avail:
            hsize -= 1
        self.title_px, self.header_px = tsize, hsize
        tf, hf = _regular_font(round(tsize * SS), fonts), _regular_font(round(hsize * SS), fonts)
        # 줄 간격은 기준 비율(118/64 ≈ 1.84배)을 쓰되 우리 상자 높이에 들어가게 높이 비율로 상한
        gap = float(intro.get("line_gap_px", 118)) * (tsize / max(1.0, float(intro.get("title_px", 64))))
        gap = min(gap, float(intro.get("line_gap_px", 118)) * max(s, 0.9))
        y_h = float(intro.get("header_cy", -150)) * s
        y_1 = float(intro.get("title1_cy", -38.5)) * s
        ys = [y_1, y_1 + gap]
        icon_img = emoji_image(icon, round(hsize * icon_k * SS), intro.get("emoji_font")) if icon else None
        icon_w = (icon_img.width / SS + hsize * 0.35) if icon_img else 0.0      # 아이콘 + 빈칸
        widths = [tf.getlength(t) / SS for t in lines] + [hf.getlength(label) / SS + icon_w]
        gw = max(widths + [1.0])
        top, bottom = y_h - hsize * 0.7, (ys[len(lines) - 1] if lines else y_1) + tsize * 0.7
        self.cy_g = (top + bottom) / 2                     # 묶음 가운데(상자 가운데 기준 y)
        pad = int(8 * SS)
        gwp, ghp = int((gw + 16) * SS) + pad, int((bottom - top + 16) * SS) + pad
        img = Image.new("RGBA", (gwp, ghp), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        x0 = (gwp - gw * SS) / 2                           # 묶음 왼쪽(줄들은 왼쪽 정렬)
        gcy = ghp / 2
        hy = gcy + (y_h - self.cy_g) * SS
        if icon_img:
            img.alpha_composite(icon_img, (int(round(x0)), int(round(hy - icon_img.height / 2))))
        d.text((x0 + icon_w * SS, hy), label, font=hf, fill=hex_rgb(intro.get("header_color", "#6DB386")) + (255,),
               anchor="lm")
        for t, y in zip(lines, ys):
            d.text((x0, gcy + (y - self.cy_g) * SS), t, font=tf, fill=hex_rgb(intro.get("title_color", "#010101")) + (255,),
                   anchor="lm")
        self.group = img

    # --- 시간에 따른 값 (시험 대상) ---
    def pop_progress(self, t: float) -> float:
        return smoothstep((t - self.t_pop) / self.pop_s) if self.pop_s > 0 else float(t >= self.t_pop)

    def panel_height(self, t: float) -> int:
        e = self.pop_progress(t)
        return int(round(self.h * (1 - (1 - self.r_end) * e)))

    def text_scale(self, t: float) -> float:
        base = 1 + self.zpre * min(t, self.t_pop)
        if t <= self.t_pop:
            return base
        e = self.pop_progress(t)
        z = base * (1 + (self.pts - 1) * e)
        return z * (1 + self.zpost * max(0.0, t - self.t_pop - self.pop_s))

    def frame(self, t: float) -> Image.Image:
        """상자 크기 RGB 한 장."""
        img = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        ph = self.panel_height(t)
        y0 = (self.h - ph) // 2
        ImageDraw.Draw(img).rectangle((0, y0, self.w, y0 + ph - 1), fill=self.panel)
        z = self.text_scale(t) / SS
        g = self.group.resize((max(1, int(round(self.group.width * z))), max(1, int(round(self.group.height * z)))),
                              Image.LANCZOS)
        cx = self.w / 2
        cy = self.h / 2 + self.cy_g
        img.paste(g, (int(round(cx - g.width / 2)), int(round(cy - g.height / 2))), g)
        return img
