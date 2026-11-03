"""게시글 첨부 그림 → 4:3 캡처 카드. 세로로 긴 그림은 빈 줄(여백)에서 내용 단위로 2~3조각으로 자른다.

영상 캡처 수십 장을 회색 줄로 이어 붙인 '칸 쌓기' 그림(697×27522)은 조각내면 읽을 수 없는 가는 띠가 되어
`panel_boxes` 로 칸을 먼저 알아낸다(주제에 맞는 칸만 골라 쓰기). 칸 쌓기가 아니면 None.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from recap_shorts.render.cards import make_card

TALL_RATIO = 1.25     # 높이/너비가 이 이상이면 조각으로 나눔
PIECE_RATIO = 0.95    # 조각 하나의 목표 높이/너비
MAX_PIECES = 3


def piece_count(w: int, h: int) -> int:
    if h <= TALL_RATIO * w:
        return 1
    return max(2, min(MAX_PIECES, round(h / (PIECE_RATIO * w))))


def split_points(im: Image.Image, n: int, window: float = 0.12) -> list[int]:
    """[0, c1, ..., h]. 이상적 경계(k*h/n) 근처 ±window*h 안에서 가장 '빈'(밝기 변화 적은) 줄을 고른다."""
    h = im.height
    if n <= 1:
        return [0, h]
    g = np.asarray(im.convert("L"), dtype=np.float32)
    row_std = g.std(axis=1)
    k = 7
    smooth = np.convolve(row_std, np.ones(k) / k, mode="same")
    pts = [0]
    for i in range(1, n):
        ideal = int(h * i / n)
        lo, hi = max(pts[-1] + 40, int(ideal - window * h)), min(h - 40, int(ideal + window * h))
        if lo >= hi:
            pts.append(ideal)
            continue
        seg = smooth[lo:hi]
        flat = np.nonzero(seg <= seg.min() + 1.0)[0]            # 가장 빈 줄들 중 이상적 경계에 가장 가까운 줄
        pts.append(int(lo + flat[np.argmin(np.abs(lo + flat - ideal))]))
    pts.append(h)
    return pts


def pieces_of(path: str | Path, n: int | None = None) -> list[tuple[int, int, int, int]]:
    """원본 좌표의 자르기 상자 목록."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        n = n or piece_count(im.width, im.height)
        pts = split_points(im, n)
    with Image.open(path) as im:
        w = im.width
    return [(0, a, w, b) for a, b in zip(pts[:-1], pts[1:])]


def make_cards_for_image(src: str | Path, out_dir: str | Path, prefix: str,
                         blur_boxes: list[tuple[int, int, int, int]] | None = None) -> list[dict]:
    """그림 하나 → 카드 1~3장. 반환: [{"file","src","crop","blur_boxes","kind":"cap"}]. label 은 None(화면에 출처 줄 없음)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from recap_shorts.images.regions import snap_crop
    with Image.open(src) as im:
        im = im.convert("RGB")
        size = im.size
        boxes = [snap_crop(im, b) for b in pieces_of(src)]     # 조각 끝이 글줄 가운데면 줄 사이로, 원본에서 잘린 끝 줄은 뺌
    cards = []
    for j, crop in enumerate(boxes):
        name = f"{prefix}.png" if len(boxes) == 1 else f"{prefix}_p{j + 1}.png"
        out = out_dir / name
        full = crop == (0, 0, *size)
        info = make_card(src, out, crop=None if full else crop, blur_boxes=blur_boxes or [], label=None)
        info["kind"] = "cap"
        cards.append(info)
    return cards


def panel_boxes(path: str | Path, *, min_panels: int = 4) -> list[tuple[int, int, int, int]] | None:
    """'칸 쌓기' 그림(같은 회색 줄로 갈라진 장면 여러 장을 세로로 이은 그림) → 칸 상자 [(0,y0,w,y1) ...], 아니면 None.

    갈라 주는 줄: 가로 전체가 거의 한 색(밝기 표준편차 < 4)인 줄이 6px 이상 이어진 것 + 줄마다 밝기가 비슷할 것.
    너비의 0.2배보다 낮은 토막은 버린다. 댓글 목록처럼 빈칸이 잦은 그림은 토막이 짧아 칸이 모자라거나
    버려진 토막이 많아 None 이 된다."""
    with Image.open(path) as im:
        w, h = im.size
        if h <= 1.6 * w or w < 40:
            return None
        g = np.asarray(im.convert("L"), dtype=np.float32)
    flat = g.std(axis=1) < 4.0
    mean = g.mean(axis=1)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], flat.astype(np.int8), [0]))))
    runs = [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2]) if b - a >= 6]   # 납작한 줄 구간 [a, b)
    if len(runs) < min_panels - 1:
        return None
    means = np.array([mean[a:b].mean() for a, b in runs])
    mode = np.median(means)
    keep = [r for r, m in zip(runs, means) if abs(m - mode) <= 12]     # 줄마다 밝기가 비슷한 것만
    if len(keep) < min_panels - 1:
        return None
    spans, prev = [], 0
    for a, b in keep:
        spans.append((prev, a))
        prev = b
    spans.append((prev, h))
    spans = [s for s in spans if s[1] > s[0]]
    good = [s for s in spans if s[1] - s[0] >= 0.2 * w]
    if len(good) < min_panels:
        return None
    if sum(b - a for a, b in good) < 0.6 * sum(b - a for a, b in spans):   # 짧은 토막이 많으면 칸 쌓기가 아님(댓글 목록)
        return None
    return [(0, a, w, b) for a, b in good]
