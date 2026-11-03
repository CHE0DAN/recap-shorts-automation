"""같은 문장 안 그림 경계를 사람이 끌어 옮긴 컷(shot_plan.json "cuts") — timeline.build · fx.fit_before_meme.

경계를 끌어 샷 길이를 바꾸고, 저장하면 영상에 그대로 반영된다.
timings 는 손으로 적는다(fake 목소리 4문장 3.0초씩 0.1초부터 — tests/pipeline/fakes.py 와 같은 꼴).
"""
import json

from recap_shorts import timeline as T
from recap_shorts.fx.apply import fit_before_meme

SCRIPT = {"title_lines": ["a", "b"], "hook": "훅 문장", "sentences": [{"emphasis": ""}] * 4}


def timings(sents=None, duration=12.6):
    """sents: [(role, start, end)] 아니면 훅 0.1~3.1 + 본문 3문장 3.1초씩."""
    sents = sents or [("hook", 0.1, 3.1), ("body", 3.2, 6.2), ("body", 6.3, 9.3), ("closing", 9.4, 12.4)]
    return {"duration": duration,
            "sentences": [{"index": i, "role": r, "start": a, "end": b, "text": f"문장 {i} 어절 둘"}
                          for i, (r, a, b) in enumerate(sents)]}


PLAN = {"0": ["h.png"], "1": ["a1.png", "a2.png"], "2": ["b1.png", "b2.png", "b3.png"], "3": ["c1.png", "c2.png"]}


def build(cuts=None, tm=None, plan=None, word_cuts=None):
    return T.build(SCRIPT, tm or timings(), plan or PLAN, voice="voice/voice.wav", word_cuts=word_cuts, cuts=cuts)


def sent_of(tl, idx):
    return [s for s in tl["shots"] if s["file"] in PLAN[str(idx)]]


def test_sentence_spans_hook_to_first_body_and_tail():
    spans = T.sentence_spans(timings())
    assert spans[0] == (0.0, 3.2)          # 훅은 0초부터 첫 본문 문장 시작까지
    assert spans[1] == (3.2, 6.3)
    assert spans[2] == (6.3, 9.4)
    assert spans[3] == (9.4, 13.05)        # 마지막은 duration + tail(0.45)


def test_user_cuts_are_used_as_given():
    span = T.sentence_spans(timings())[2]
    cuts = {"2": {"t": [7.1, 8.6], "span": list(span)}}
    tl = build(cuts)
    got = [(s["start"], s["end"]) for s in sent_of(tl, 2)]
    assert got == [(6.3, 7.1), (7.1, 8.6), (8.6, 9.4)]
    assert all(s.get("cut") == "user" for s in sent_of(tl, 2))
    assert all("cut" not in s for s in sent_of(tl, 1))       # 다른 문장은 그대로
    # 사람이 옮긴 문장은 자막을 컷에 맞추라고 하므로 breaks 를 만들지 않는다
    assert all("breaks" not in json.dumps(c) for c in tl["captions"])
    assert tl["options"]["snap_captions_to_cuts"] is True


def test_user_cuts_scale_when_sentence_span_changed():
    # 저장할 때는 6.3~9.4(3.1초). 목소리를 다시 녹음해 지금은 6.3~8.2(1.9초)
    tm = timings([("hook", 0.1, 3.1), ("body", 3.2, 6.2), ("body", 6.3, 8.1), ("closing", 8.2, 11.2)], duration=11.4)
    cuts = {"2": {"t": [7.1, 8.6], "span": [6.3, 9.4]}}
    tl = build(cuts, tm=tm)
    assert T.sentence_spans(tm)[2] == (6.3, 8.2)
    starts = [s["start"] for s in sent_of(tl, 2)]
    # (7.1-6.3)*1.9/3.1 = 0.49 → 6.79 / (8.6-6.3)*1.9/3.1 = 1.41 → 7.71
    assert starts == [6.3, 6.79, 7.71]
    assert sent_of(tl, 2)[-1]["end"] == 8.2
    assert all(s["cut"] == "user" for s in sent_of(tl, 2))


