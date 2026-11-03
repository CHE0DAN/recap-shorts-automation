import json

import pytest

from recap_shorts.fx import intro as I
from recap_shorts.fx import sfx as S
from recap_shorts.render import compose as C
from recap_shorts.render.intro import IntroCard

CFG = {"intro": {"enabled": True, "style": "card", "pop_lead_s": 0.15, "pop_min_s": 0.6, "pop_before_cut_min_s": 0.5,
                 "pop_s": 0.067, "pop_text_scale": 1.084, "ref_box_h": 1028, "panel_h_start": 1028, "panel_h_end": 792,
                 "label_default": "출처"}}


def test_split_title_and_syllables():
    assert I.split_title("동네 빵집 주인은 어디서 밀가루를 살까?") == ["동네 빵집 주인은", "어디서 밀가루를 살까?"]
    assert I.split_title("한단어") == ["한단어", ""]
    assert I.count_syllables("가나 다") == 3


def test_build_intro_times():
    tl = {"fps": 30, "hook": {"text": "동네 빵집 주인은 어디서 밀가루를 살까?", "start": 0.0, "end": 2.7}}
    tm = {"sentences": [{"role": "hook", "text": tl["hook"]["text"], "start": 0.1, "end": 2.56}]}
    b = I.build_intro(tl, tm, CFG, voice_offset_s=0.2)
    assert b["t_cut"] == 2.7 and 0.6 <= b["t_pop"] <= 2.2 and b["t_pop"] == pytest.approx(1.233, abs=0.04)
    assert b["label"] == "출처" and len(b["lines"]) == 2
    assert I.build_intro(tl, tm, {"intro": {"enabled": False}}) is None


def test_card_motion():
    b = {**CFG["intro"], "lines": ["첫째 줄", "둘째 줄"], "label": "출처", "t_pop": 1.0, "t_cut": 2.7}
    card = IntroCard(b)
    assert card.panel_height(0.5) == 810 and card.panel_height(1.1) == round(810 * 792 / 1028)
    assert 0 < card.panel_height(1.033) < 810
    assert card.text_scale(0.0) == 1.0 and card.text_scale(1.0) == pytest.approx(1.014)
    assert card.text_scale(1.1) > 1.014 * 1.08
    assert card.frame(0.0).size == (1080, 810)


def test_composer_intro_hides_first_shot(tmp_path):
    from PIL import Image
    Image.new("RGB", (400, 300), (200, 0, 0)).save(tmp_path / "a.png")
    Image.new("RGB", (400, 300), (0, 0, 200)).save(tmp_path / "b.png")
    tl = {"fps": 30, "duration": 4.0, "title_lines": ["가", "나"], "hook": {"text": "가 나", "start": 0, "end": 2.0},
          "shots": [{"file": "a.png", "start": 0, "end": 2.0}, {"file": "b.png", "start": 2.0, "end": 4.0}],
          "captions": [], "intro": {**CFG["intro"], "lines": ["가", "나"], "label": "x", "t_pop": 1.0, "t_cut": 2.0}}
    comp = C.Composer(tl, str(tmp_path))
    im = comp.frame_image(15)
    assert im.getpixel((5, 465 + 5)) == (255, 255, 255)      # 카드 흰 판, 첫 샷(빨강)·훅 띠 없음
    assert comp.frame_image(60).getpixel((540, 800))[2] > 150  # t_cut 뒤 본문 샷


