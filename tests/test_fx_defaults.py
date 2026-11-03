"""효과음·짤(밈) 기본값과 배치 규칙이 기대대로인지 (tests/test_fx_*.py 묶음)."""
import array
import json
import math
import os
import re
import struct
import wave

import pytest
from PIL import Image

from recap_shorts.fx import apply as A
from recap_shorts.fx import memes as M
from recap_shorts.fx import sfx as S
from recap_shorts.fx.config import load_config
from recap_shorts.render import audio
from recap_shorts.render import overlays as OV

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "render")


def write_wav(path, dur=0.3, freq=441.0, amp=0.9, sr=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / sr)))
                               for i in range(int(sr * dur))))


def make_lib(tmp_path, specs):
    items = []
    for id_, beats in specs:
        Image.new("RGBA", (64, 64), (0, 200, 0, 128)).save(tmp_path / f"{id_}.png")
        items.append({"id": id_, "file": f"{id_}.png", "family": "pepe", "beats": beats, "transparent": True})
    (tmp_path / "manifest.json").write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")
    return M.load_library(tmp_path)[0]


def sents(beats, step=3.0):
    return [{"index": i, "role": "hook" if i == 0 else "body", "text": f"문장{i}", "start": i * step,
             "end": (i + 1) * step - 0.1, "beat": b} for i, b in enumerate(beats)]


def sfx_lib(tmp_path, types, dur=None):
    d = tmp_path / "sfxlib"
    d.mkdir(exist_ok=True)
    items = []
    for t in types:
        write_wav(d / f"{t}_1.wav", 0.2)
        items.append({"id": f"{t}_1", "file": f"{t}_1.wav", "type": t, "duration": (dur or {}).get(t, 0.2)})
    (d / "manifest.json").write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")
    return d


def timeline(n=10, step=2.0):
    return {"duration": n * step, "shots": [{"file": "x", "start": i * step, "end": (i + 1) * step, "motion": "static"}
                                            for i in range(n)], "hook": {"text": "t", "start": 0.0, "end": step}}


MCFG = {"max_per_video": 4, "min_gap_s": 3.0, "allowed_beats": ["shock", "neutral", "conclusion"], "beat_priority": ["shock"],
        "on_hook": False, "prefer_transparent": True, "full_shot_ratio": 1.0, "full_shot_len_s": 1.6,
        "sticker": {"anchors": ["box_br"]}}


# ---------- 짤 ----------

def test_default_config_values():
    cfg = load_config()
    m = cfg["memes"]
    # 짤은 흰 바탕 상자 가득, 1.2초, 끝 짤 없음(측정 규격)
    assert m["full_shot_ratio"] == 1.0 and m["full_shot_anim"] == "none" and m["full_shot_bg"] == [255, 255, 255]
    assert m["library"] == "assets_local/memes_r" and m["full_shot_len_s"] == 1.2 and not m["end_with_meme"]
    assert m["first_after_s"] == 3.0 and "conclusion" not in m["allowed_beats"] and m["beat_priority"][0] == "question"
    assert cfg["timing"]["picture_lead_s"] == 0.2
    # 효과음 규칙(R1~R12)
    sx = cfg["sfx"]
    # 최근 영상 기준으로 줄임(10초당 2.3개, 컷 60% 건너뜀, 크기 −2dB)
    # 그림과 동시(+0.03), 44%에만, 간격 0.5, 같은 소리 4번
    assert sx["types_db"]["boom"] == -15 and sx["min_gap_s"] == 0.5 and sx["max_per_10s"] == 2.3
    assert sx["cuts"]["offset_s"] == 0.03 and sx["cuts"]["skip_ratio"] == 0.56 and sx["max_same_file"] == 4
    assert sx["place_on"] == "none" and "boing" not in sx["cuts"]["types"] and sx["ending"]["at_end_s"] == 1.1
    assert set(sx["hook"]) >= {"open", "pop", "first_cut"}
    # 끝 '휙'은 꺼 두고, 첫 컷 '톡'은 켜 둔다
    assert sx["hook"]["first_cut"].get("enabled", True) is True and sx["ending"]["enabled"] is False
    # 휙 소리는 컷 효과음 종류에서 빼고, 카드 튐 자리는 끈다
    assert "whoosh" not in sx["cuts"]["types"] and sx["hook"]["pop"]["enabled"] is False
    # pick_by 'fit': 문장과 짤 뜻을 같이 보고 고름
    assert cfg["memes"]["pick_by"] == "fit"
    # 짤은 40초 이하 2개, 페페 계열 1개 / 효과음은 직접 모은 CC0 꾸러미에서 고른 것 먼저
    assert M.max_for_length(m, 34.9) == 2 and m["max_per_family"] == {"pepe": 1} and m["family_alias"]["apu"] == "pepe"
    # 저장소에 같이 든 밈 효과음·차임 꾸러미(설정 화면에서 폴더를 고르면 그쪽이 먼저)
    assert cfg["sfx"]["libraries"] == ["assets/sfx_packs/user_meme", "assets/sfx_packs/chime"]
    assert cfg["sfx"]["fallback_libraries"] == []


