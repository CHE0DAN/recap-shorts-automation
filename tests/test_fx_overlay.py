import json
import os
import shutil

from PIL import Image

from recap_shorts.render import layout as L
from recap_shorts.render import overlays as OV
from recap_shorts.render.compose import Composer

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "render")


def ov(**kw):
    d = {"kind": "sticker", "file": "s.png", "start": 2.0, "end": 3.5, "anchor": "box_br", "size_frac": 0.38,
         "anim": "pop", "pop_s": 0.2, "overshoot": 1.15, "fade_s": 0.1, "shake_px": 10.0}
    d.update(kw)
    return d


def test_pop_scale_curve():
    assert OV.pop_scale(0.0, 0.2, 1.15) == 0.0
    vals = [OV.pop_scale(i * 0.01, 0.2, 1.15) for i in range(0, 21)]
    assert max(vals) > 1.1 and max(vals) <= 1.15 + 1e-9  # 작은 오버슈트
    assert abs(vals[-1] - 1.0) < 1e-9 and OV.pop_scale(5.0, 0.2, 1.15) == 1.0
    assert vals[1] < vals[3]  # 처음엔 커지는 중


def test_state_window_and_fade():
    o = ov()
    assert OV.overlay_state(o, 1.99) is None and OV.overlay_state(o, 3.5) is None
    mid = OV.overlay_state(o, 2.8)
    assert mid["scale"] == 1.0 and mid["alpha"] == 1.0 and mid["dx"] == 0.0
    end = OV.overlay_state(o, 3.45)
    assert 0.0 < end["alpha"] < 1.0  # 끝에서 서서히 사라짐
    assert OV.overlay_state(o, 2.02)["scale"] < 1.0


def test_shake_and_slide_up():
    sh = OV.overlay_state(ov(anim="shake"), 2.3)
    assert abs(sh["dx"]) > 0 and abs(sh["dx"]) <= 10.0
    assert OV.is_animating(ov(anim="shake"), 3.0) and not OV.is_animating(ov(), 3.0)
    su0, su1 = OV.overlay_state(ov(anim="slide_up"), 2.01), OV.overlay_state(ov(anim="slide_up"), 2.6)
    assert su0["dy"] > 100 and su1["dy"] == 0.0


def test_anchor_inside_box_and_size_cap():
    for a in OV.ANCHORS:
        x, y = OV.anchor_xy(a, 300, 300, 24)
        assert 0 <= x and x + 300 <= L.IMAGE_W and 0 <= y and y + 300 <= L.IMAGE_H
    assert OV.anchor_xy("box_br", 300, 300, 24) == (L.IMAGE_W - 324, L.IMAGE_H - 324)
    w, h = OV.rest_size(100, 100, 0.38)
    assert w == round(0.38 * L.IMAGE_W) == h
    w, h = OV.rest_size(100, 1000, 0.38)  # 세로로 긴 그림은 높이 한계로 줄어든다
    assert h <= 0.62 * L.IMAGE_H + 1 and abs(w / h - 0.1) < 0.01


def _tl(tmp_path, overlays, shots_extra=None):
    with open(os.path.join(FIX, "sample_timeline.json"), encoding="utf-8") as f:
        tl = json.load(f)
    shutil.copytree(os.path.join(FIX, "images"), tmp_path / "images", dirs_exist_ok=True)
    Image.new("RGBA", (200, 200), (255, 0, 255, 255)).save(tmp_path / "s.png")
    tl["overlays"] = overlays
    if shots_extra:
        tl["shots"] = shots_extra
    return tl


def test_composer_draws_sticker_only_inside_window(tmp_path):
    base = Composer(_tl(tmp_path, []), str(tmp_path))
    c = Composer(_tl(tmp_path, [ov(file=str(tmp_path / "s.png"), start=5.0, end=6.0)]), str(tmp_path))
    f_in = c.frame_image(int(5.5 * 30))
    f_base = base.frame_image(int(5.5 * 30))
    assert f_in.tobytes() != f_base.tobytes()
    # 스티커는 이미지 상자 오른쪽 아래, 자막 띠(상자 아래)는 그대로
    cap = (0, L.CAPTION_Y0, L.W, L.CAPTION_Y1)
    assert f_in.crop(cap).tobytes() == f_base.crop(cap).tobytes()
    px = f_in.getpixel((L.W - 24 - 190, L.IMAGE_Y1 - 24 - 190))
    assert px[0] > 200 and px[1] < 80 and px[2] > 200  # 분홍 스티커 중앙
    assert c.frame_image(int(7.0 * 30)).tobytes() == base.frame_image(int(7.0 * 30)).tobytes()


def test_frame_key_reuses_static_frames(tmp_path):
    c = Composer(_tl(tmp_path, [ov(file=str(tmp_path / "s.png"), start=5.0, end=6.0)]), str(tmp_path))
    k1, k2 = c.frame_key(int(5.6 * 30)), c.frame_key(int(5.7 * 30))
    assert k1 == k2  # 가만히 있는 구간은 같은 키 -> 앞 프레임 재사용
    assert c.frame_key(int(5.02 * 30)) != c.frame_key(int(5.05 * 30))  # 등장 중에는 프레임마다 다름


def test_full_shot_meme_is_a_normal_shot(tmp_path):
    with open(os.path.join(FIX, "sample_timeline.json"), encoding="utf-8") as f:
        tl = json.load(f)
    Image.new("RGBA", (200, 100), (255, 0, 255, 255)).save(tmp_path / "m.png")
    shutil.copytree(os.path.join(FIX, "images"), tmp_path / "images")
    from recap_shorts.fx.memes import insert_shot
    tl["shots"] = insert_shot(tl["shots"], {"file": str(tmp_path / "m.png"), "kind": "meme", "start": 10.0, "end": 11.2,
                                            "motion": "static", "bg": [20, 20, 20], "anim": "pop", "fit": "contain"})
    c = Composer(tl, str(tmp_path))
    fr = c.frame_image(int(10.8 * 30))
    assert fr.getpixel((L.W // 2, L.IMAGE_Y0 + L.IMAGE_H // 2))[:3] == (255, 0, 255)
    assert fr.getpixel((5, L.IMAGE_Y0 + 5))[:3] == (20, 20, 20)  # 배경(contain-fit 이라 가장자리는 단색)
    small = c.frame_image(int(10.02 * 30))
    assert small.getpixel((L.W // 2, L.IMAGE_Y0 + L.IMAGE_H // 2))[:3] in ((255, 0, 255), (20, 20, 20))