def test_hook_slots_and_ending(tmp_path):
    items = []
    for t, roles in [("hit", ["cut", "hook_open"]), ("whoosh_short", ["hook_pop"]), ("pop", ["cut", "hook_first_cut"]),
                     ("whoosh", ["cut"])]:
        (tmp_path / f"{t}.wav").write_bytes(b"x")
        items.append({"id": t + "_01", "file": f"{t}.wav", "type": t, "roles": roles, "duration": 0.3})
    (tmp_path / "manifest.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    lib, _ = S.load_library([tmp_path])
    tl = {"duration": 20.0, "shots": [{"start": 0, "end": 2.7}, {"start": 2.7, "end": 20}],
          "hook": {"start": 0, "end": 2.7}, "intro": {"t_pop": 1.4, "t_cut": 2.7}}
    cfg = {"min_gap_s": 0.5, "cuts": {"mode": "none"}, "types_db": {"pop": -15, "whoosh_short": -1},
           "hook": {"enabled": True, "open": {"type": "hit", "t": 0.06, "db": -3},
                    "pop": {"type": "whoosh_short", "offset_s": 0.06, "db": -8},
                    "first_cut": {"type": "pop", "offset_s": 0.02, "db": -15}},
           "ending": {"types": {"whoosh": 1.0}, "len_s": 0.4, "db": -18, "at_end_s": 1.1}}
    ev = S.place_sfx(tl, [], [], lib, cfg)["events"]
    assert [(e["why"], e.get("slot"), e["t"], e["db"]) for e in ev] == [
        ("hook", "open", 0.06, -3.0), ("hook", "pop", 1.46, -8.0), ("hook", "first_cut", 2.72, -15.0),
        ("ending", None, 18.9, -18.0)]
    assert ev[-1]["len_s"] == 0.4
    # 자리마다 enabled false 로 끌 수 있다(첫 컷 '톡'·끝 '휙')
    off = {**cfg, "hook": {**cfg["hook"], "first_cut": {**cfg["hook"]["first_cut"], "enabled": False}},
           "ending": {**cfg["ending"], "enabled": False}}
    ev = S.place_sfx(tl, [], [], lib, off)["events"]
    assert [(e["why"], e.get("slot")) for e in ev] == [("hook", "open"), ("hook", "pop")]


def test_fixed_label_and_emoji_icon(tmp_path):
    """label_fixed 가 있으면 모든 영상의 머리줄이 같은 꼴('🤣 | 유머 • 정보 게시판 >')이 된다."""
    import numpy as np
    from recap_shorts.render import intro as RI
    tl = {"fps": 30, "hook": {"text": "붓꽃과 수선화가 다른 꽃이라는 거 알아?", "start": 0.0, "end": 2.6}}
    tm = {"sentences": [{"role": "hook", "text": tl["hook"]["text"], "start": 0.1, "end": 2.5}]}
    cfg = {"intro": {**CFG["intro"], "label_fixed": "| 유머 • 정보 게시판 >", "label_icon": "🤣"}}
    b = I.build_intro(tl, tm, cfg, job_dir=tmp_path)
    assert b["label"] == "| 유머 • 정보 게시판 >" and b["label_icon"] == "🤣" and "label_fixed" not in b
    with_icon = np.asarray(IntroCard(b).frame(2.0).convert("RGB"), dtype=int)
    without = np.asarray(IntroCard({**b, "label_icon": ""}).frame(2.0).convert("RGB"), dtype=int)
    if RI.emoji_image("🤣", 34) is not None:            # 이모지 글꼴이 있는 PC: 노란 아이콘이 생기고 글자는 오른쪽으로
        yellow = (with_icon[..., 0] > 200) & (with_icon[..., 1] > 150) & (with_icon[..., 2] < 90)
        assert yellow.sum() > 200 and not np.array_equal(with_icon, without)


def test_intro_stays_when_fx_off_or_fails(tmp_path, monkeypatch):
    # 인트로 화면 고정 — 짤·효과음을 끄거나 그 단계가 실패해도 인트로는 붙는다
    from recap_shorts.fx import apply as A
    tl = {"fps": 30, "duration": 4.0, "hook": {"text": "교실 창문이 늘 왼쪽에 있는 진짜 이유", "start": 0.0, "end": 2.9},
          "shots": [], "captions": [], "audio": {}}
    tm = {"sentences": [{"index": 0, "role": "hook", "text": tl["hook"]["text"], "start": 0.1, "end": 2.8}]}
    cfg = tmp_path / "fx.json"
    cfg.write_text(json.dumps({"enabled": True, "intro": {**CFG["intro"], "label_fixed": "| 유머 • 정보 게시판 >"}}), encoding="utf-8")
    off = A.maybe_apply(tmp_path, tl, tm, {"fx": False}, config_path=cfg)
    assert off["intro"]["label"] == "| 유머 • 정보 게시판 >" and off["intro"]["t_cut"] == 2.9 and "intro" not in tl

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(A, "apply_fx", boom)
    failed = A.maybe_apply(tmp_path, tl, tm, None, config_path=cfg)
    assert "error" in failed["fx"] and failed["intro"]["lines"] == I.split_title(tl["hook"]["text"])


def test_intro_lines_follow_title_when_hook_is_title():
    tm = {"sentences": [{"role": "hook", "text": "x", "start": 0.1, "end": 2.6}]}
    tl = {"fps": 30, "title_lines": ["교실 창문이 늘", "왼쪽에 있는 진짜 이유"],
          "hook": {"text": "교실 창문이 늘 왼쪽에 있는 진짜 이유", "start": 0.0, "end": 2.7}}
    assert I.build_intro(tl, tm, CFG)["lines"] == ["교실 창문이 늘", "왼쪽에 있는 진짜 이유"]
    tl["hook"]["text"] = "붓꽃과 수선화가 다른 꽃이라는 거 알아?"     # 훅이 제목과 다르면 가운데에서 나눔
    assert I.build_intro(tl, tm, CFG)["lines"] == I.split_title(tl["hook"]["text"])