def test_max_for_length():
    cfg = {"max_per_video": 4, "max_by_length": [[40, 4], [50, 5]], "max_cap": 6}
    assert [M.max_for_length(cfg, d) for d in (20, 40, 41, 50, 60, None)] == [4, 4, 5, 5, 6, 4]


def test_first_after_and_full_shot_len_clamp(tmp_path):
    lib = make_lib(tmp_path, [(f"s{i}", ["shock"]) for i in range(6)])
    ss = sents(["neutral"] + ["shock"] * 8)
    cfg = {**MCFG, "first_after_s": 6.0, "full_shot_len_s": 9.0, "full_shot_max_s": 2.5, "max_per_video": 6}
    ev = M.pick_memes(ss, lib, cfg)["events"]
    assert ev and min(e["start"] for e in ev) >= 6.0
    assert all(e["mode"] == "shot" and e["end"] - e["start"] <= 2.5 + 1e-9 for e in ev)
    short = M.pick_memes(sents(["neutral", "shock"], step=1.2), lib, {**cfg, "first_after_s": 0, "position": "start"})["events"]
    assert short and short[0]["end"] <= 2.3 + 1e-9  # 문장 끝을 넘지 않음


def test_end_with_meme_uses_conclusion_and_counts(tmp_path):
    lib = make_lib(tmp_path, [("c1", ["conclusion"])] + [(f"s{i}", ["shock"]) for i in range(4)])
    ss = sents(["neutral"] + ["shock"] * 8, step=4.0)
    cfg = {**MCFG, "end_with_meme": True, "first_after_s": 6.0, "max_per_video": 3}
    ev = M.pick_memes(ss, lib, cfg)["events"]
    assert len(ev) == 3  # 끝 짤도 개수에 포함
    assert ev[-1]["meme_id"] == "c1" and ev[-1]["beat"] == "conclusion" and ev[-1]["sentence"] == 8
    none = M.pick_memes(ss, [i for i in lib if i["id"] != "c1"], cfg)
    assert any("끝 짤" in n for n in none["notes"]) and len(none["events"]) == 3


def test_shot_anim_none_carried_to_shot():
    cfg = load_config()["memes"]
    sh = M.to_shot({"beat": "smug", "start": 7.0, "end": 8.6, "meme_id": "x", "file": "/a.png"}, cfg)
    assert sh["anim"] == "none" and sh["bg"] == [255, 255, 255] and sh["fit"] == "cover"
    assert sh["fit_focus_y"] == 0.35 and sh["margin"] == 0


def test_overlay_anim_none_is_a_hard_cut():
    ov = {"start": 2.0, "end": 3.0, "anim": "none"}
    assert OV.overlay_state(ov, 2.0) == {"scale": 1.0, "dx": 0.0, "dy": 0.0, "alpha": 1.0}
    assert OV.overlay_state(ov, 2.99)["alpha"] == 1.0 and not OV.is_animating(ov, 2.5)


