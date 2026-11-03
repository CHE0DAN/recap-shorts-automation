"""3.1 주제 고르기: 개념글 후보 목록의 분야·위험·흥미를 Clef 로 매긴다. 위험 후보는 아래로 내리기만 한다(지우지 않음)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from . import client as c
from . import evalres, questions as Q

log = logging.getLogger("recap.clef.triage")
HIDE_AT = 0.5       # 평가 결과(threshold)가 없을 때의 기본 기준. Clef 는 위험 질문에서 확률이 낮게 나오는 편이라(예 쪽 평균 0.2~0.45)
                    # 평가에서 질문별로 잡은 기준값(eval_results.json 의 threshold, 보통 0.1~0.3)을 우선 쓴다.
BODY_CHARS = 600


def _usable(field: str, risk: str | None = None) -> list[str]:
    key = f"triage.{field}" + (f".{risk}" if risk else "")
    return evalres.usable_variants(key, Q.VARIANTS)


def usable() -> bool:
    return bool(_usable("category") or _usable("interest") or any(_usable("risk", r) for r in Q.RISK_KEYS))


def _state(post: dict) -> str:
    body = (post.get("text") or "").strip()[:BODY_CHARS]
    s = Q.TRIAGE_STATE + f"Title: {post.get('title', '')}"
    if body:
        s += f"\nBody: {body}"
    return s


def _questions(v_cat, v_int, v_risk) -> dict:
    qs = {}
    for v in v_cat:
        qs[f"cat_{v}"] = Q.category_q(v)
    for v in v_int:
        qs[f"int_{v}"] = Q.interest_q(v)
    for r, vs in v_risk.items():
        for v in vs:
            qs[f"risk_{r}_{v}"] = Q.risk_q(r, v)
    return qs


def _pass(post: dict, qs: dict, image) -> dict[str, c.Answer]:
    return c.ask(qs, state=_state(post), images=[image] if image else [])


def hide_at(risk: str, variants: list[str]) -> float:
    return _avg([evalres.threshold(f"triage.risk.{risk}.{v}", HIDE_AT) for v in variants]) if variants else HIDE_AT


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _merge(passes: list[dict[str, c.Answer]], v_cat, v_int, v_risk) -> dict:
    cat_runs, int_runs, risk_runs = [], [], {r: [] for r in v_risk}
    for got in passes:
        for v in v_cat:
            a = got[f"cat_{v}"]
            p = dict(a.probabilities) or {str(a.value): 1.0}
            tot = sum(p.values()) or 1.0
            cat_runs.append({k: x / tot for k, x in p.items()})
        for v in v_int:
            int_runs.append(float(got[f"int_{v}"].value) + 1.0)
        for r, vs in v_risk.items():
            for v in vs:
                risk_runs[r].append(float(got[f"risk_{r}_{v}"].value))
    category = None
    if cat_runs:
        keys = {k for r in cat_runs for k in r}
        category = {k: round(_avg([r.get(k, 0.0) for r in cat_runs]), 3) for k in keys}
    # 위험은 두 질문 평균이지만 글자만 본 판단과 그림까지 본 판단 중 더 높은 쪽(놓치지 않기 위해)
    risks: dict = {}
    for r in Q.RISK_KEYS:
        vals = risk_runs.get(r)
        if not vals:
            risks[r] = None
            continue
        n_v = len(v_risk[r])
        by_pass = [_avg(vals[i * n_v:(i + 1) * n_v]) for i in range(len(passes))]
        risks[r] = round(max(by_pass), 3)
    return {"category": category, "risks": risks, "interest": round(_avg(int_runs), 2) if int_runs else None}


def triage_one(post: dict) -> dict | None:
    v_cat, v_int = _usable("category"), _usable("interest")
    v_risk = {r: _usable("risk", r) for r in Q.RISK_KEYS}
    v_risk = {r: vs for r, vs in v_risk.items() if vs}
    qs = _questions(v_cat, v_int, v_risk)
    if not qs:
        return None
    passes = [_pass(post, qs, None)]                      # 1차: 글만
    img = post.get("image")
    if img and not any(
            _avg([float(passes[0][f"risk_{r}_{v}"].value) for v in vs]) >= hide_at(r, vs) for r, vs in v_risk.items()):
        try:
            passes.append(_pass(post, qs, img))           # 2차: 그림 포함(이미 위험이면 생략)
        except c.DailyLimitError:
            raise
        except c.ClefError as e:
            log.warning("image pass failed for %s: %s", post.get("no"), e)
    m = _merge(passes, v_cat, v_int, v_risk)
    by = [r for r, x in m["risks"].items() if x is not None and x >= hide_at(r, v_risk.get(r, []))]
    return {"no": post.get("no"), **m, "hidden": bool(by), "hidden_by": by,
            "asked_twice": all(len(vs) >= 2 for vs in [v_cat, v_int, *v_risk.values()] if vs)}


def triage(posts: list[dict]) -> list[dict] | None:
    """-> [{no, category: {라벨: 확률}, risks: {person_attack, sexual, unverified_claim: 확률|None}, interest: 1~5|None,
    hidden, asked_twice}]. 평가 미통과(usable 질문이 하나도 없음)·키 없음이면 None. 글 하나가 실패하면 그 글만
    {"no", "error"} 로 두고 계속, 하루 한도면 None."""
    if not posts or not c.configured() or not usable():
        return None

    def one(p: dict) -> dict:
        try:
            return triage_one(p) or {"no": p.get("no"), "error": "no usable question"}
        except c.DailyLimitError:
            raise
        except c.ClefError as e:
            return {"no": p.get("no"), "error": str(e)[:160]}

    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            return list(ex.map(one, posts))
    except c.DailyLimitError:
        return None
