import json
import math
import os
import shutil
import struct
import subprocess
import wave

import pytest

from recap_shorts.fx import apply as A
from recap_shorts.fx import sfx as S
from recap_shorts.fx.config import enabled, load_config
from recap_shorts.render import audio

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "render")


def write_wav(path, dur=0.3, freq=1000.0, amp=0.95, sr=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / sr)))
                               for i in range(int(sr * dur))))


def lib_dir(tmp_path, types=("swoosh", "pop", "boom", "ding", "whoosh")):
    d = tmp_path / "sfxlib"
    d.mkdir()
    items = []
    for t in types:
        for k in (1, 2):
            write_wav(d / f"{t}_{k}.wav", 0.2)
            items.append({"id": f"{t}_{k}", "file": f"{t}_{k}.wav", "type": t, "duration": 0.2})
    (d / "manifest.json").write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")
    return d


def timeline(n_cuts=10, step=2.0):
    shots = [{"file": "x", "start": i * step, "end": (i + 1) * step, "motion": "static"} for i in range(n_cuts)]
    return {"duration": n_cuts * step, "shots": shots, "hook": {"text": "t", "start": 0.0, "end": step}}


CFG = {"min_gap_s": 0.25, "max_per_video": 24,
       "cuts": {"mode": "every_k", "k": 2, "type": "swoosh", "db": -18, "offset_s": 0.0, "skip_first": True},
       "meme_pop": {"db": -10, "offset_s": 0.0, "default_type": "pop", "by_beat": {"shock": "boom"}},
       "hook": {"enabled": True, "type": "whoosh", "db": -12, "offset_s": 0.0},
       "beat_events": {"enabled": True, "db": -8, "offset_s": 0.0, "by_beat": {"reveal": "ding"}}, "types_db": {}}


def test_load_library_and_missing(tmp_path):
    lib, notes = S.load_library([lib_dir(tmp_path), tmp_path / "none"])
    assert len(lib) == 10 and not notes
    lib, notes = S.load_library([tmp_path / "none"])
    assert lib == [] and notes


def test_cut_modes():
    tl = timeline()
    starts = [s["start"] for s in tl["shots"]][1:]
    assert S.cut_times(tl, {"mode": "none"}, []) == []
    assert S.cut_times(tl, {"mode": "all", "skip_first": False}, []) == starts
    assert S.cut_times(tl, {"mode": "every_k", "k": 3, "skip_first": False}, []) == starts[::3]
    assert S.cut_times(tl, {"mode": "sentence_start", "skip_first": False}, [4.0, 8.03]) == [4.0, 8.0]
    tl["shots"][3]["kind"] = "meme"  # 짤 샷 시작은 컷 효과음에서 제외
    assert 6.0 not in S.cut_times(tl, {"mode": "all", "skip_first": False}, [])


def test_placement_priority_gap_and_types(tmp_path):
    lib, _ = S.load_library([lib_dir(tmp_path)])
    tl = timeline()
    sents = [{"index": 0, "role": "hook", "start": 0.0, "end": 2.0, "beat": "shock"},
             {"index": 1, "role": "body", "start": 4.0, "end": 6.0, "beat": "reveal"}]
    memes = [{"start": 4.1, "beat": "shock"}, {"start": 10.0, "beat": "funny"}]
    r = S.place_sfx(tl, sents, memes, lib, CFG)
    ev = r["events"]
    ts = [e["t"] for e in ev]
    assert ts == sorted(ts)
    assert all(b - a >= 0.25 - 1e-9 for a, b in zip(ts, ts[1:]))
    by = {e["t"]: e for e in ev}
    assert by[0.0]["type"] == "whoosh" and by[0.0]["why"] == "hook"
    assert by[4.1]["type"] == "boom" and by[4.1]["db"] == -10  # 짤(4.1) 이 컷/반전(4.0) 보다 우선하고 비슷한 시각은 하나만
    assert 4.0 not in by
    assert by[10.0]["type"] == "pop"  # 모르는 beat -> 기본 종류
    assert all(os.path.isfile(e["file"]) for e in ev)


def test_same_type_rotates_files(tmp_path):
    lib, _ = S.load_library([lib_dir(tmp_path)])
    r = S.place_sfx(timeline(), [], [], lib, {**CFG, "hook": {"enabled": False},
                                               "cuts": {"mode": "all", "type": "swoosh", "db": -18, "skip_first": False}})
    ids = [e["id"] for e in r["events"]]
    assert len(ids) >= 4 and all(a != b for a, b in zip(ids, ids[1:]))


