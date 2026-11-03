"""F9 우리 해석(take): 프롬프트 규칙, take 필드 보존, 가드 flag(경고만), 다듬기 후에도 유지."""
import json
from pathlib import Path

from recap_shorts.script.guard import TAKE_COPY_MAX, as_bool, copy_ratio, run_guard
from recap_shorts.script.pipeline import normalize_script, refine_script
from recap_shorts.script.prompt import SCHEMA, build_prompt
from recap_shorts.script.refine import build_refine_prompt, merge_refined

FIX = Path(__file__).parents[1] / "fixtures" / "script"
TOPIC = json.loads((FIX / "topic_sample.json").read_text(encoding="utf-8"))

# topic_sample 원문에서 그대로 따온 구절 (evidence 용, 10~60자)
EV1 = "상대팀 투수가 갑자기 쥐가 나서 마운드에서 주저앉음"
EV2 = "그런데 이게 너무 느려서 타자들이 타이밍을 못 맞추고 연속 삼진 두 개가 나옴"
EV3 = "경기 끝나고 할아버지가 아이스크림 열두 개를 사 주셨음"

RETELL1 = "상대 투수가 갑자기 쥐가 나서 마운드에서 주저앉았대."
RETELL2 = "공이 너무 느려서 타자들이 타이밍을 못 맞추고 삼진 두 개가 나왔어."
# 우리 해석: 원문에 없는 생각(정리·관점). 숫자·영문·따옴표 없음
TAKE_OK = "내 눈엔 빠른 공보다 느린 공이 먹힌 게 이 경기의 진짜 반전이야."
# 해석이라고 달았지만 원문 문장을 그대로 읽은 것
TAKE_COPY = "경기 끝나고 할아버지가 아이스크림 열두 개를 사 주셨음"


def S(text, ev=None, take=None, hint="일러스트"):
    s = {"text": text, "evidence": ev, "source_id": None, "emphasis": None, "image_hint": hint}
    if take is not None:
        s["take"] = take
    return s


def script(sents, closing="이게 말이 되냐 진짜"):
    return {"title_lines": ["동네 야구에서", "생긴 황당한 일"], "hook": "의외로 느린 공이 먹혔다는 동호회 경기 근황",
            "sentences": sents, "closing": closing, "flags": []}


def take_flags(chk):
    return [f for f in chk["flags"] if "해석" in f]


# ------------------------------------------------------------------ 프롬프트·스키마

def test_prompt_has_f9_and_take_schema():
    p = build_prompt(TOPIC)
    for must in ("F9.", "우리 해석", "정리·맥락·비교·관점", '"take": true', "재사용 콘텐츠", "closing 은 F8 대로 반응 한 마디"):
        assert must in p, must
    assert '"take"' in SCHEMA


def test_refine_prompt_keeps_take():
    p = build_refine_prompt(TOPIC, script([S(RETELL1, EV1, take=False)]))
    assert "F1~F11" in p and "take" in p and '"take": false' in p


def test_normalize_keeps_take_only_when_present():
    out = normalize_script({"sentences": [S("가나다", take=True), S("라마바", take="false"), S("사아자")]})
    s = out["sentences"]
    assert s[0]["take"] is True and s[1]["take"] is False and "take" not in s[2]      # 필드 없는 옛 대본은 없는 채로
    assert as_bool("true") and as_bool(1) and not as_bool("false") and not as_bool(None)


# ------------------------------------------------------------------ 가드: 표시한 문장

def test_marked_original_take_passes():
    sc = script([S(RETELL1, EV1, take=False), S(RETELL2, EV2, take=False), S(TAKE_OK, take=True)])
    out, chk = run_guard(sc, TOPIC)
    t = chk["checks"]["take"]
    assert t["ok"] and t["mode"] == "marked" and t["counted"] == [3]
    assert not take_flags(chk)
    assert out["sentences"][2]["take"] is True                 # 가드를 거쳐도 필드가 남는다


def test_marked_copy_of_source_is_flagged():
    sc = script([S(RETELL1, EV1, take=False), S(TAKE_COPY, EV3, take=True)])
    out, chk = run_guard(sc, TOPIC)
    assert not chk["checks"]["take"]["ok"]
    (f,) = take_flags(chk)
    assert "2번 문장" in f and "겹침" in f and "독창적" in f
    assert not chk["ok"] and len(out["sentences"]) == 2          # 경고만: 문장은 지우지 않는다


def test_too_short_take_is_flagged():
    _, chk = run_guard(script([S(RETELL1, EV1, take=False), S("진짜 웃기지?", take=True)]), TOPIC)
    (f,) = take_flags(chk)
    assert "너무 짧음" in f


def test_all_take_false_is_flagged():
    sc = script([S(RETELL1, EV1, take=False), S(RETELL2, EV2, take=False), S(TAKE_OK, take=False)])
    _, chk = run_guard(sc, TOPIC)
    assert chk["checks"]["take"]["mode"] == "unmarked"
    assert take_flags(chk) == [f for f in chk["flags"] if f.startswith("우리 해석 문장이 없음")]
    assert "독창적이지 않음" in take_flags(chk)[0]


