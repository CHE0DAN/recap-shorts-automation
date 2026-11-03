import json

from PIL import Image

from recap_shorts.fx import memes as M
from recap_shorts.fx.config import load_config


def make_lib(tmp_path, specs):
    items = []
    for id_, fam, beats, tr in specs:
        Image.new("RGBA", (64, 64), (0, 200, 0, 255 if not tr else 128)).save(tmp_path / f"{id_}.png")
        items.append({"id": id_, "file": f"{id_}.png", "family": fam, "beats": beats, "transparent": tr, "name": id_})
    (tmp_path / "manifest.json").write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")
    return tmp_path


def sents(beats, step=3.0, hook=True):
    return [{"index": i, "role": "hook" if (hook and i == 0) else "body", "text": f"문장{i}",
             "start": i * step, "end": (i + 1) * step - 0.1, "beat": b} for i, b in enumerate(beats)]


CFG = {"max_per_video": 4, "min_gap_s": 4.0, "allowed_beats": ["shock", "funny", "sad"],
       "beat_priority": ["shock", "funny", "sad"], "on_hook": False, "prefer_transparent": True,
       "full_shot_ratio": 0.0, "sticker": {"anchors": ["box_br", "box_bl"], "max_len_s": 1.8}}


def test_missing_or_empty_library_is_not_an_error(tmp_path):
    lib, note = M.load_library(tmp_path / "nope")
    assert lib == [] and "건너뜀" in note
    (tmp_path / "manifest.json").write_text('{"version":1,"items":[]}', encoding="utf-8")
    assert M.load_library(tmp_path)[0] == []
    assert M.pick_memes(sents(["shock"] * 3), [], CFG)["events"] == []


def test_manifest_skips_items_without_file(tmp_path):
    lib_dir = make_lib(tmp_path, [("a", "pepe", ["shock"], True)])
    doc = json.loads((lib_dir / "manifest.json").read_text(encoding="utf-8"))
    doc["items"].append({"id": "ghost", "file": "ghost.png", "beats": ["shock"]})
    (lib_dir / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    lib, _ = M.load_library(lib_dir)
    assert [i["id"] for i in lib] == ["a"]


def test_picker_rules(tmp_path):
    lib, _ = M.load_library(make_lib(tmp_path, [
        ("s1", "pepe", ["shock"], True), ("s2", "wojak", ["shock"], True), ("s3", "pepe", ["shock"], False),
        ("f1", "pepe", ["funny"], True), ("d1", "pepe", ["sad"], True)]))
    ss = sents(["shock", "shock", "neutral", "funny", "shock", "sad", "shock", "funny"])
    ev = M.pick_memes(ss, lib, CFG, seed=1)["events"]
    assert 1 <= len(ev) <= CFG["max_per_video"]
    assert all(e["sentence"] != 0 for e in ev)  # 훅 제외
    starts = [e["start"] for e in ev]
    assert starts == sorted(starts)
    assert all(b - a >= CFG["min_gap_s"] - 1e-9 for a, b in zip(starts, starts[1:]))
    ids = [e["meme_id"] for e in ev]
    assert len(ids) == len(set(ids))  # 한 편에서 같은 짤 반복 없음
    assert all(e["end"] - e["start"] <= 1.8 + 1e-9 for e in ev)
    shock = [e["meme_id"] for e in ev if e["beat"] == "shock"]
    assert "s3" not in shock or {"s1", "s2"} <= set(shock)  # 투명한 것 먼저, 불투명은 마지막 수단


def test_prefers_transparent(tmp_path):
    lib, _ = M.load_library(make_lib(tmp_path, [("opaque", "pepe", ["shock"], False), ("clear", "wojak", ["shock"], True)]))
    ev = M.pick_memes(sents(["neutral", "shock"]), lib, CFG)["events"]
    assert [e["meme_id"] for e in ev] == ["clear"]


def test_on_hook_enabled_allows_hook(tmp_path):
    lib, _ = M.load_library(make_lib(tmp_path, [("s1", "pepe", ["shock"], True)]))
    ss = sents(["shock", "neutral"])
    assert M.pick_memes(ss, lib, CFG)["events"] == []
    assert len(M.pick_memes(ss, lib, {**CFG, "on_hook": True})["events"]) == 1


def test_no_matching_beat_adds_note(tmp_path):
    lib, _ = M.load_library(make_lib(tmp_path, [("d1", "pepe", ["sad"], True)]))
    r = M.pick_memes(sents(["neutral", "shock"]), lib, CFG)
    assert r["events"] == [] and any("맞는 짤이 없어" in n for n in r["notes"])


def test_full_shot_ratio_and_anchor_cycle(tmp_path):
    lib, _ = M.load_library(make_lib(tmp_path, [(f"s{i}", "pepe", ["shock"], True) for i in range(6)]))
    ss = sents(["neutral"] + ["shock"] * 7, step=5.0)
    ev = M.pick_memes(ss, lib, {**CFG, "max_per_video": 4, "full_shot_ratio": 0.5})["events"]
    assert [e["mode"] for e in ev] == ["sticker", "shot", "sticker", "shot"]
    assert [e["anchor"] for e in ev if e["mode"] == "sticker"] == ["box_br", "box_bl"]


def test_deterministic(tmp_path):
    lib, _ = M.load_library(make_lib(tmp_path, [(f"s{i}", "pepe", ["shock"], True) for i in range(5)]))
    ss = sents(["neutral"] + ["shock"] * 6, step=5.0)
    a = M.pick_memes(ss, lib, CFG, seed="job1")["events"]
    assert a == M.pick_memes(ss, lib, CFG, seed="job1")["events"]


def test_overlay_and_shot_conversion():
    cfg = load_config(override={"memes": {"sticker": {"anim": "pop", "anim_by_beat": {"shock": "shake"}}}})["memes"]
    ev = {"sentence": 3, "beat": "shock", "start": 5.0, "end": 6.5, "meme_id": "x", "file": "/a/x.png", "anchor": "box_bl"}
    ov = M.to_overlay(ev, cfg)
    assert ov["kind"] == "sticker" and ov["anchor"] == "box_bl" and ov["anim"] == "shake"
    assert ov["size_frac"] == cfg["sticker"]["size_frac"]
    sh = M.to_shot(ev, cfg)
    assert sh["kind"] == "meme" and sh["start"] == 5.0 and sh["end"] == 6.5


def test_insert_shot_keeps_contiguous_coverage():
    shots = [{"file": "a", "start": 0.0, "end": 3.0, "motion": "zoom_in"},
             {"file": "b", "start": 3.0, "end": 6.0, "motion": "static"},
             {"file": "c", "start": 6.0, "end": 9.0, "motion": "enter"}]
    out = M.insert_shot(shots, {"file": "m", "kind": "meme", "start": 4.0, "end": 7.0})
    assert out[0]["start"] == 0.0 and out[-1]["end"] == 9.0
    for a, b in zip(out, out[1:]):
        assert abs(a["end"] - b["start"]) < 1e-6
    assert [s["file"] for s in out] == ["a", "b", "m", "c"]
    assert out[-1]["start"] == 7.0 and out[-1]["motion"] == "static"  # 잘린 오른쪽 조각은 등장 효과 없이


def test_insert_shot_absorbs_slivers():
    shots = [{"file": "b", "start": 3.0, "end": 6.0, "motion": "static"}]
    out = M.insert_shot(shots, {"file": "m", "kind": "meme", "start": 3.05, "end": 5.95})
    assert len(out) == 1 and out[0]["kind"] == "meme" and (out[0]["start"], out[0]["end"]) == (3.0, 6.0)