def test_missing_type_noted_and_max_cap(tmp_path):
    lib, _ = S.load_library([lib_dir(tmp_path, types=("pop",))])
    r = S.place_sfx(timeline(), [], [{"start": 3.0, "beat": "shock"}], lib, CFG)
    assert any("boom" in n for n in r["notes"])
    r2 = S.place_sfx(timeline(20), [], [], S.load_library([lib_dir(tmp_path / "..", types=("swoosh",))])[0] if False else lib,
                     {**CFG, "cuts": {"mode": "all", "type": "pop", "db": -18, "skip_first": False}, "max_per_video": 5})
    assert len(r2["events"]) <= 5


def test_types_db_override(tmp_path):
    lib, _ = S.load_library([lib_dir(tmp_path)])
    r = S.place_sfx(timeline(), [], [], lib, {**CFG, "types_db": {"swoosh": -30}})
    assert {e["db"] for e in r["events"] if e["type"] == "swoosh"} == {-30}


def test_config_defaults_on_and_job_option():
    cfg = load_config()
    assert cfg["enabled"] is True and cfg["memes"]["enabled"] is True and cfg["sfx"]["enabled"] is True
    assert enabled(cfg, {}) and not enabled(cfg, {"fx": False}) and enabled(cfg, {"fx": True})
    assert not enabled({"enabled": False}, {}) and enabled({"enabled": False}, {"fx": {"memes": {"enabled": True}}})


def test_maybe_apply_off_adds_only_intro(tmp_path):
    # fx 를 꺼도 인트로 카드는 붙는다(인트로 고정). 짤·효과음은 붙지 않고 입력도 그대로
    tl = timeline()
    before = json.dumps(tl, sort_keys=True)
    out = A.maybe_apply(tmp_path, tl, {"sentences": []}, {"fx": False})
    assert json.dumps(tl, sort_keys=True) == before
    assert {k: v for k, v in out.items() if k != "intro"} == tl and "intro" in out
    assert "fx" not in out and not (out.get("audio") or {}).get("sfx")


def test_make_sfx_library_files_match_manifest():
    root = os.path.join(os.path.dirname(__file__), "..", "assets", "sfx")
    mf = json.load(open(os.path.join(root, "manifest.json"), encoding="utf-8"))
    types = {i["type"] for i in mf["items"]}
    assert set(S.SFX_TYPES) <= types
    for it in mf["items"]:
        with wave.open(os.path.join(root, it["file"])) as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (48000, 1, 2)
            assert w.getnframes() / 48000 == pytest.approx(it["duration"], abs=0.002)


# ---------- 직접 모은 꾸러미가 없는 PC: 저장소 합성음으로 대신 ----------

def test_builtin_fallback_values_are_synth_types():
    assert set(S.SFX_TYPES) >= set(S.BUILTIN_TYPE_FALLBACK.values())


def test_builtin_type_fallback_config_wins_and_goes_one_more_hop():
    # 설정이 직접 적은 값이 먼저. 설정이 합성 꾸러미에 없는 종류로 보내면 한 번 더 합성 종류로 바꾼다(sparkle 은 없앰).
    fb = S.builtin_type_fallback({"cheer": "laugh", "sparkle": "ding", "hit": "boom"})
    assert fb["hit"] == "boom" and fb["sparkle"] == "ding"     # 설정 값 유지
    assert fb["cheer"] == "boing"                              # laugh → boing 두 번째 걸음
    assert fb["scream"] == "buzz" and fb["whoosh_short"] == "whoosh"  # 대응표가 채움


def test_synth_cast_merges_sizes_and_cut_weights():
    types_db = {"sparkle": -15, "ding": -23, "huh": -21}
    weights = {"sparkle": 0.26, "ding": 0.22, "boom": 0.11}
    tdb, cuts = S.synth_cast(types_db, {"types": weights, "mode": "all"})
    # sparkle 자리는 ding 으로, huh(물음표)는 boing 으로 합쳐지므로 'sparkle'·'huh' 크기가 따로 남지 않는다
    # (기본 db 로 커지지 않음). 대응표에 없는 종류는 그대로 둔다.
    assert tdb == {"ding": -23, "boing": -21}
    assert cuts["types"] == {"ding": pytest.approx(0.22 + 0.26), "boom": pytest.approx(0.11)}
    assert cuts["mode"] == "all"
    assert types_db["sparkle"] == -15 and weights["sparkle"] == 0.26   # 입력 dict 는 그대로
    tdb2, cuts2 = S.synth_cast(None, None)
    assert tdb2 == {} and cuts2 is None


