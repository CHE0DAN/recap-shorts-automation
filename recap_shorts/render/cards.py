"""캡처·세로 그림을 이미지 상자(1080×810, 4:3)에 맞는 '카드'로 만든다.

이미지 상자는 cover 맞춤(꽉 채워 자르기)이라, 세로로 긴 캡처나 작은 글 카드를 그대로 넣으면 크게 잘리거나 흐릿하게 늘어난다.
그래서 (1) 같은 그림을 흐리고 어둡게 깔아 바탕을 만들고, (2) 그 위에 원본을 잘리지 않게 넣고(fit), (3) 아래에 작게 출처를 적는다.
가림(blur_boxes)은 원본 좌표로 받아 카드에 넣기 전에 처리한다 — 얼굴·아이디 같은 것을 확실히 지우기 위해 모자이크를 쓴다.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .layout import IMAGE_H as BOX_H, IMAGE_W as BOX_W

FONT = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Pretendard-ExtraBold.otf"


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def _mosaic(im: Image.Image, box: tuple[int, int, int, int], cell: int = 18) -> None:
    x0, y0, x1, y1 = box
    region = im.crop(box)
    w, h = region.size
    small = region.resize((max(1, w // cell), max(1, h // cell)), Image.BILINEAR)
    im.paste(small.resize((w, h), Image.NEAREST), (x0, y0))


def make_card(src: str | Path, out: str | Path, crop: tuple[int, int, int, int] | None = None,
              blur_boxes: list[tuple[int, int, int, int]] | None = None, label: str | None = None,
              margin: int = 36, max_upscale: float = 2.2,
              highlight: tuple[int, int, int, int] | None = None, backdrop=None) -> dict:
    """highlight: 원본 좌표의 상자 — 둘레를 빨간 테두리로 강조(앞뒤 줄을 같이 보여 줄 때 어느 줄인지 표시).
    backdrop: 바탕으로 흐려 깔 그림(경로·PIL) — 작은 글줄 띠는 제 글자를 크게 흐리면 어색해서 주변 화면을 깐다."""
    im = Image.open(src).convert("RGB")
    for b in blur_boxes or []:
        _mosaic(im, b)
    if highlight:                                   # 원본 좌표에 그린 뒤 자른다
        width = max(3, round(min((crop[2] - crop[0]) if crop else im.width, 900) / 160))
        ImageDraw.Draw(im).rounded_rectangle(highlight, radius=width * 2, outline=(255, 59, 48), width=width)
    if crop:
        im = im.crop(crop)
    # 바탕: cover 맞춤 후 크게 흐리고 어둡게
    bw, bh = BOX_W, BOX_H
    base = im
    if backdrop is not None:
        base = (Image.open(backdrop) if isinstance(backdrop, (str, Path)) else backdrop).convert("RGB")
    s = max(bw / base.width, bh / base.height)
    bg = base.resize((int(base.width * s) + 1, int(base.height * s) + 1), Image.LANCZOS)
    bg = bg.crop(((bg.width - bw) // 2, (bg.height - bh) // 2, (bg.width - bw) // 2 + bw, (bg.height - bh) // 2 + bh))
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)), 0.55)
    # 앞: 잘리지 않게 fit, 너무 작은 것은 max_upscale 까지만 키움
    label_h = 44 if label else 0
    aw, ah = bw - 2 * margin, bh - 2 * margin - label_h
    f = min(aw / im.width, ah / im.height, max_upscale)
    fg = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
    x = (bw - fg.width) // 2
    y = margin + (ah - fg.height) // 2
    shadow = Image.new("RGBA", (fg.width + 24, fg.height + 24), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((12, 12, fg.width + 12, fg.height + 12), radius=18, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    card = bg.convert("RGBA")
    card.alpha_composite(shadow, (x - 12, y - 6))
    mask = Image.new("L", fg.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fg.width - 1, fg.height - 1), radius=14, fill=255)
    card.paste(fg, (x, y), mask)
    if label:
        d = ImageDraw.Draw(card)
        font = _font(24)
        d.text((margin, bh - margin - 26), label, font=font, fill=(235, 235, 235, 255))
    card.convert("RGB").save(out)
    return {"file": str(out), "src": str(src), "crop": crop, "blur_boxes": blur_boxes or [], "scale": round(f, 3), "label": label}
