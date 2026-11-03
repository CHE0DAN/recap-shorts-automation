"""다듬기 패스: 초안 대본을 같은 모델에 다시 보여 "소리 내어 읽었을 때 어색한 곳"만 고치게 한다.

고치는 것은 말투·연결·문장 흐름뿐. 문장 수, evidence, source_id, image_hint, take(우리 해석 표시), 사실(숫자·이름)은 그대로 둔다.
모델이 이를 어기더라도 merge_refined 가 초안의 값으로 되돌린다(문장 수가 다르면 다듬기 결과를 통째로 버림).
"""
from __future__ import annotations

import json

from .prompt import RULES, SCHEMA

KEEP_FIELDS = ("evidence", "source_id", "image_hint", "take")    # merge_refined 는 초안 사본에 글만 덮어써서 이 값들을 그대로 둔다


def build_refine_prompt(topic: dict, draft: dict) -> str:
    src = (topic.get("source_text") or "").strip()
    body = json.dumps(draft, ensure_ascii=False, indent=2)
    return "\n".join([
        "너는 한국어 유튜브 쇼츠 대본 교정자다. 아래 초안을 '소리 내어 읽었을 때 어색한 곳'만 고쳐 다시 쓴다.",
        "",
        "[고칠 것]",
        "- 한 문장씩 입으로 소리 내어 읽는다고 생각하고, 끊기는 곳·숨이 찬 곳·번역투·같은 끝맺음 반복·어색한 연결어를 자연스러운 구어체로 고친다.",
        "- 아래 [문장 흐름 규칙] F1~F11 을 다시 지킨다. 특히 모든 문장이 같은 어미로 끝나지 않게, 앞 문장을 들어야 다음 문장이 이해되게.",
        "- 반말 사이에 '~했다·~였다·~한다고 한다' 같은 해라체가 끼어 있으면 반말로 고친다(F4).",
        "- 누가 한 말인지 빠진 문장은 주어를 채운다(F11). 작은따옴표 안 인용(F10)은 원문 글자 그대로 두고 바꾸지 않는다.",
        "- 문장 하나는 15~30음절, 전체 음절 수는 초안과 비슷하게(190~220 안).",
        "",
        "[바꾸면 안 되는 것 - 어기면 결과를 버린다]",
        "- sentences 의 개수와 순서. 문장을 합치거나 쪼개거나 추가·삭제하지 말 것.",
        "- 각 문장의 evidence, source_id, image_hint, take 는 초안 그대로 복사.",
        "- take 가 true 인 문장(F9 우리 해석)은 말투만 고친다. 원문 내용을 다시 전하는 말로 바꾸거나 사실·숫자를 넣지 말고, 의견·정리 말투를 지킨다.",
        "- 사실: 숫자·이름·회사·장소·결과를 새로 만들거나 바꾸지 말 것. 초안에 없는 사실을 넣지 말 것.",
        "- title_lines 와 hook 은 그대로. 다만 hook 이 서술어로 끝나면(~올라왔어, ~했대) 규칙 2 의 명사로 끝나는 꼴(12~20음절)로 고친다.",
        "- emphasis 는 문장에 그대로 들어 있는 낱말이어야 한다(바뀐 문장에 없으면 null).",
        "",
        "[원문 source_text - 사실 확인용]", "<<<", src, ">>>",
        "",
        "[초안]", body,
        "",
        RULES,
        "[출력 형식] 초안과 같은 모양의 JSON 객체 하나만 출력한다.", SCHEMA,
    ])


def merge_refined(draft: dict, refined: dict) -> tuple[dict | None, str | None]:
    """(합친 대본, 버린 이유). 문장 수가 다르거나 구조가 틀리면 (None, 이유)."""
    rs = refined.get("sentences")
    ds = draft.get("sentences") or []
    if not isinstance(rs, list) or len(rs) != len(ds):
        return None, f"문장 수가 달라 버림(초안 {len(ds)} → 다듬기 {len(rs) if isinstance(rs, list) else '없음'})"
    out = json.loads(json.dumps(draft, ensure_ascii=False))
    for i, (d, r) in enumerate(zip(out["sentences"], rs)):
        r = {"text": r} if isinstance(r, str) else (r or {})
        t = str(r.get("text") or "").strip()
        if not t:
            return None, f"문장 {i} 가 비어 있어 버림"
        d["text"] = t
        emph = r.get("emphasis")
        if emph and emph in t:
            d["emphasis"] = emph
        elif d.get("emphasis") and d["emphasis"] not in t:
            d["emphasis"] = None
    for key in ("hook", "closing"):
        v = str(refined.get(key) or "").strip()
        if v:
            out[key] = v
    return out, None


def changed_sentences(draft: dict, final: dict) -> list[dict]:
    """다듬기 전/후가 달라진 곳 (보고·화면 비교용)."""
    ch = []
    for key in ("hook", "closing"):
        if (draft.get(key) or "") != (final.get(key) or ""):
            ch.append({"where": key, "before": draft.get(key), "after": final.get(key)})
    for i, (a, b) in enumerate(zip(draft.get("sentences") or [], final.get("sentences") or [])):
        if a.get("text") != b.get("text"):
            ch.append({"where": f"sentences[{i}]", "before": a.get("text"), "after": b.get("text")})
    return ch
