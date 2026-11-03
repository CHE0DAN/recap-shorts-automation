import pytest

from recap_shorts.render import captions as cap
from recap_shorts.render import layout as L

S = [
    {"text": "알고 보니 포수가 장난으로 공을 두 개 줬대", "start": 3.0, "end": 6.0, "emphasis": "두 개"},
    {"text": "심판도 한참 어이없어 하더니 결국 웃음이 터졌고", "start": 6.0, "end": 9.5, "emphasis": "심판도"},
    {"text": "그래서 사람이 더 늘었다는데", "start": 9.5, "end": 11.5, "emphasis": None},
]


def test_syllable_range_and_words_preserved():
    cards = cap.make_cards(S, measure=False)
    for s in S:
        mine = [c for c in cards if s["start"] - 1e-6 <= c["start"] < s["end"] - 1e-6]
        assert " ".join(c["text"] for c in mine) == s["text"]  # 어절 보존, 순서 유지
        assert len(mine) >= 1
        for c in mine:  # 어절 단위라 6~10 을 한두 음절 벗어날 수 있다
            assert 5 <= cap.syllables(c["text"]) <= 11 or len(mine) == 1, c
    sy = [cap.syllables(c["text"]) for c in cards]
    assert sum(1 for x in sy if 6 <= x <= 10) / len(sy) >= 0.7


def test_times_cover_sentence_and_min_len():
    cards = cap.make_cards(S, measure=False)
    for s in S:
        mine = [c for c in cards if s["start"] - 1e-6 <= c["start"] < s["end"] - 1e-6]
        assert mine[0]["start"] == pytest.approx(s["start"], abs=1e-3)
        assert mine[-1]["end"] == pytest.approx(s["end"], abs=1e-3)
        assert sum(c["end"] - c["start"] for c in mine) == pytest.approx(s["end"] - s["start"], abs=1e-2)
        for a, b in zip(mine, mine[1:]):
            assert a["end"] == pytest.approx(b["start"], abs=1e-3)
        for c in mine:
            assert c["end"] - c["start"] >= 0.6 - 1e-3


def test_no_split_inside_word():
    text = "프로야구선수협회가 발표했다는데"
    cards = cap.make_cards([{"text": text, "start": 0, "end": 4, "emphasis": None}], measure=False)
    words = text.split()
    got = [w for c in cards for w in c["text"].split()]
    assert got == words


def test_emphasis_only_in_matching_card():
    cards = cap.make_cards(S[:1], measure=False)
    with_e = [c for c in cards if c["emphasis"]]
    assert all("두 개" in c["text"] for c in with_e)
    assert len(with_e) == 1


def test_short_sentence_one_card():
    cards = cap.make_cards([{"text": "와", "start": 0, "end": 0.4, "emphasis": None}], measure=False)
    assert len(cards) == 1


def test_fit_two_lines_max():
    for text in ["알고 보니 포수가 장난으로", "아주아주긴낱말하나가 또다른긴낱말둘이", "가나다라마바 사아자차카타 파하"]:
        fit = cap.fit_text(text)
        if fit:
            size, lines, _ = fit
            assert len(lines) <= 2
            assert size >= L.CAPTION_SIZE_MIN
            for ln in lines:
                assert L.load_font(size).getlength(ln) + 12 <= L.TEXT_MAX_W + 1e-6


def test_long_card_gets_split_when_not_fitting():
    # 한 카드가 폭에 안 들어갈 만큼 긴 어절들 -> 더 쪼개 모든 카드가 맞아야 한다
    text = " ".join(["대한민국프로야구"] * 6)
    cards = cap.make_cards([{"text": text, "start": 0, "end": 12, "emphasis": None}], measure=True)
    assert len(cards) > 1
    for c in cards:
        assert cap.fit_text(c["text"]) is not None
    assert " ".join(c["text"] for c in cards) == text


# 자막 카드가 '안/못/생각해 낸' 같은 데서 끊기지 않게
def _texts(text, dur=4.0):
    return [c["text"] for c in cap.make_cards([{"text": text, "start": 0.0, "end": dur}], measure=False)]


def _no_glued_break(cards):
    from recap_shorts.render.captions import glued
    ws = [c.split() for c in cards]
    return not any(glued(a[-1], b[0]) for a, b in zip(ws, ws[1:]))


def test_glued_rules():
    from recap_shorts.render.captions import glued
    for a, b in [("안", "주고,"), ("못", "구하면"), ("생각해", "낸"), ("새", "세입자를"), ("기다려주기만", "하면"),
                 ("할", "수"), ("없다는", "거야."), ("필기할", "때"), ("기존", "세입자가"), ("하고", "있어")]:
        assert glued(a, b), (a, b)
    for a, b in [("주고,", "그걸로"), ("그래서", "내가"), ("세입자가", "그때까지"), ("날렸다는", "집주인의")]:
        assert not glued(a, b), (a, b)


def test_cards_keep_glued_words_together():
    for text in ["새 세입자 3억은 기존 세입자한테 안 주고, 그걸로 주식해서 3억을 벌겠대.",
                 "계약은 내년 2월에 끝나는데, 새 세입자를 못 구하면 돌려줄 돈이 없대.",
                 "근데 이 집주인이 생각해 낸 해결책이 진짜 황당해.",
                 "심지어 기존 세입자가 그때까지 기다려주기만 하면 피해자가 아무도 없다는 거야.",
                 "댓글을 보니까 창문이 오른쪽에 있으면 필기할 때 손 그림자가 글씨를 가려서 그렇다더라."]:
        cards = _texts(text)
        assert " ".join(cards) == text and _no_glued_break(cards), cards


def test_fit_text_line_break_avoids_glued_words():
    from recap_shorts.render.captions import glued
    r = cap.fit_text("세입자한테 안 주고 그걸로 주식해서", max_w=420)
    assert r is not None and len(r[1]) == 2
    l1, l2 = r[1]
    assert not glued(l1.split()[-1], l2.split()[0])
