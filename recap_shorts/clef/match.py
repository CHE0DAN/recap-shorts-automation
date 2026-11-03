"""3.2 장면 자동 배치: 문장×그림 적합도 표 → 겹치지 않게 배치. 점수는 추천이며 사람이 편집기에서 바꾼다."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import client as c
from . import evalres, questions as Q

log = logging.getLogger("recap.clef.match")
CHUNK = 30          # 한 요청의 질문 수(변형당)


def variants() -> list[str]:
    return evalres.usable_variants("match", Q.VARIANTS)


def _one_image(sentences: list[str], image, vs: list[str]) -> list[float]:
    """그림 1장 × 문장 전체. 변형별로 한 요청(질문 여러 개), 변형 평균."""
    per_v = []
    for v in vs:
        row = [0.0] * len(sentences)
        for a in range(0, len(sentences), CHUNK):
            part = sentences[a:a + CHUNK]
            qs = {f"s{a + i}": Q.match_q(v, s) for i, s in enumerate(part)}
            got = c.ask(qs, state=Q.MATCH_STATE, images=[image])
            for k, ans in got.items():
                row[int(k[1:])] = float(ans.value)
        per_v.append(row)
    return [sum(col) / len(col) for col in zip(*per_v)]


def fit_matrix(sentences: list[str], images: list) -> list[list[float]] | None:
    """matrix[i][j] = 문장 i 에 그림 j 가 어울릴 확률(usable 변형 평균). 평가 미통과이거나 키 없으면 None.
    개별 그림 호출이 실패하면 그 열은 0.5(모름)로 채우고 계속한다. 하루 한도면 None."""
    vs = variants()
    if not vs or not c.configured() or not sentences or not images:
        return None
    cols: list[list[float] | None] = [None] * len(images)

    def work(j: int) -> None:
        try:
            cols[j] = _one_image(sentences, images[j], vs)
        except c.DailyLimitError:
            raise
        except c.ClefError as e:
            log.warning("fit for image %s failed: %s", Path(str(images[j])).name, e)

    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(work, range(len(images))))
    except c.DailyLimitError:
        return None
    if all(col is None for col in cols):
        return None
    return [[(cols[j][i] if cols[j] is not None else 0.5) for j in range(len(images))] for i in range(len(sentences))]


def assign(matrix: list[list[float]], per_sentence: tuple[int, int] = (2, 3), allow_reuse: bool = False,
           min_extra_score: float = 0.4) -> dict[str, list[int]]:
    """헝가리안(문장마다 서로 다른 최고 그림 1장) + 탐욕(최소 개수까지, 남는 그림은 점수 높은 순으로 최대까지).
    -> {"문장 index": [그림 index, ...]} 점수 높은 순. allow_reuse=True 면 그림을 여러 문장에 써도 된다."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    n = len(matrix)
    m = len(matrix[0]) if n else 0
    lo, hi = per_sentence
    out: dict[int, list[int]] = {i: [] for i in range(n)}
    if not n or not m:
        return {str(i): [] for i in range(n)}
    M = np.array(matrix, dtype=float)
    used: set[int] = set()

    # 1) 헝가리안: 문장마다 1장 (그림이 모자라면 일부 문장은 비움)
    rows, cols = linear_sum_assignment(-M)
    for i, j in zip(rows, cols):
        out[int(i)].append(int(j))
        used.add(int(j))

    def pairs(min_score: float | None):
        for i in range(n):
            for j in range(m):
                if j in out[i]:
                    continue
                if not allow_reuse and j in used:
                    continue
                if min_score is not None and M[i, j] < min_score:
                    continue
                yield M[i, j], i, j

    # 2) 탐욕: 각 문장 최소 개수까지
    for _ in range(n * lo):
        need = [(s, i, j) for s, i, j in pairs(None) if len(out[i]) < lo]
        if not need:
            break
        _, i, j = max(need)
        out[i].append(j)
        used.add(j)
    # 3) 남는 그림은 점수가 충분하면 최대 개수까지
    while True:
        extra = [(s, i, j) for s, i, j in pairs(min_extra_score) if len(out[i]) < hi]
        if not extra:
            break
        _, i, j = max(extra)
        out[i].append(j)
        used.add(j)
    return {str(i): sorted(js, key=lambda j: -M[i, j]) for i, js in out.items()}


def plan(sentences: list[str], images: list, per_sentence: tuple[int, int] = (2, 3), allow_reuse: bool = False,
         matrix: list[list[float]] | None = None) -> dict | None:
    """-> {"plan": {"0": [그림 경로...], ...}, "scores": {"matrix": .., "images": [경로], "chosen": {"0": [점수...]}}}
    shot_plan.json 의 "plan" 형식(키 = 문장 index 문자열, 0번은 훅). 평가 미통과/실패면 None."""
    m = matrix if matrix is not None else fit_matrix(sentences, images)
    if m is None:
        return None
    a = assign(m, per_sentence, allow_reuse)
    paths = [str(p) for p in images]
    return {"plan": {k: [paths[j] for j in js] for k, js in a.items()},
            "scores": {"matrix": m, "images": paths,
                       "chosen": {k: [round(m[int(k)][j], 3) for j in js] for k, js in a.items()}}}
