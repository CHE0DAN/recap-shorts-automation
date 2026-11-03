"""짤을 문장 뜻에 맞춰 고르기(pick_by "fit") — 문장과 짤 뜻을 같이 보고 고른다."""
import json

from PIL import Image

from recap_shorts.fx import meme_fit as MF
from recap_shorts.fx import memes as M

CFG = {"position": "end", "min_before_s": 0.6, "full_shot_len_s": 1.2, "full_shot_min_s": 0.6, "full_shot_max_s": 2.0,
       "first_after_s": 3.0, "end_with_meme": False, "min_gap_s": 3.0, "max_per_video": 2, "full_shot_ratio": 1.0,
       "max_per_family": {"pepe": 1}, "allowed_beats": ["reveal", "funny"], "beat_priority": ["reveal", "funny"]}


def lib(tmp_path, ids=("shrug", "smug", "dots"), family="pepe"):
    items = []
    for i in ids:
        Image.new("RGB", (32, 32), "white").save(tmp_path / f"{i}.png")
        items.append({"id": i, "file": f"{i}.png", "family": family, "beats": ["reveal"], "meaning": f"{i} 뜻"})
    (tmp_path / "manifest.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return M.load_library(tmp_path)[0]


def sents(n=6, step=3.0):
    return [{"index": i, "role": "hook" if i == 0 else "body", "text": f"문장{i}", "start": i * step,
             "end": (i + 1) * step - 0.1, "beat": "reveal"} for i in range(n)]


def test_eligible_skips_hook_early_and_last():
    # 훅(0)·3초 전(문장 1의 짤 자리는 4.8초부터라 통과)·마지막 문장(5, end_with_meme 꺼짐)은 뺀다
    assert M.eligible_indices(sents(), CFG, 18.0) == [1, 2, 3, 4]
    assert M.eligible_indices(sents(), {**CFG, "end_with_meme": True}, 18.0) == [1, 2, 3, 4, 5]
    assert M.eligible_indices(sents(), {**CFG, "first_after_s": 7.0}, 18.0) == [2, 3, 4]


def test_validate_drops_bad_rows_and_caps():
    raw = {"picks": [{"sentence": 9, "meme": "shrug"}, {"sentence": 2, "meme": "nope"}, {"sentence": "3", "meme": "dots", "why": "어이없음"},
                     {"sentence": 3, "meme": "smug"}, {"sentence": 4, "meme_id": "shrug"}, {"sentence": 1, "meme": "smug"}]}
    got = MF.validate(raw, [1, 2, 3, 4], ["shrug", "smug", "dots"], 2)
    assert got == [{"sentence": 3, "meme_id": "dots", "why": "어이없음"}, {"sentence": 4, "meme_id": "shrug", "why": ""}]
    assert MF.validate({"beats": []}, [1], ["shrug"], 2) is None


def test_fit_memes_uses_llm_once_then_cache(tmp_path):
    L = lib(tmp_path)
    calls = []

    def llm(prompt):
        calls.append(prompt)
        return {"picks": [{"sentence": 4, "meme": "dots", "why": "황당"}]}
    cp = tmp_path / "fx" / "meme_fit.json"
    r = MF.fit_memes(sents(), L, [1, 2, 3, 4], 2, cache_path=cp, llm=llm)
    assert r["source"] == "llm" and r["picks"] == [{"sentence": 4, "meme_id": "dots", "why": "황당"}]
    assert "dots 뜻" in calls[0] and "고를 수 있는 문장 번호: 1, 2, 3, 4" in calls[0]
    r2 = MF.fit_memes(sents(), L, [1, 2, 3, 4], 2, cache_path=cp, llm=llm)
    assert r2["source"] == "cache" and len(calls) == 1


def test_fit_memes_failure_means_no_memes(tmp_path):
    L = lib(tmp_path)

    def boom(prompt):
        raise RuntimeError("한도")
    r = MF.fit_memes(sents(), L, [1, 2], 2, cache_path=tmp_path / "f.json", llm=boom)
    assert r["picks"] == [] and "한도" in r["error"] and not (tmp_path / "f.json").exists()


def test_pick_memes_with_fits_uses_only_those_pairs(tmp_path):
    L = lib(tmp_path)
    # 박자로는 문장 1(reveal)에 붙었을 짤이, fit 결과(문장 4에 dots)만 따른다
    out = M.pick_memes(sents(), L, CFG, duration=18.0, fits=[{"sentence": 4, "meme_id": "dots"}])
    assert [(e["sentence"], e["meme_id"]) for e in out["events"]] == [(4, "dots")]
    none = M.pick_memes(sents(), L, CFG, duration=18.0, fits=[])
    assert none["events"] == [] and any("어울리는 짤 없음" in n for n in none["notes"])
    # 페페 계열 1개 상한은 그대로
    two = M.pick_memes(sents(), L, CFG, duration=18.0,
                       fits=[{"sentence": 2, "meme_id": "shrug"}, {"sentence": 4, "meme_id": "dots"}])
    assert [e["sentence"] for e in two["events"]] == [2]
    beats = M.pick_memes(sents(), L, CFG, duration=18.0)          # fits 없으면 예전(박자) 방식
    assert beats["events"] and beats["events"][0]["sentence"] == 1


def test_effective_max_counts_family_caps(tmp_path):
    L = lib(tmp_path)
    assert M.effective_max(L, CFG, 30.0) == 1                       # 모두 페페, 페페 상한 1
    assert M.effective_max(L, {**CFG, "max_per_family": {}}, 30.0) == 2


def test_fit_event_takes_the_memes_beat(tmp_path):
    L = lib(tmp_path)
    for it in L:
        it["beats"] = {"shrug": ["question"], "smug": ["smug"], "dots": ["awkward"]}[it["id"]]
    s = sents()
    s[4]["beat"] = "smug"
    out = M.pick_memes(s, L, CFG, duration=18.0, fits=[{"sentence": 4, "meme_id": "shrug"}])
    assert out["events"][0]["beat"] == "question"        # 효과음은 meme_pop.by_beat[question](허?)
