import os

import pytest
from PIL import Image

from recap_shorts.render import compose as C
from recap_shorts.render import layout as L


def test_pixel_bounds():
    assert (L.W, L.H) == (1080, 1920)
    assert L.TITLE_Y0 == 0 and L.TITLE_Y1 == 465
    assert (L.IMAGE_Y0, L.IMAGE_Y1) == (465, 1275)
    assert L.IMAGE_Y1 - L.IMAGE_Y0 == 810
    assert (L.CAPTION_Y0, L.CAPTION_Y1) == (1275, 1455)
    assert L.CAPTION_MAX_PX == 1535
    assert L.BLANK_Y0 == 1455


def test_cover_box_ratio_and_focus():
    b = C.cover_box(1920, 1080, (0.5, 0.5))
    assert (b[2] - b[0], b[3] - b[1]) == (1440, 1080)
    assert b[0] == 240
    left = C.cover_box(1920, 1080, (0.0, 0.5))
    right = C.cover_box(1920, 1080, (1.0, 0.5))
    assert left[0] == 0 and right[2] == 1920
    t = C.cover_box(1200, 1600, (0.5, 0.0))
    assert (t[2] - t[0], t[3] - t[1]) == (1200, 900) and t[1] == 0
    s = C.cover_box(1000, 1000, (0.5, 1.0))
    assert s[3] == 1000 and (s[2] - s[0]) == 1000


def test_zoom_and_enter_params():
    assert C.zoom_scale(0, 0, 2.6) == 1.0
    assert C.zoom_scale(2.6, 0, 2.6) == pytest.approx(1.08)
    assert C.zoom_scale(1.3, 0, 2.6) == pytest.approx(1.04)
    assert C.enter_params(0) == (6.0, 24.0, 0.0)
    assert C.enter_params(0.2) == (0.0, 0.0, 1.0)


def test_snap_captions():
    caps = [{"text": "a", "start": 2.67, "end": 4.0}, {"text": "b", "start": 4.0, "end": 5.4}]
    out = C.snap_captions_to_cuts(caps, [2.67, 4.07, 5.37])
    assert out[0]["end"] == 4.07 and out[1]["start"] == 4.07 and out[1]["end"] == 5.37


def test_fixed_layer_and_overlays():
    fx = C.make_fixed_layer(["테스트 제목 1줄", "노란 2줄"])
    assert fx.size == (1080, 1920)
    px = fx.load()
    # 제목 띠 안에 흰/노란 글자, 띠 밖은 검정
    seen = {px[x, y] for y in range(0, 465, 3) for x in range(0, 1080, 3)}
    assert (255, 255, 255) in seen and (255, 212, 0) in seen
    assert all(px[x, y] == (0, 0, 0) for y in range(465, 1920, 7) for x in range(0, 1080, 7))
    ov = C.make_caption_overlay("알고 보니 포수가 장난으로", "포수가")
    bbox = ov.getchannel("A").getbbox()
    assert bbox and bbox[1] >= L.CAPTION_Y0 and bbox[3] <= L.CAPTION_Y1
    assert bbox[0] >= L.SIDE_MARGIN - 8 and bbox[2] <= L.W - L.SIDE_MARGIN + 8
    hk = C.make_hook_overlay("야구 갤러리가 발칵 뒤집힌 사연")
    hb = hk.getchannel("A").getbbox()
    assert hb[0] == L.HOOK_MARGIN_X and hb[2] in (L.W - L.HOOK_MARGIN_X, L.W - L.HOOK_MARGIN_X + 1)
    assert hb[3] - hb[1] <= L.HOOK_H + 1