def test_unusable_cuts_fall_back_to_automatic():
    span = T.sentence_spans(timings())[2]
    auto = [(s["start"], s["end"]) for s in sent_of(build(), 2)]
    bad = [
        {"t": [7.1], "span": list(span)},                          # 개수 다름(그림 3장인데 1개)
        {"t": [8.6, 7.1], "span": list(span)},                     # 순서 뒤집힘
        {"t": [6.35, 8.6], "span": list(span)},                    # 첫 샷 0.05초 → 0.4초 미만
        {"t": [7.1, 8.6]},                                         # span 없음 → 지금 구간 그대로 쓰면 되므로 이건 쓴다(아래)
    ]
    for entry in bad[:3]:
        tl = build({"2": entry})
        assert [(s["start"], s["end"]) for s in sent_of(tl, 2)] == auto
        assert all("cut" not in s for s in sent_of(tl, 2))     # 자동으로 돌아갔으므로 표시 없음
    assert [s["start"] for s in sent_of(build({"2": bad[3]}), 2)] == [6.3, 7.1, 8.6]   # span 없으면 지금 구간에 그대로
    # 엉뚱한 꼴(목록·문자열 시각)은 자동, span 이 망가진 값이면 span 을 무시하고 시각만 쓴다
    for weird in ({"2": [7.1, 8.6]}, {"2": {"t": ["a", "b"], "span": [6.3, 9.4]}}):
        assert [(s["start"], s["end"]) for s in sent_of(build(weird), 2)] == auto
    assert [s["start"] for s in sent_of(build({"2": {"t": [7.1, 8.6], "span": "x"}}), 2)] == [6.3, 7.1, 8.6]


def test_user_cuts_do_not_touch_word_cut_breaks_of_other_sentences():
    class FakeWC:
        """다른 문장(1번)의 어절 경계는 그대로 고른 것처럼 — 2번 문장은 부르지 않아야 한다."""
        def __init__(self):
            self.calls = []

        def choose(self, index, start, end, n):
            self.calls.append(index)
            return None

        def text_k(self, index, k, tw):
            return k

    wc = FakeWC()
    span = T.sentence_spans(timings())[2]
    build({"2": {"t": [7.1, 8.6], "span": list(span)}}, word_cuts=wc)
    assert wc.calls == [1, 3]     # 2번은 사용자 컷 → 자동 고르기를 부르지 않는다


def test_fit_before_meme_keeps_user_cut_shots():
    """짤 단계가 사람이 옮긴 경계를 다시 나누거나 빼지 않는다 — 짤만 끼운다(겹치는 샷만 잘림)."""
    sents = [{"index": 0, "role": "hook", "start": 0.0}, {"index": 1, "role": "body", "start": 2.0},
             {"index": 2, "role": "body", "start": 6.0}]
    shots = [{"file": "h.png", "start": 0.0, "end": 2.0},
             {"file": "c1.png", "start": 2.0, "end": 3.4, "cut": "user"},
             {"file": "c2.png", "start": 3.4, "end": 4.6, "cut": "user"},
             {"file": "c3.png", "start": 4.6, "end": 6.0, "cut": "user"},
             {"file": "n.png", "start": 6.0, "end": 8.0}]
    meme = {"kind": "meme", "file": "m.png", "start": 4.4, "end": 6.0}
    out = fit_before_meme(shots, sents, meme, min_len=0.9)
    # 다시 나누지 않는다: c1/c2 는 그대로, 짤과 겹치는 부분만 잘리고 c3 는 짤에 완전히 덮인다
    got = [(s["file"], s["start"], s["end"]) for s in out]
    assert got == [("h.png", 0.0, 2.0), ("c1.png", 2.0, 3.4), ("c2.png", 3.4, 4.4),
                   ("m.png", 4.4, 6.0), ("n.png", 6.0, 8.0)]
    assert [s["cut"] for s in out if s["file"].startswith("c")] == ["user", "user"]


def test_fit_before_meme_still_respreads_automatic_sentences():
    sents = [{"index": 0, "role": "hook", "start": 0.0}, {"index": 1, "role": "body", "start": 2.0}]
    shots = [{"file": "h.png", "start": 0.0, "end": 2.0},
             {"file": "c1.png", "start": 2.0, "end": 6.0},       # 자동 컷 하나 → 다시 나눠야 함
             {"file": "c2.png", "start": 6.0, "end": 8.0}]
    meme = {"kind": "meme", "file": "m.png", "start": 4.0, "end": 6.0}
    out = fit_before_meme(shots, sents, meme, min_len=0.9)
    assert [(s["file"], s["start"], s["end"]) for s in out] == [
        ("h.png", 0.0, 2.0), ("c1.png", 2.0, 4.0), ("m.png", 4.0, 6.0), ("c2.png", 6.0, 8.0)]
