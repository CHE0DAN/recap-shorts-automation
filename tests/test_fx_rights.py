"""효과음 저작권 점검(config/sfx_rights.json, 경고만): 기록 내용, 점검 범위, 검수 경고, 고르기 회피(기본 꺼짐), 목록 CLI.
작은 가짜 꾸러미(폴더 이름 user_meme)와 가짜 타임라인만 쓴다 — assets_local 이 없는 PC 에서도 돈다."""
import json
import math
import struct
import wave

import pytest

from recap_shorts.fx import __main__ as fx_cli
from recap_shorts.fx import rights as R
from recap_shorts.fx import sfx as S

HIGH = {"boing_01", "ding_01", "oof_01", "laugh_02", "scream_01", "sus_01"}
MEDIUM = {"error_01", "fanfare_01", "scream_02", "awkward_01", "huh_01", "boom_01"}
LOW = {"pop_01", "pop_02", "hit_01", "boing_02", "coin_01", "boom_02", "boom_03", "huh_02", "awkward_02", "awkward_03",
       "sad_01", "sad_02", "sad_03", "laugh_01", "punchline_01", "bleep_01"}


def write_wav(path, dur=0.2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<h", int(20000 * math.sin(2 * math.pi * 800 * i / 48000))) for i in range(int(48000 * dur))))


def pack(tmp_path, ids_types, name="user_meme"):
    """가짜 효과음 꾸러미 폴더. ids_types = [(id, type), ...]"""
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    items = []
    for i, t in ids_types:
        write_wav(d / f"{i}.wav")
        items.append({"id": i, "file": f"{i}.wav", "type": t, "duration": 0.2, "source_file": f"src/{i}-x.mp3"})
    (d / "manifest.json").write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")
    return d


def ev(d, i, t, **kw):
    return {"file": str(d / f"{i}.wav"), "t": t, "db": -20, "id": i, **kw}


# ------------------------------------------------------------------ 기록 파일
def test_rights_file_has_the_approved_levels():
    r = R.load_rights()
    by = {lv: {k for k, v in r["items"].items() if v["level"] == lv} for lv in ("high", "medium", "low")}
    assert by["high"] == HIGH and by["medium"] == MEDIUM and by["low"] == LOW
    assert len(r["items"]) == 28 and all(v["note"] for v in r["items"].values())
    assert r["items"]["laugh_02"]["note"].startswith("노래 'Oh No'(Capone) 일부") and "Content ID" in r["items"]["laugh_02"]["note"]
    assert r["items"]["oof_01"]["note"] == "로블록스가 2022년 저작권 분쟁으로 교체한 소리"
    assert r["pack"] == "user_meme" and r["unknown_level"] == "medium"
    # 판단 근거(원본 파일 이름만, 소리 지문 아님)를 파일 안에 적어 둔다
    assert "파일 이름" in r["basis"] and "소리 지문" in r["basis"]


def test_missing_or_broken_rights_file_means_no_check(tmp_path):
    assert R.load_rights(tmp_path / "none.json") == {}
    (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")
    assert R.load_rights(tmp_path / "bad.json") == {}
    d = pack(tmp_path, [("scream_01", "scream")])
    assert R.check_events([ev(d, "scream_01", 1.0)], {}) == []


# ------------------------------------------------------------------ 점검 범위·검수 경고
def test_check_events_warns_medium_and_high_only(tmp_path):
    d = pack(tmp_path, [(i, "pop") for i in ("pop_01", "boom_01", "scream_01", "new_99")])
    events = [ev(d, "scream_01", 12.5), ev(d, "pop_01", 3.0), ev(d, "boom_01", 20.0), ev(d, "new_99", 7.25),
              ev(d, "scream_01", 30.0)]
    w = R.check_events(events)
    assert [(x["t"], x["id"], x["level"]) for x in w] == [
        (7.25, "new_99", "medium"), (12.5, "scream_01", "high"), (20.0, "boom_01", "medium"), (30.0, "scream_01", "high")]
    assert w[0]["note"].startswith("저작권 점검 기록 없음")             # 기록에 없는 id -> unknown = medium
    assert w[1]["note"] == "유튜버 영상에서 잘라낸 목소리" and w[1]["source"] == "emotional-damage-auughhh"
    assert R.check_events([]) == [] and R.check_events([ev(d, "pop_01", 1.0)]) == []


def test_id_falls_back_to_file_stem_and_other_folders_are_not_checked(tmp_path):
    d = pack(tmp_path, [("sus_01", "sus")])
    old = {"file": str(d / "sus_01.wav"), "t": 4.0, "db": -20}             # 옛 타임라인: id 없음
    assert [x["id"] for x in R.check_events([old])] == ["sus_01"]
    synth = pack(tmp_path, [("ding_01", "ding")], name="sfx")              # 합성음 폴더에도 같은 id(ding_01)가 있다
    chime = pack(tmp_path, [("sparkle_01", "sparkle")], name="chime")
    assert R.check_events([ev(synth, "ding_01", 1.0), ev(chime, "sparkle_01", 2.0)]) == []
    assert [x["id"] for x in R.check_events([ev(d, "ding_01", 1.0)])] == ["ding_01"]   # 같은 id 라도 user_meme 이면 high


def test_warnings_for_timeline(tmp_path):
    d = pack(tmp_path, [("huh_01", "huh")])
    tl = {"audio": {"sfx": [ev(d, "huh_01", 5.0)]}}
    assert [x["level"] for x in R.warnings_for_timeline(tl)] == ["medium"]
    assert R.warnings_for_timeline({}) == [] and R.warnings_for_timeline({"audio": {"sfx": None}}) == []


def test_review_step_writes_sfx_rights(tmp_path):
    """검수 단계: review.json 의 sfx_rights 에 high·medium 이 시각 순으로 들어간다(승인은 막지 않음)."""
    from recap_shorts import pipeline as P
    from tests.pipeline.fakes import FakeDeps
    from tests.pipeline.test_pipeline import go, make
    deps = FakeDeps(image_up=False)
    store, runner, job = make(tmp_path / "w", deps, {"auto_steps": ["read", "script", "scenes", "review"]})
    go(runner, job)
    rv = json.loads((job.dir / "out" / "review.json").read_text(encoding="utf-8"))
    assert isinstance(rv["sfx_rights"], list)
    d = pack(tmp_path, [(i, "x") for i in ("pop_01", "boom_01", "oof_01")])
    tl = json.loads((job.dir / "timeline.json").read_text(encoding="utf-8"))
    tl["audio"]["sfx"] = [ev(d, "oof_01", 9.0), ev(d, "pop_01", 2.0), ev(d, "boom_01", 4.5)]
    (job.dir / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    P.step_review(P.Ctx(job, "review", deps))
    rv = json.loads((job.dir / "out" / "review.json").read_text(encoding="utf-8"))
    assert [(w["t"], w["id"], w["level"]) for w in rv["sfx_rights"]] == [(4.5, "boom_01", "medium"), (9.0, "oof_01", "high")]
    assert set(rv["sfx_rights"][0]) == {"t", "id", "level", "note", "source"}
    assert job.step("review")["status"] in ("waiting", "done", "running")


# ------------------------------------------------------------------ 고르기 회피 (기본 꺼짐)
def test_filter_library_default_is_untouched(tmp_path):
    d = pack(tmp_path, [("scream_01", "scream"), ("pop_01", "pop")])
    lib, _ = S.load_library([d])
    out, notes = R.filter_library(lib, None)
    assert out is lib and notes == []
    out, notes = R.filter_library(lib, "")
    assert out is lib and notes == []


def test_filter_library_levels(tmp_path):
    ids = ["pop_01", "boom_01", "scream_01", "new_99"]
    d = pack(tmp_path, [(i, "pop") for i in ids])
    synth = pack(tmp_path, [("ding_01", "ding")], name="sfx")
    lib, _ = S.load_library([d, synth])
    keep, notes = R.filter_library(lib, "high")
    assert sorted(it["id"] for it in keep) == ["boom_01", "ding_01", "new_99", "pop_01"]      # scream_01(high)만 빠진다
    assert len(notes) == 1 and "high" in notes[0] and "scream_01" in notes[0]
    keep, notes = R.filter_library(lib, "medium")
    assert sorted(it["id"] for it in keep) == ["ding_01", "pop_01"]                           # medium·high·기록 없음(=medium) 빠짐, 다른 폴더 소리는 그대로
    assert "3개" in notes[0]


def test_filter_library_bad_value_or_no_rights_changes_nothing(tmp_path):
    d = pack(tmp_path, [("scream_01", "scream")])
    lib, _ = S.load_library([d])
    out, notes = R.filter_library(lib, "everything")
    assert out is lib and "몰라" in notes[0]
    out, notes = R.filter_library(lib, "high", rights={})
    assert out is lib and "읽지 못해" in notes[0]


CFG = {"min_gap_s": 0.25, "max_per_video": 24,
       "cuts": {"mode": "none"},
       "meme_pop": {"db": -10, "offset_s": 0.0, "default_type": "pop", "by_beat": {"angry": "scream", "funny": "pop"}},
       "hook": {"enabled": False}, "beat_events": {"enabled": False}, "types_db": {}}


def _timeline():
    return {"duration": 20.0, "shots": [{"file": "x", "start": 0.0, "end": 20.0}], "hook": {"text": "t", "start": 0.0, "end": 2.0}}


def _place(lib, **over):
    memes = [{"start": 4.0, "beat": "angry"}, {"start": 8.0, "beat": "funny"}, {"start": 12.0, "beat": "angry"}]
    return S.place_sfx(_timeline(), [], memes, lib, {**CFG, **over})


def test_picker_default_unchanged_and_avoid_switch(tmp_path):
    d = pack(tmp_path, [("scream_01", "scream"), ("scream_02", "scream"), ("pop_01", "pop")])
    lib, _ = S.load_library([d])
    base = _place(lib)
    assert [e["id"] for e in base["events"]] == ["scream_01", "pop_01", "scream_02"]      # 켜기 전: 돌려 가며 high 도 고른다
    assert _place(lib, avoid_rights_risk=None) == base and not base["notes"]               # 키가 없어도 null 이어도 똑같다

    hi = _place(lib, avoid_rights_risk="high")
    assert [e["id"] for e in hi["events"]] == ["scream_02", "pop_01", "scream_02"]         # scream_01(high) 제외
    assert any("scream_01" in n for n in hi["notes"])

    med = _place(lib, avoid_rights_risk="medium")
    assert [e["id"] for e in med["events"]] == ["pop_01"]                                  # scream 이 모두 빠져 그 자리는 건너뜀
    assert any("scream" in n and "없는 효과음 종류" in n for n in med["notes"])
    assert all(R.assess(e["id"], e["file"], R.load_rights())["level"] == "low" for e in med["events"])


def test_avoid_switch_is_off_in_default_config():
    from recap_shorts.fx.config import load_config
    cfg = load_config()["sfx"]
    assert "avoid_rights_risk" in cfg and cfg["avoid_rights_risk"] is None


# ------------------------------------------------------------------ 목록 CLI
def test_cli_pack_table(tmp_path, capsys):
    d = pack(tmp_path, [(i, "x") for i in sorted(HIGH | MEDIUM | LOW)] + [("new_99", "x")])
    fx_cli.main(["rights", "--library", str(d)])
    out = capsys.readouterr().out
    assert "원본 파일 이름만 보고 매긴 것" in out and "high 6 / medium 7 / low 16" in out      # new_99 는 unknown = medium
    assert out.index("[high]") < out.index("[medium]") < out.index("[low]")
    assert "닌텐도 게임 소리" in out and "new_99" in out and "기록 없음" in out
    assert "sfx.avoid_rights_risk = null" in out


def test_cli_pack_json_and_other_folder(tmp_path, capsys):
    d = pack(tmp_path, [("scream_01", "scream")], name="chime")
    R.main(["--library", str(d), "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rep["rows"] == [] and rep["not_checked"][0]["count"] == 1 and rep["avoid_rights_risk"] is None


def test_cli_job_lists_risky_sounds(tmp_path, capsys):
    d = pack(tmp_path, [("scream_01", "scream"), ("pop_01", "pop"), ("huh_01", "huh")])
    job = tmp_path / "job"
    job.mkdir()
    (job / "timeline.json").write_text(json.dumps({"audio": {"sfx": [ev(d, "huh_01", 3.0), ev(d, "pop_01", 4.0), ev(d, "scream_01", 9.5)]}}),
                                       encoding="utf-8")
    fx_cli.main(["rights", "--job", str(job)])
    out = capsys.readouterr().out
    assert "효과음 3개 중 주의 이상 2개" in out
    assert out.index("scream_01") < out.index("huh_01") and "pop_01" not in out.split("\n", 1)[1]    # high 가 먼저, low 는 안 나옴
    R.main(["--job", str(job), "--json"])
    assert [w["id"] for w in json.loads(capsys.readouterr().out)] == ["huh_01", "scream_01"]


def test_ban_sources_removes_sound_from_picks():
    """한 번 걸러 낸 소리(emotional damage)는 다시 쓰지 않는다(sfx.ban_sources)."""
    lib = [{"id": "scream_01", "type": "scream", "file": "a.wav", "source_file": "src/emotional-damage-auughhh.mp3", "priority": 0},
           {"id": "scream_02", "type": "scream", "file": "b.wav", "source_file": "src/faahhhh-funny-scream.mp3", "priority": 0},
           {"id": "pop_01", "type": "pop", "file": "c.wav", "source_file": "src/pop.mp3", "priority": 0}]
    res = _place(lib, ban_sources=["emotional-damage-auughhh"])
    files = [e["file"] for e in res["events"]]
    assert "a.wav" not in files and "b.wav" in files
    assert any("ban_sources" in n for n in res["notes"])
