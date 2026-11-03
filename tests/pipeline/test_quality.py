from recap_shorts.images import quality


def _fake(answer):
    return lambda imgs, instr: answer


def test_review_flags_and_redo_order():
    ans = {"items": [
        {"i": 1, "sunset": True, "reason": "노을"},
        {"i": 2},
        {"i": 3, "blank_screen": True, "neon_float": True},
        {"i": 4, "filler": True, "similar_to": 2},
    ], "worst": [3, 4, 99, 3]}
    r = quality.review(["a", "b", "c", "d"], ["h1", "h2", "h3", "h4"], read_fn=_fake(ans))
    assert r["worst"] == [3, 4]
    rows = r["items"]
    assert rows[0]["sunset"] and rows[0]["bad"] == 1
    assert rows[1]["bad"] == 0
    assert rows[2]["bad"] == 2 + 2 + 1
    assert rows[3]["similar_to"] == 2 and rows[3]["bad"] == 1 + 1 + 1
    # 심한 결함(3번) 먼저, 가벼운 결함 2개 이상(4번) 다음, 노을 하나(1번)는 다시 만들지 않음
    assert quality.pick_redo(r, max_redo=3) == [2, 3]
    assert quality.pick_redo(r, max_redo=1) == [2]


def test_review_failure_and_bad_answers():
    def boom(imgs, instr):
        raise RuntimeError("api down")
    assert quality.review(["a"], ["h"], read_fn=boom) == {"items": [], "worst": []}
    assert quality.review(["a"], ["h"], read_fn=_fake({"nope": 1})) == {"items": [], "worst": []}
    r = quality.review(["a", "b"], ["h", "h"], read_fn=_fake({"items": [{"i": "x"}, {"i": 2, "similar_to": 5}]}))
    assert [x["bad"] for x in r["items"]] == [0, 0] and r["items"][1]["similar_to"] == 0
    assert quality.review([], [], read_fn=boom) == {"items": [], "worst": []}


def _job(tmp_path, n=3):
    """AI 그림 n장이 있는 job 과 assets 항목(품질 검사 직전 상태)."""
    from recap_shorts import pipeline as P
    from tests.pipeline.fakes import png
    job = P.JobStore(tmp_path).create({"gallery": "dcbest", "no": 1, "url": "u"})
    entries = []
    for i in range(n):
        f = job.dir / "assets" / "ai" / f"ai_{i:02d}.png"
        png(f)
        entries.append({"file": f"assets/ai/ai_{i:02d}.png", "kind": "ai", "sentence": i, "status": "ok",
                        "hint": f"장면 {i}", "prompt_en": f"scene {i}"})
    return job, entries


class QualityDeps:
    """image_quality 답을 차례로 돌려주고, 받은 그림 목록을 남기는 가짜."""
    def __init__(self, answers, gen_ok=True):
        from tests.pipeline.fakes import FakeDeps
        self.base, self.answers, self.gen_ok, self.asked = FakeDeps(), list(answers), gen_ok, []

    def image_quality(self, paths, hints):
        self.asked.append([p.name for p in paths])
        ans = self.answers.pop(0)
        return quality.review(paths, hints, read_fn=_fake(ans))

    def generate_image(self, prompt, out_png):
        if not self.gen_ok:
            return {"ok": False, "error": "server down"}
        return self.base.generate_image(prompt, out_png)


def test_regenerated_images_are_checked_again(tmp_path):
    """다시 만든 장만 한 번 더 검사하고, 결함이 남은 장은 다시 만들기 추천 + 이유(빈 격자 표가 남은 경우)."""
    from recap_shorts import pipeline as P
    job, entries = _job(tmp_path)
    first = {"items": [{"i": 1}, {"i": 2, "artifacts": True, "reason": "튜브 성분표가 빈 격자"},
                       {"i": 3, "fake_text": True}], "worst": [2]}
    again = {"items": [{"i": 1, "artifacts": True, "reason": "격자 표가 그대로"}, {"i": 2}], "worst": []}
    deps = QualityDeps([first, again])
    P._quality_pass(P.Ctx(job, "assets", deps), entries)
    assert deps.asked == [["ai_00.png", "ai_01.png", "ai_02.png"], ["ai_01.png", "ai_02.png"]]
    still, fixed = entries[1], entries[2]
    assert still["recommend_regenerate"] and still["review_reason"].startswith("다시 만들어도 결함 남음(뭉개진 AI 티)")
    assert "격자 표가 그대로" in still["review_reason"] and still["quality_before"]["artifacts"]
    assert not fixed.get("recommend_regenerate") and fixed["quality"]["fake_text"] is False
    assert not entries[0].get("recommend_regenerate")
    sub = next(x for x in job.step("assets")["sub"] if x["label"] == "이미지 품질")
    assert sub["note"] == "결함 2장 → 다시 만듦 2장 · 그래도 남음 1장"


def test_recheck_failure_or_failed_redo_is_flagged(tmp_path):
    """다시 검사가 실패하거나 다시 만들기 자체가 실패하면, 결함이 남았을 수 있으니 표시한다."""
    from recap_shorts import pipeline as P
    first = {"items": [{"i": 1, "blank_screen": True}, {"i": 2}], "worst": []}
    job, entries = _job(tmp_path / "a", 2)
    deps = QualityDeps([first, {"nope": 1}])
    P._quality_pass(P.Ctx(job, "assets", deps), entries)
    assert entries[0]["recommend_regenerate"] and "검사 못 함" in entries[0]["review_reason"]
    assert "빈 화면" in entries[0]["review_reason"]

    job, entries = _job(tmp_path / "b", 2)
    deps = QualityDeps([first], gen_ok=False)
    P._quality_pass(P.Ctx(job, "assets", deps), entries)
    assert len(deps.asked) == 1                                  # 다시 만든 장이 없으면 다시 검사도 없음
    assert entries[0]["recommend_regenerate"] and entries[0]["review_reason"].startswith("다시 만들기 실패")
