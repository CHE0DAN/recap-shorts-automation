"""Clef 모듈 시험: 네트워크 없이(가짜 응답)."""
import base64
import io
import json

import pytest

from recap_shorts.clef import client as c
from recap_shorts.clef import evalres, inspect as insp, match as M, questions as Q, triage as T


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("RECAP_CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("RECAP_CF_API_TOKEN", "tok-secret")
    evalres.set_results({})          # 실제 eval_results.json 이 아니라 빈 결과(= 모두 usable 아님)에서 시작
    monkeypatch.setattr(c.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    c.METER.reset()
    c.METER.budget = None
    yield
    evalres.set_results(None)


def usable(*keys, **extra):
    return {"questions": {k: {"usable": True, **extra.get(k, {})} for k in keys}}


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.text = json.dumps(body if body is not None else {})


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json)
        return self.responses.pop(0)


def ok_body(questions, value=0.7, tokens=1000):
    ans = {}
    for k, q in questions.items():
        if q["type"] == "noul":
            ans[k] = {"type": "noul", "noul": value}
        elif q["type"] == "choice":
            opts = list(q["criteria"])
            ans[k] = {"type": "choice", "choice": opts[0],
                      "probabilities": {opts[0]: 0.8, **{o: 0.2 / (len(opts) - 1) for o in opts[1:]}}}
        else:
            ans[k] = {"type": "score", "score": 2.0}
    return {"success": True, "result": {"answers": ans, "usage": {"input_tokens": tokens}}}


# ---------------------------------------------------------------- 질문 만들기·검사
def test_question_builders():
    assert c.yes_no("q", yes="a")["criteria"] == {"true": "a"}
    assert c.choice("q", {"x": "1", "y": "2"})["type"] == "choice"
    assert c.score("q", ["a", "b"])["criteria"] == ["a", "b"]


@pytest.mark.parametrize("bad", [{}, {"bad id!": c.yes_no("q")}, {"a": {"type": "noul"}},
                                 {"a": c.choice("q", {"only": "1"})}, {"a": c.score("q", ["x"])}])
def test_check_rejects(bad):
    with pytest.raises(c.ClefError):
        c._check(bad)


def test_too_many_questions():
    with pytest.raises(c.ClefError):
        c._check({f"q{i}": c.yes_no("q") for i in range(65)})


def test_image_and_size_checks(tmp_path):
    big = tmp_path / "a.png"
    big.write_bytes(b"x" * (c.MAX_IMAGE_BYTES + 1))
    with pytest.raises(c.ClefError):
        c._data_url(big, "image", c.MAX_IMAGE_BYTES, shrink=False)
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a")
    with pytest.raises(c.ClefError):
        c._data_url(gif, "image", c.MAX_IMAGE_BYTES)
    with pytest.raises(c.ClefError):                     # 영상을 소리 칸에
        c._data_url((b"x", "video/mp4"), "audio", c.MAX_AUDIO_BYTES)


def test_image_is_shrunk(tmp_path):
    from PIL import Image
    p = tmp_path / "big.png"
    Image.new("RGBA", (2000, 1000), (255, 0, 0, 0)).save(p)
    url = c._data_url(p, "image", c.MAX_IMAGE_BYTES)
    assert url.startswith("data:image/jpeg;base64,")
    im = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(im.size) <= c.IMAGE_MAX_SIDE


def test_ask_parses_and_counts_neurons():
    qs = {"a": c.yes_no("q"), "b": c.choice("q", {"x": "1", "y": "2"}), "s": c.score("q", ["l", "m", "h"])}
    fc = FakeClient([Resp(200, ok_body(qs, tokens=1000))])
    u = {}
    got = c.ask(qs, client=fc, usage=u)
    assert got["a"].value == 0.7 and got["b"].value == "x" and got["s"].value == 2.0
    assert u["input_tokens"] == 1000 and u["neurons"] == pytest.approx(13.64, abs=0.01)
    assert c.METER.neurons == pytest.approx(13.636, abs=0.01)


def test_ask_rejects_wrong_answer_kind():
    qs = {"a": c.yes_no("q")}
    fc = FakeClient([Resp(200, {"success": True, "result": {"answers": {"a": {"type": "noul", "noul": "yes"}}}})])
    with pytest.raises(c.ClefError):
        c.ask(qs, client=fc)


def test_retry_once_on_429(monkeypatch):
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    qs = {"a": c.yes_no("q")}
    fc = FakeClient([Resp(429, {"success": False, "errors": [{"code": 3040, "message": "busy"}]}), Resp(200, ok_body(qs))])
    u = {}
    c.ask(qs, client=fc, usage=u)
    assert len(fc.calls) == 2 and u["attempts"] == 2


def test_daily_limit_not_retried(monkeypatch):
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    qs = {"a": c.yes_no("q")}
    fc = FakeClient([Resp(429, {"success": False, "errors": [{"code": 3036, "message": "daily"}]}), Resp(200, ok_body(qs))])
    with pytest.raises(c.DailyLimitError):
        c.ask(qs, client=fc)
    assert len(fc.calls) == 1


def test_token_not_in_error():
    qs = {"a": c.yes_no("q")}
    fc = FakeClient([Resp(400, {"success": False, "errors": [{"code": 1, "message": "bad tok-secret here"}]})])
    with pytest.raises(c.ClefError) as e:
        c.ask(qs, client=fc)
    assert "tok-secret" not in str(e.value)


def test_budget_guard():
    c.METER.budget = 5
    c.METER.add(1000)
    with pytest.raises(c.ClefError):
        c.ask({"a": c.yes_no("q")}, client=FakeClient([]))


def test_not_configured(monkeypatch):
    monkeypatch.setenv("RECAP_CF_ACCOUNT_ID", "")
    monkeypatch.setenv("RECAP_CF_API_TOKEN", "")
    assert c.credentials() == ("", "")          # 시험 설정 파일(tests/conftest.py)은 비어 있다
    assert not c.configured()
    with pytest.raises(c.ClefError):
        c.ask({"a": c.yes_no("q")})


# ---------------------------------------------------------------- assign
def test_assign_no_overlap_and_counts():
    mat = [[0.9 if (i, j) in {(0, 0), (0, 1), (0, 2), (1, 3), (1, 4), (1, 5), (2, 6), (2, 7)} else 0.1
            for j in range(8)] for i in range(3)]
    a = M.assign(mat, (2, 3), allow_reuse=False)
    flat = [j for js in a.values() for j in js]
    assert len(flat) == len(set(flat))
    assert all(2 <= len(js) <= 3 for js in a.values())
    assert set(a["0"]) <= {0, 1, 2} and set(a["1"]) <= {3, 4, 5}


def test_assign_hungarian_beats_greedy():
    # 탐욕이면 문장0이 그림0(0.9)을 가져가고 문장1은 0.1; 헝가리안은 (0->1, 1->0) 합 1.65
    a = M.assign([[0.9, 0.8], [0.85, 0.1]], (1, 1))
    assert a == {"0": [1], "1": [0]}


def test_assign_reuse_and_few_images():
    a = M.assign([[0.9, 0.1], [0.8, 0.2]], (2, 2), allow_reuse=True)
    assert sorted(a["0"]) == [0, 1] and sorted(a["1"]) == [0, 1]
    a = M.assign([[0.9], [0.8], [0.7]], (1, 1))          # 그림이 모자라면 일부 문장은 비어 있음
    assert sum(len(v) for v in a.values()) == 1


def test_assign_sorted_by_score_desc():
    assert M.assign([[0.2, 0.9, 0.5]], (3, 3))["0"] == [1, 2, 0]


# ---------------------------------------------------------------- usable 처리
def test_unusable_returns_none(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    assert M.fit_matrix(["문장"], [img]) is None
    assert M.plan(["문장"], [img]) is None
    assert T.triage([{"no": 1, "title": "t", "text": "", "image": None}]) is None
    assert insp.inspect_image(img) is None
    assert insp.voice_says(img, "문장") is None


def test_fit_matrix_uses_only_usable_variants(monkeypatch, tmp_path):
    evalres.set_results(usable("match.A"))
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    seen = []

    def fake_ask(qs, **kw):
        seen.append(qs)
        return {k: c.Answer("noul", 0.25 if k == "s0" else 0.75) for k in qs}
    monkeypatch.setattr(c, "ask", fake_ask)
    m = M.fit_matrix(["a", "b", "c"], [img, img])
    assert len(seen) == 2 and len(seen[0]) == 3          # 그림당 1 요청, 문장 3개 묶음
    assert m == [[0.25, 0.25], [0.75, 0.75], [0.75, 0.75]]
    p = M.plan(["a", "b", "c"], [img, img], per_sentence=(1, 1), allow_reuse=True, matrix=m)
    assert set(p["plan"]) == {"0", "1", "2"} and all(isinstance(v[0], str) for v in p["plan"].values())


def test_fit_matrix_failed_image_filled(monkeypatch, tmp_path):
    evalres.set_results(usable("match.A"))
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"x")

    def fake_ask(qs, images=(), **kw):
        if str(images[0]).endswith("b.png"):
            raise c.ClefError("boom")
        return {k: c.Answer("noul", 0.9) for k in qs}
    monkeypatch.setattr(c, "ask", fake_ask)
    assert M.fit_matrix(["s"], [a, b]) == [[0.9, 0.5]]


def test_triage_output_and_threshold(monkeypatch):
    keys = ["triage.category.A", "triage.category.B", "triage.risk.sexual.A", "triage.risk.sexual.B"]
    evalres.set_results(usable(*keys, **{"triage.risk.sexual.A": {"threshold": 0.2},
                                         "triage.risk.sexual.B": {"threshold": 0.2}}))
    calls = []

    def fake_ask(qs, state="", images=(), **kw):
        calls.append(bool(images))
        risky = "BAD" in state
        out = {}
        for k, q in qs.items():
            if q["type"] == "choice":
                out[k] = c.Answer("choice", "politics", {"politics": 0.7, "sports": 0.3})
            else:
                out[k] = c.Answer("noul", 0.3 if risky else 0.05)
        return out
    monkeypatch.setattr(c, "ask", fake_ask)
    r = T.triage([{"no": 1, "title": "BAD", "text": "x", "image": "p.png"},
                  {"no": 2, "title": "fine", "text": "", "image": "p.png"}])
    assert r[0]["hidden"] is True and r[0]["hidden_by"] == ["sexual"] and r[0]["risks"]["person_attack"] is None
    assert r[0]["asked_twice"] is True and r[0]["interest"] is None
    assert r[0]["category"]["politics"] == pytest.approx(0.7)
    assert r[1]["hidden"] is False
    # 위험 글은 그림 2차를 생략, 평범한 글은 2차(그림 포함)를 한다
    assert sorted(calls) == [False, False, True]


def test_triage_one_failure_isolated(monkeypatch):
    evalres.set_results(usable("triage.category.A"))

    def fake_ask(qs, state="", **kw):
        if "boom" in state:
            raise c.ClefError("x")
        return {k: c.Answer("choice", "sports", {"sports": 1.0}) for k in qs}
    monkeypatch.setattr(c, "ask", fake_ask)
    r = T.triage([{"no": 1, "title": "boom"}, {"no": 2, "title": "ok"}])
    assert "error" in r[0] and r[1]["category"] == {"sports": 1.0}


def test_inspect_image_partial(monkeypatch, tmp_path):
    evalres.set_results(usable("inspect.text_or_logo.A", "inspect.text_or_logo.B"))
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(c, "ask", lambda qs, **kw: {k: c.Answer("noul", 0.9) for k in qs})
    assert insp.inspect_image(img, "ai") == {"face": None, "personal_text": None, "text_or_logo": 0.9, "real_person_like": None}
    with pytest.raises(ValueError):
        insp.inspect_image(img, "x")


def test_voice_says(monkeypatch, tmp_path):
    evalres.set_results(usable("voice.A"))
    w = tmp_path / "a.wav"
    w.write_bytes(b"x")
    monkeypatch.setattr(c, "ask", lambda qs, **kw: {k: c.Answer("noul", 0.8) for k in qs})
    assert insp.voice_says(w, "문장") == 0.8


def test_evalres_file_missing_means_unusable(monkeypatch, tmp_path):
    monkeypatch.setattr(evalres, "PATH", tmp_path / "none.json")
    evalres._cache = None
    assert not evalres.is_usable("match.A")
    assert evalres.threshold("x") == 0.5


def test_watch_questions():
    assert "topic_match" in Q.watch_questions(True) and "topic_match" not in Q.watch_questions(False)
    assert "caption_cut" in Q.watch_questions(False)
