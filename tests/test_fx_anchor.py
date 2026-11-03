from recap_shorts.fx.apply import away_from_focus

SHOTS = [{"start": 0.0, "end": 2.0, "focus": [0.8, 0.7]},
         {"start": 2.0, "end": 4.0, "focus": [0.2, 0.9]},
         {"start": 4.0, "end": 6.0}]


def test_sticker_goes_to_the_corner_away_from_focus():
    two = ["box_br", "box_bl"]
    assert away_from_focus(SHOTS, {"start": 1.0}, two) == "box_bl"      # 대상이 오른쪽 아래
    assert away_from_focus(SHOTS, {"start": 2.5}, two) == "box_br"      # 대상이 왼쪽 아래
    assert away_from_focus(SHOTS, {"start": 4.5}, two) == "box_br"      # focus 없음 → 첫 자리
    four = ["box_br", "box_bl", "box_tr", "box_tl"]
    assert away_from_focus(SHOTS, {"start": 1.0}, four) == "box_tl"
    assert away_from_focus([], {"start": 1.0}, ["nope"]) == "box_br"


def test_fit_before_meme_respreads_and_drops_ai_first():
    from recap_shorts.fx.apply import fit_before_meme
    sents = [{"index": 0, "role": "hook", "start": 0.0}, {"index": 1, "role": "body", "start": 2.0},
             {"index": 2, "role": "body", "start": 5.0}]
    shots = [{"file": "w/assets/cap/dc_head.png", "start": 0.0, "end": 2.0},
             {"file": "w/assets/cap/c01.png", "start": 2.0, "end": 3.0},
             {"file": "w/assets/cap/c01_s01.png", "start": 3.0, "end": 4.0},
             {"file": "w/assets/ai/ai_01.png", "start": 4.0, "end": 5.0},
             {"file": "w/assets/cap/c02.png", "start": 5.0, "end": 7.0}]
    meme = {"kind": "meme", "file": "m.png", "start": 3.4, "end": 5.0}
    out = fit_before_meme(shots, sents, meme, min_len=0.9)
    names = [s["file"].split("/")[-1] for s in out]
    assert names == ["dc_head.png", "c01.png", "m.png", "c02.png"]      # 1.4초에 2컷이면 0.7초 → AI, 잘라 낸 캡처 순으로 뺌
    assert out[1]["start"] == 2.0 and out[1]["end"] == 3.4 and out[2]["start"] == 3.4
    loose = fit_before_meme(shots, sents, {**meme, "start": 4.2}, min_len=0.7)
    # 2.2초에 3컷 = 0.73초 ≥ 0.7 → 셋 다 남는다
    assert [s["file"].split("/")[-1] for s in loose] == ["dc_head.png", "c01.png", "c01_s01.png", "ai_01.png", "m.png", "c02.png"]


def test_sfx_chooser_prefers_role_and_fixed_mode():
    from recap_shorts.fx.sfx import _Chooser
    lib = [{"id": "d1", "type": "ding", "duration": 0.5}, {"id": "d2", "type": "ding", "duration": 0.5, "role": "hook"},
           {"id": "d3", "type": "ding", "duration": 0.4, "roles": ["cut"]}, {"id": "d4", "type": "ding", "duration": 0.6, "roles": ["cut"]}]
    ch = _Chooser(lib)
    assert ch.get("ding", role="hook")["id"] == "d2"
    assert [ch.get("ding", role="cut")["id"] for _ in range(3)] == ["d3", "d4", "d3"]
    assert ch.get("ding", role="meme_pop")["id"] in {"d1", "d2", "d3", "d4"}      # 그 자리용이 없으면 아무거나
    fx = _Chooser(lib, "fixed")
    assert {fx.get("ding", role="cut")["id"] for _ in range(3)} == {"d3"}