def test_apply_fx_falls_back_to_builtin_sfx_when_user_pack_missing(tmp_path):
    """새로 설치한 판(assets_local 없음)에서 효과음이 하나도 안 붙던 결함 — 저장소 합성음으로 대신한다.
    훅 '탁'(hit)은 합성 꾸러미에 없어 대응표로 pop, 컷 'sparkle' 비중은 ding 으로 합쳐진다."""
    cfg = load_config(override={"memes": {"enabled": False}, "beats": {"use_llm": False},
                                "sfx": {"libraries": [str(tmp_path / "nope")], "fallback_libraries": []}})
    tl = {**timeline(), "audio": {"voice": "voice.wav"}, "captions": []}
    timings = {"sentences": [{"index": 0, "role": "hook", "text": "가", "start": 0.0, "end": 2.0},
                             {"index": 1, "role": "body", "text": "나?", "start": 2.0, "end": 4.0}], "duration": 4.0}
    new, rep = A.apply_fx(tl, timings, tmp_path, cfg)
    ev = new["audio"]["sfx"]
    assert ev and all(os.path.isfile(e["file"]) for e in ev)
    assert all("assets" in e["file"].replace("\\", "/") and "/sfx/" in e["file"].replace("\\", "/") for e in ev)
    assert any(e["type"] == "pop" and e["why"] == "hook" for e in ev)   # hit → pop
    assert {e["type"] for e in ev} <= set(S.SFX_TYPES)
    assert any("저장소 합성음" in n for n in rep["notes"])


def test_apply_fx_keeps_user_pack_when_present(tmp_path):
    """assets_local 이 있는 PC: 예전처럼 그 꾸러미만 쓰고, 종류 대응표·크기를 바꾸지 않는다."""
    user = lib_dir(tmp_path, types=("hit", "sparkle", "pop"))
    cfg = load_config(override={"memes": {"enabled": False}, "beats": {"use_llm": False},
                                "sfx": {"libraries": [str(user)], "fallback_libraries": []}})
    tl = {**timeline(), "audio": {"voice": "voice.wav"}, "captions": []}
    timings = {"sentences": [{"index": 0, "role": "hook", "text": "가", "start": 0.0, "end": 2.0},
                             {"index": 1, "role": "body", "text": "나?", "start": 2.0, "end": 4.0}], "duration": 4.0}
    new, rep = A.apply_fx(tl, timings, tmp_path, cfg)
    ev = new["audio"]["sfx"]
    assert ev and all(os.path.dirname(e["file"]) == str(user) for e in ev)
    assert any(e["type"] == "hit" for e in ev)                     # 대응표를 덧씌우지 않는다
    assert {e["type"] for e in ev} <= {"hit", "sparkle", "pop"}
    assert not any("저장소 합성음" in n for n in rep["notes"])


def test_missing_meme_library_is_skipped_silently(tmp_path):
    """짤 꾸러미(assets_local/memes_r)가 없는 판: 오류 없이 짤만 건너뛴다."""
    cfg = load_config(override={"memes": {"library": str(tmp_path / "no_memes")}, "beats": {"use_llm": False},
                                "sfx": {"libraries": [str(tmp_path / "nope")]}})
    tl = {**timeline(), "audio": {}, "captions": []}
    timings = {"sentences": [{"index": 0, "role": "hook", "text": "가", "start": 0.0, "end": 2.0},
                             {"index": 1, "role": "body", "text": "나", "start": 2.0, "end": 4.0}], "duration": 4.0}
    new, rep = A.apply_fx(tl, timings, tmp_path, cfg)
    assert not [s for s in new["shots"] if s.get("kind") == "meme"] and not new["overlays"]
    assert any("짤 라이브러리" in n for n in rep["notes"])
    assert "error" not in rep and not any("Traceback" in n for n in rep["notes"])


# ---------- 믹스 ----------

