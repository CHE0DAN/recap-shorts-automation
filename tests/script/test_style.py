"""F3·F4 말투 숫자 검사(guard.check_style)·F10 인용 검사(check_quotes) — 경고만 남기고 막지 않는다."""
from recap_shorts.script.guard import _is_hearsay, check_quotes, check_style
from recap_shorts.script.text import normalize_loose


def test_hearsay_endings_counted_but_not_nouns():
    for w in ["식었대", "처참하대", "먹으래", "달렸대", "생각난다더라", "올라왔다는데", "했대요"]:
        assert _is_hearsay(w), w
    for w in ["세대", "반대", "미래", "침대", "무대", "흥건했어", "짜거든", "있었지"]:
        assert not _is_hearsay(w), w


def test_style_flags_over_limits():
    texts = ["시장 골목이 사라진다니 동네 사람들이 화가 났대.", "근데 점심 약속은 늘 겹쳤어.",
             "심지어 손님 수가 절반으로 줄어들었대.", "반면 소문만 퍼져 나간다는 말도 있었지.", "그래도 간판은 예쁘게 달렸대.",
             "노점 편이 더 많았대."]
    check, flags = check_style(texts)
    assert check["hearsay"] == [1, 3, 5, 6]
    assert check["flourish"] == {"심지어": 1, "반면": 1}
    assert check["openers"] == [2, 3, 4, 5]
    assert not check["ok"] and len(flags) == 3      # 전해 들은 꼴(4번 > 3), 꾸밈 연결어, 첫머리 접속사 ('근데' 1번은 통과)


def test_style_ok_within_limits():
    texts = ["시장 골목까지 다니며 물건을 팔았어.", "점심은 늘 김밥으로 대충 때웠는데, 국물까지 흥건했어.",
             "결국 댓글에선 노점 편이 더 많았대.", "다들 그 차이를 놓치더라."]
    check, flags = check_style(texts)
    assert flags == [] and check["ok"]
    assert check["haera"] == [] and check["hearsay"] == [3, 4]


def test_haera_mixed_into_banmal_is_flagged():
    """반말 사이에 '~했다·~한다고 한다'가 끼면 경고."""
    texts = ["주차 자리 때문에 이웃과 다퉜더니, 관리인은 규정만 들먹이며 받아쳤다.", "이 글에 달린 댓글들이 전부 같은 사람이라는 거야.",
             "결국 게시판에 사과 글을 올린 뒤에 글은 내렸다고 한다."]
    check, flags = check_style(texts)
    assert check["haera"] == [1, 3]
    assert any("'~다' 끝맺음 2번" in f for f in flags)


def test_quotes_must_be_in_source():
    src = normalize_loose("관리인 2개월 전, 수정됨\n한 번만 봐주세요\n주차는 안 돼요!!!\n공지는 계속 올립니다")
    ok, flags = check_quotes(["댓글엔 관리인이 '한 번만 봐주세요' 한 마디만 달았어.", "‘주차는 안 돼요!!! 공지는 계속 올립니다’라고 했지."], src)
    assert ok["ok"] and ok["count"] == 2 and flags == []
    bad, flags = check_quotes(["관리인은 '다신 오지 마세요'라고 했어."], src)
    assert not bad["ok"] and bad["missing"] == [{"sentence": 1, "quote": "다신 오지 마세요"}] and len(flags) == 1