def test_deleted_take_sentence_is_explained():
    # 숫자가 들었는데 근거가 없는 해석 문장 -> 기존 사실 가드가 지우고, 해석이 없어졌음을 알린다
    sc = script([S(RETELL1, EV1, take=False), S("내 눈엔 72살 할아버지가 던진 게 핵심이야.", take=True)])
    out, chk = run_guard(sc, TOPIC)
    assert len(out["sentences"]) == 1 and len(chk["deleted"]) == 1
    (f,) = take_flags(chk)
    assert f.startswith("우리 해석 문장이 없음") and "삭제됨" in f


def test_hook_and_closing_never_count_as_take():
    sc = script([S(RETELL1, EV1, take=False), S(RETELL2, EV2, take=False)],
                closing="내 눈엔 이 이야기의 진짜 반전은 느린 공이 먹혔다는 거야")
    _, chk = run_guard(sc, TOPIC)
    assert take_flags(chk)                                       # 끝 한 줄에 의견이 있어도 해석으로 세지 않는다
    legacy = script([S(RETELL1, EV1), S(RETELL2, EV2)], closing="내 눈엔 이 이야기의 진짜 반전은 느린 공이 먹혔다는 거야")
    assert take_flags(run_guard(legacy, TOPIC)[1])


# ------------------------------------------------------------------ 가드: 표시 필드가 없는 대본(옛 대본·손으로 쓴 대본)

def test_legacy_script_without_take_field_all_retelling_is_flagged():
    _, chk = run_guard(script([S(RETELL1, EV1), S(RETELL2, EV2)]), TOPIC)
    assert chk["checks"]["take"]["mode"] == "fallback" and take_flags(chk)


def test_legacy_script_with_own_sentence_is_not_flagged():
    # 근거 없는 긴 문장 + 원문과 안 겹침 -> 사용자가 직접 쓴 해석으로 본다
    _, chk = run_guard(script([S(RETELL1, EV1), S(TAKE_OK)]), TOPIC)
    assert chk["checks"]["take"]["mode"] == "fallback" and chk["checks"]["take"]["counted"] == [2]
    assert not take_flags(chk)


def test_legacy_script_short_reaction_or_copy_is_flagged():
    assert take_flags(run_guard(script([S(RETELL1, EV1), S("대박이다 진짜?")]), TOPIC)[1])
    assert take_flags(run_guard(script([S(RETELL1, EV1), S(TAKE_COPY)]), TOPIC)[1])


# ------------------------------------------------------------------ 겹침 값

def test_copy_ratio_examples():
    src = TOPIC["source_text"]
    assert copy_ratio(TAKE_COPY, src) > 0.9                     # 글자 그대로
    assert copy_ratio(TAKE_OK, src) < TAKE_COPY_MAX             # 직접 쓴 관점
    assert copy_ratio(RETELL1, src) > TAKE_COPY_MAX             # 거의 같은 말로 옮긴 요약은 겹침이 크다
    assert copy_ratio("", src) == 0.0


# ------------------------------------------------------------------ 다듬기

def test_refine_keeps_take_field():
    draft = script([S(RETELL1, EV1, take=False), S(TAKE_OK, take=True)])
    ref = json.loads(json.dumps(draft))
    ref["sentences"][1]["text"] = "내 눈엔 느린 공이 먹힌 게 이 경기의 진짜 반전이지."
    ref["sentences"][1].pop("take")                              # 모델이 필드를 빼먹어도 초안 값을 쓴다
    out, why = merge_refined(draft, ref)
    assert why is None and out["sentences"][1]["take"] is True and out["sentences"][0]["take"] is False


class _LLM:
    def __init__(self, refined):
        self.refined, self.calls = refined, []

    def complete_json(self, prompt):
        return self.refined


def test_refine_reverts_when_take_becomes_a_copy():
    draft, dchk = run_guard(script([S(RETELL1, EV1, take=False), S(TAKE_OK, take=True)]), TOPIC)
    assert dchk["checks"]["take"]["ok"]
    bad = json.loads(json.dumps(draft))
    bad["sentences"][1]["text"] = TAKE_COPY                      # 다듬기가 해석을 원문 복사로 바꿔 버림
    final, fchk, info = refine_script(TOPIC, draft, dchk, _LLM(bad))
    assert not info["applied"] and "해석" in info["error"]
    assert final["sentences"][1]["text"] == TAKE_OK and fchk["checks"]["take"]["ok"]
    good = json.loads(json.dumps(draft))
    good["sentences"][1]["text"] = "내 눈엔 느린 공이 먹힌 게 이 경기의 진짜 반전이지."
    final, fchk, info = refine_script(TOPIC, draft, dchk, _LLM(good))
    assert info["applied"] and final["sentences"][1]["take"] is True and fchk["checks"]["take"]["ok"]