def _peak_and_len(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    mx = float([ln for ln in r.stderr.splitlines() if "max_volume" in ln][0].split("max_volume:")[1].split("dB")[0])
    with wave.open(path) as w:
        return mx, w.getnframes() / w.getframerate()


def test_mix_length_and_no_clipping_even_when_stacked(tmp_path):
    voice = os.path.join(FIX, "voice.wav")
    loud = tmp_path / "loud.wav"
    write_wav(loud, 0.5, 441, 0.99)
    dur = 6.0
    ev = [{"file": str(loud), "t": t, "db": 6.0} for t in (0.5, 0.55, 0.6, 2.0, 2.0, 5.9)]  # 겹치게, 일부러 세게
    mixed = str(tmp_path / "mixed.wav")
    info = audio.build_mix(voice, None, dur, mixed, sfx=ev)
    assert info["sfx_count"] == 6
    peak, length = _peak_and_len(mixed)
    assert length == pytest.approx(dur, abs=0.02)
    assert peak <= -0.3  # 한계 0.95(약 -0.45 dBFS) -> 클리핑 없음


def test_voice_loudness_kept_with_normal_levels(tmp_path):
    voice = os.path.join(FIX, "voice.wav")
    snd = tmp_path / "pop.wav"
    write_wav(snd, 0.2, 441, 0.9)
    plain, mixed = str(tmp_path / "plain.wav"), str(tmp_path / "mixed.wav")
    audio.build_mix(voice, None, 6.0, plain)
    audio.build_mix(voice, None, 6.0, mixed, sfx=[{"file": str(snd), "t": t, "db": -12.0} for t in (1.0, 3.0, 5.0)])
    a, b = audio.measure_loudness(plain), audio.measure_loudness(mixed)
    assert abs(float(a["input_i"]) - float(b["input_i"])) < 1.0


def test_mix_sfx_gain_follows_db(tmp_path):
    f = tmp_path / "s.wav"
    write_wav(f, 0.3, 441, 0.9)
    out = {}
    for db in (-6, -18):
        p = str(tmp_path / f"o{db}.wav")
        audio.build_mix(None, None, 1.0, p, sfx=[{"file": str(f), "t": 0.1, "db": db}])
        out[db] = _peak_and_len(p)[0]
    assert out[-6] == pytest.approx(audio.VOICE_PEAK_DB - 6, abs=0.6)
    assert out[-6] - out[-18] == pytest.approx(12, abs=0.6)


def test_mix_ignores_events_outside_duration(tmp_path):
    f = tmp_path / "s.wav"
    write_wav(f, 0.3)
    info = audio.build_mix(None, None, 1.0, str(tmp_path / "o.wav"), sfx=[{"file": str(f), "t": 5.0, "db": -10}])
    assert info["sfx_count"] == 0


def test_render_with_sfx_in_timeline(tmp_path):
    from recap_shorts.render.render import render
    with open(os.path.join(FIX, "sample_timeline.json"), encoding="utf-8") as f:
        tl = json.load(f)
    tl["duration"] = 3.0
    tl["shots"] = [s for s in tl["shots"] if s["start"] < 3.0]
    tl["shots"][-1]["end"] = 3.0
    tl["captions"] = [c for c in tl["captions"] if c["start"] < 3.0]
    tl["captions"][-1]["end"] = 3.0
    shutil.copytree(os.path.join(FIX, "images"), tmp_path / "images")
    shutil.copy(os.path.join(FIX, "voice.wav"), tmp_path / "voice.wav")
    write_wav(tmp_path / "pop.wav", 0.2)
    tl["audio"]["sfx"] = [{"file": "pop.wav", "t": 1.0, "db": -10}]  # 상대 경로도 작업 폴더 기준으로 풀림
    p = tmp_path / "tl.json"
    p.write_text(json.dumps(tl), encoding="utf-8")
    res = render(str(p), str(tmp_path / "o.mp4"), quiet=True)
    assert res["sfx_count"] == 1 and os.path.getsize(tmp_path / "o.mp4") > 1000


def test_sfx_drop_list(tmp_path):
    """사람이 뺀 효과음(16초에서 어울리지 않아 뺌)은 시각·id 가 맞을 때만 빠진다."""
    assert A.sfx_drops(tmp_path) == []
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "sfx_drop.json").write_text(json.dumps([{"t": 15.785, "id": "scream_01"}, {"x": 1}]), encoding="utf-8")
    drops = A.sfx_drops(tmp_path)
    assert drops == [{"t": 15.785, "id": "scream_01"}]
    assert A.dropped({"t": 15.9, "id": "scream_01"}, drops[0])
    assert not A.dropped({"t": 15.9, "id": "pop_01"}, drops[0])
    assert not A.dropped({"t": 17.0, "id": "scream_01"}, drops[0])
    assert A.dropped({"t": 15.7, "id": "pop_01"}, {"t": 15.785})
    (tmp_path / "fx" / "sfx_drop.json").write_text("{broken", encoding="utf-8")
    assert A.sfx_drops(tmp_path) == []