def test_meme_shot_fit_square_height_and_wide_cover(tmp_path):
    from recap_shorts.render import layout as L
    from recap_shorts.render.compose import Composer
    Image.new("RGBA", (300, 300), (255, 0, 0, 255)).save(tmp_path / "sq.png")
    Image.new("RGBA", (400, 200), (0, 0, 255, 255)).save(tmp_path / "wide.png")
    Image.new("RGB", (50, 50), (9, 9, 9)).save(tmp_path / "bg.png")
    base = {"kind": "meme", "motion": "static", "bg": [0, 0, 0], "anim": "none", "focus": [0.5, 0.5]}
    tl = {"fps": 30, "duration": 4.0, "title_lines": ["a", "b"], "captions": [],
          "shots": [{**base, "file": str(tmp_path / "sq.png"), "start": 0.0, "end": 2.0},
                    {**base, "file": str(tmp_path / "wide.png"), "start": 2.0, "end": 4.0}]}
    c = Composer(tl, str(tmp_path))
    f = c.frame_image(15)
    y = L.IMAGE_Y0 + L.IMAGE_H // 2
    assert f.getpixel((L.W // 2, y))[:3] == (255, 0, 0)
    assert f.getpixel((L.W // 2 - L.IMAGE_H // 2 + 3, y))[:3] == (255, 0, 0)  # 정사각이 상자 높이를 채움
    assert f.getpixel((L.W // 2 - L.IMAGE_H // 2 - 5, y))[:3] == (0, 0, 0)  # 좌우 검은 띠
    g = c.frame_image(75)
    assert g.getpixel((3, y))[:3] == (0, 0, 255) and g.getpixel((L.W - 4, L.IMAGE_Y0 + 3))[:3] == (0, 0, 255)  # 가로 짤은 가득(cover)


# ---------- 효과음 ----------

SCFG = {"min_gap_s": 0.1, "max_per_video": 60, "place_on": "none",
        "cuts": {"mode": "all", "skip_ratio": 0.3, "skip_first": False, "db": -18, "offset_s": 0.2,
                 "types": {"ding": 0.35, "whoosh": 0.30, "pop": 0.20, "boing": 0.15}},
        "meme_pop": {"db": -18, "offset_s": 0.2, "default_type": "pop"}, "hook": {"enabled": False}}


def test_cut_types_rotation_skip_and_offset(tmp_path):
    lib, _ = S.load_library([sfx_lib(tmp_path, ["ding", "whoosh", "pop", "boing"])])
    tl = timeline(40, 1.0)
    a = S.place_sfx(tl, [], [], lib, SCFG)["events"]
    assert a == S.place_sfx(tl, [], [], lib, SCFG)["events"]  # 결정적
    assert 0.55 * 39 <= len(a) <= 0.85 * 39  # 컷의 약 30% 건너뜀
    assert {e["type"] for e in a} == {"ding", "whoosh", "pop", "boing"}
    assert 0.25 < sum(e["type"] == "ding" for e in a) / len(a) < 0.45
    assert all(abs((e["t"] % 1.0) - 0.2) < 1e-6 for e in a)  # 컷 +0.20초


def test_hook_at_first_cut_and_ending_long_sound(tmp_path):
    d = sfx_lib(tmp_path, ["ding", "pop", "slidewhistle"], dur={"slidewhistle": 1.5})
    lib, _ = S.load_library([d])
    cfg = {**SCFG, "cuts": {"mode": "none"},
           "hook": {"enabled": True, "type": "ding", "at": "first_cut", "db": -18, "offset_s": 0.25},
           "ending": {"type": "slidewhistle", "len_s": 1.5, "db": -18}}
    r = S.place_sfx(timeline(), [], [{"start": 6.0, "beat": "x"}, {"start": 16.0, "beat": "x"}], lib, cfg)["events"]
    by = {e["why"]: e for e in r}
    assert by["hook"]["t"] == pytest.approx(2.25) and by["hook"]["type"] == "ding"
    assert by["ending"]["t"] == pytest.approx(16.2) and by["ending"]["type"] == "slidewhistle"
    assert sum(e["why"] == "meme_pop" for e in r) == 1  # 마지막 짤의 pop 은 끝 효과음이 대신
    assert not any(e["t"] == 0.0 for e in r)  # 훅 효과음은 0초가 아니라 첫 컷에


def test_ending_without_memes_uses_last_cut(tmp_path):
    lib, _ = S.load_library([sfx_lib(tmp_path, ["slidewhistle"])])
    cfg = {**SCFG, "cuts": {"mode": "none", "offset_s": 0.2}, "ending": {"type": "slidewhistle", "db": -18}}
    r = S.place_sfx(timeline(), [], [], lib, cfg)["events"]
    assert [(e["why"], e["t"]) for e in r] == [("ending", pytest.approx(18.2))]


def test_pick_type_weighted_follows_weights():
    got = [S.pick_type_weighted({"a": 0.5, "b": 0.5}, i) for i in range(100)]
    assert 40 <= got.count("a") <= 60


def test_snap_to_speech_gap():
    np = pytest.importorskip("numpy")
    rms = np.ones(300) * 0.3
    rms[140:160] = 0.001  # 1.4~1.6초 쉼
    assert 1.4 <= S.snap_to_gap(1.3, rms, 0.01) <= 1.6
    assert 1.6 <= S.snap_to_gap(1.5 + 0.2, rms, 0.01, voice_offset_s=0.2) <= 1.8  # 목소리가 0.2초 늦을 때
    assert S.snap_to_gap(1.0, None, 0.01) == 1.0
    assert S.snap_to_gap(2.5, rms, 0.01) == pytest.approx(2.5, abs=0.26)  # 쉼이 범위 밖이면 거의 제자리


def test_place_sfx_snaps_events_into_gaps(tmp_path):
    np = pytest.importorskip("numpy")
    lib, _ = S.load_library([sfx_lib(tmp_path, ["ding", "whoosh", "pop", "boing"])])
    rms = np.ones(2000) * 0.3
    rms[::100] = 0.0  # 1초마다 10ms 골
    rms = np.convolve(rms, np.ones(3) / 3, mode="same")
    cfg = {**SCFG, "place_on": "speech_gap", "cuts": {**SCFG["cuts"], "skip_ratio": 0.0}}
    r = S.place_sfx(timeline(10, 2.0), [], [], lib, cfg, energy=(rms, 0.01))["events"]
    assert r and all(abs(e["t"] - round(e["t"])) < 0.02 for e in r)  # 모두 정수 초(골)로 옮겨짐


def test_voice_energy_reads_wav(tmp_path):
    pytest.importorskip("numpy")
    write_wav(tmp_path / "v.wav", 1.0, 441, 0.5)
    rms, hop = S.voice_energy(tmp_path / "v.wav")
    assert hop == 0.01 and len(rms) == 100 and abs(float(rms.mean()) - 0.5 / math.sqrt(2)) < 0.03


# ---------- 그림이 말보다 먼저 ----------

def _first_loud_sec(path):
    with wave.open(path) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = array.array("h", w.readframes(w.getnframes()))
    return next(i for i, v in enumerate(x) if abs(v) > 500) / (sr * ch)


def test_voice_offset_delays_voice_and_keeps_loudness(tmp_path):
    voice = os.path.join(FIX, "voice.wav")
    a, b = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    audio.build_mix(voice, None, 5.0, a)
    audio.build_mix(voice, None, 5.0, b, voice_offset_s=0.5)
    la, lb = audio.measure_loudness(a), audio.measure_loudness(b)
    assert abs(float(la["input_i"]) - float(lb["input_i"])) < 0.3
    assert _first_loud_sec(b) - _first_loud_sec(a) == pytest.approx(0.5, abs=0.03)


def test_voice_offset_does_not_move_sfx(tmp_path):
    snd = tmp_path / "s.wav"
    write_wav(snd, 0.2, 441, 0.9)
    out = str(tmp_path / "o.wav")
    audio.build_mix(None, None, 2.0, out, sfx=[{"file": str(snd), "t": 1.0, "db": -10}], voice_offset_s=0.5)
    assert _first_loud_sec(out) == pytest.approx(1.0, abs=0.03)


def test_apply_fx_adds_picture_lead(tmp_path):
    cfg = load_config(override={"memes": {"enabled": False}, "beats": {"use_llm": False},
                                "sfx": {"libraries": [str(sfx_lib(tmp_path, ["ding", "whoosh", "pop", "boing", "slidewhistle"]))],
                                        "place_on": "none"}})
    tl = {**timeline(), "audio": {"voice": "voice.wav"}, "captions": []}
    timings = {"sentences": [{"index": 0, "role": "hook", "text": "가", "start": 0.0, "end": 2.0},
                             {"index": 1, "role": "body", "text": "나?", "start": 2.0, "end": 4.0}], "duration": 4.0}
    new, _ = A.apply_fx(tl, timings, tmp_path, cfg)
    assert new["audio"]["voice_offset_s"] == 0.2 and new["duration"] == pytest.approx(20.2)
    assert new["shots"][-1]["end"] == pytest.approx(20.2) and tl["duration"] == 20.0  # 원본 불변
    assert new["audio"]["sfx"] and all(0 <= e["t"] < new["duration"] for e in new["audio"]["sfx"])


def test_position_end_puts_reaction_at_sentence_end_and_ends_video(tmp_path):
    lib = make_lib(tmp_path, [("c1", ["conclusion"]), ("t1", ["shock"]), ("s1", ["shock"])])
    import json
    mf = tmp_path / "manifest.json"
    if mf.is_file():
        d = json.loads(mf.read_text(encoding="utf-8"))
        for it in d["items"]:
            if it["id"] == "t1":
                it["has_text"] = True
        mf.write_text(json.dumps(d), encoding="utf-8")
        lib, _ = M.load_library(tmp_path)
    for it in lib:
        if it["id"] == "t1":
            it["has_text"] = True
    ss = sents(["neutral", "neutral", "shock", "neutral"], step=4.0)
    cfg = {**MCFG, "first_after_s": 0.0, "full_shot_len_s": 1.6, "position": "end", "end_with_meme": True, "max_per_video": 4}
    ev = M.pick_memes(ss, lib, cfg, duration=16.5)["events"]
    by = {e["sentence"]: e for e in ev}
    shock = by[ss[2]["index"]]
    assert abs(shock["end"] - ss[3]["start"]) < 1e-6 and abs(shock["end"] - shock["start"] - 1.6) < 1e-6
    assert shock["meme_id"] == "s1"                      # 글씨 있는 짤(t1)은 뒤로
    end = by[ss[3]["index"]]
    assert end["beat"] == "conclusion" and abs(end["end"] - 16.5) < 1e-6


def test_family_cap_keeps_one_pepe(tmp_path):
    lib = make_lib(tmp_path, [("p1", ["shock"]), ("p2", ["conclusion"]), ("p3", ["shock"])])
    for it in lib:
        it["family"] = "pepe"
    lib.append({**lib[0], "id": "w1", "family": "wojak"})
    ss = sents(["neutral", "neutral", "neutral", "shock", "neutral", "shock", "neutral"], step=4.0)
    cfg = {**MCFG, "first_after_s": 0.0, "end_with_meme": True, "max_per_video": 3, "position": "end",
           "max_per_family": {"pepe": 1}, "family_alias": {"apu": "pepe"}}
    ev = M.pick_memes(ss, lib, cfg, duration=28.5)["events"]
    fams = [("pepe" if e["meme_id"].startswith("p") else "wojak") for e in ev]
    assert fams.count("pepe") == 1 and "wojak" in fams and len(ev) == 2


def test_apply_fx_copies_meme_into_job(tmp_path):
    """장면 편집기에서 페페 짤이 안 보이던 문제 — 앱은 작업 폴더 안 파일만 보여 준다.
    고른 짤은 작업 폴더 assets/meme/ 에 복사하고 상대 경로로, 원래 자리는 meme_src 에."""
    libdir = tmp_path / "lib"
    libdir.mkdir()
    make_lib(libdir, [("q1", ["question"])])
    job = tmp_path / "job"
    job.mkdir()
    cfg = load_config(override={"beats": {"use_llm": False}, "sfx": {"enabled": False},
                                "memes": {"library": str(libdir), "pick_by": "beats", "allowed_beats": ["question"],
                                          "beat_priority": ["question"], "first_after_s": 0.0}})
    tl = {**timeline(), "audio": {}, "captions": []}
    timings = {"sentences": [{"index": 0, "role": "hook", "text": "가", "start": 0.0, "end": 2.0},
                             {"index": 1, "role": "body", "text": "이게 왜?", "start": 2.0, "end": 5.0},
                             {"index": 2, "role": "body", "text": "끝.", "start": 5.0, "end": 8.0}], "duration": 8.0}
    new, rep = A.apply_fx(tl, timings, job, cfg, memes=True, sfx=False)
    meme = [s for s in new["shots"] if s.get("kind") == "meme"]
    assert meme and re.fullmatch(r"assets/meme/[0-9a-f]{8}_q1\.png", meme[0]["file"]) and (job / meme[0]["file"]).is_file()
    assert meme[0]["meme_src"].replace("\\", "/").endswith("lib/q1.png")
