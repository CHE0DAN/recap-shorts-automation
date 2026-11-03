"""Clef-omni 질문 평가(설계서 3절 "평가"). 정답을 아는 재료로 질문 문장 A/B 를 각각 시험해 usable 을 정한다.

  python scripts/clef_eval.py run inspect|voice|triage|match [--job work/<작업 폴더>] [--voice-job work/<작업 폴더>]
                                                        # 실제 호출(응답은 eval_raw.json 에 캐시, 같은 호출은 다시 하지 않음)
  python scripts/clef_eval.py report                    # 캐시에서 지표를 계산해 eval_results.json 저장·표 출력(호출 없음)

--job 은 재료가 든 work 폴더(기본 work/sample), --voice-job 은 목소리 시험 재료 폴더(기본은 --job 과 같음).

뉴런 예산: 누적 사용량(eval_raw.json 의 "_neurons")이 BUDGET(2900) 에 닿으면 멈춘다.
지표: 정확도 = 0.5 기준 균형 정확도(예·아니오 각각 맞힌 비율의 평균, 표본이 한쪽으로 쏠려도 공정), 장면 적합도는 AUC(정답 쌍이
오답 쌍보다 높은 비율), 분야는 top1. 흔들림 = 같은 질문을 두 번 물은 답의 차이 평균.
usable = 정확도(또는 AUC) >= 0.8 그리고 흔들림 <= 0.15.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recap_shorts.clef import client as c  # noqa: E402
from recap_shorts.clef import evalres, match as M, questions as Q  # noqa: E402

RAW = ROOT / "recap_shorts" / "clef" / "eval_raw.json"
OUT = ROOT / "recap_shorts" / "clef" / "eval_results.json"
JOB = ROOT / "work" / "sample"           # 재료가 든 작업 폴더(--job)
VOICE_JOB = JOB                          # 목소리 시험 재료 폴더(--voice-job, 기본은 JOB)
BUDGET = 2900.0
BODY_CHARS = 600
raw: dict = json.loads(RAW.read_text(encoding="utf-8")) if RAW.exists() else {"_neurons": 0.0, "_calls": 0}


def save() -> None:
    RAW.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def spend(u: dict) -> None:
    raw["_neurons"] = round(raw.get("_neurons", 0.0) + u.get("neurons", 0.0), 2)
    raw["_calls"] = raw.get("_calls", 0) + 1
    if raw["_neurons"] >= BUDGET:
        save()
        raise SystemExit(f"budget {BUDGET} reached ({raw['_neurons']})")


def ask_cached(key: str, qs: dict, **kw):
    """key 로 캐시. -> {질문id: 값(noul 은 확률, choice 는 {옵션: 확률}, score 는 0~4 기대값)}"""
    if key in raw:
        return raw[key]
    u: dict = {}
    got = c.ask(qs, usage=u, **kw)
    raw[key] = {k: (a.probabilities if a.kind == "choice" else float(a.value)) for k, a in got.items()}
    spend(u)
    save()
    return raw[key]


# --------------------------------------------------------------------------- 지표
def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def bal_acc(pos: list[float], neg: list[float], thr: float = 0.5) -> float:
    if not pos or not neg:
        return float("nan")
    return (sum(p >= thr for p in pos) / len(pos) + sum(n < thr for n in neg) / len(neg)) / 2


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def verdict(acc: float, wobble: float, metric: str) -> dict:
    ok = acc == acc and wobble == wobble and acc >= evalres.ACC_MIN and wobble <= evalres.WOBBLE_MAX
    return {"metric": metric, "accuracy": round(acc, 3), "wobble": round(wobble, 3), "usable": bool(ok)}


def best_threshold(pos, neg) -> tuple[float, float]:
    """균형 정확도가 가장 높은 기준값(같은 값 구간이면 가운데). 점수들 사이의 중간값 후보. -> (기준값, 정확도)"""
    vals = sorted(set(pos + neg))
    if not vals:
        return 0.5, float("nan")
    cands = [0.0] + [(a + b) / 2 for a, b in zip(vals, vals[1:])] + [1.0 + 1e-9]
    scored = [(bal_acc(pos, neg, t), t) for t in cands]
    top = max(a for a, _ in scored)
    ts = [t for a, t in scored if a >= top - 1e-12]
    return min(1.0, (ts[0] + ts[-1]) / 2), top      # 최적 구간의 가운데(확률 기준)


MIN_YES = 3


def pn_verdict(pos, neg, wob) -> dict:
    """예/아니오 질문: 0.5 기준 정확도와 평가 표본에 맞춰 잡은 기준값(threshold)의 정확도를 함께 기록. usable = 기준값 정확도 >= 0.8,
    AUC >= 0.8, 예 표본 >= 3, 흔들림 <= 0.15. (기준값은 같은 표본에서 골랐으므로 낙관적: 실제 목록에서 다시 확인할 것)"""
    thr, acc = best_threshold(pos, neg)
    d = verdict(acc, mean(wob), "balanced_acc@threshold")
    a = auc(pos, neg)
    d["usable"] = bool(d["usable"] and a >= 0.8 and len(pos) >= MIN_YES)
    d["threshold"] = round(thr, 3)
    d["acc_at_0_5"] = round(bal_acc(pos, neg), 3)
    return pn_extra(d, pos, neg)


def pn_extra(d: dict, pos, neg) -> dict:
    d.update(n_yes=len(pos), n_no=len(neg), auc=round(auc(pos, neg), 3), yes_mean=round(mean(pos), 3), no_mean=round(mean(neg), 3))
    return d


# --------------------------------------------------------------------------- 3.3 자료 검사
def make_crops():
    """img_3(SNS 캡처)에서 잘라 낸 두 장: 위쪽(프로필 사진 + 아이디), 아래쪽(대화 말풍선만: 얼굴·아이디 없음)."""
    from PIL import Image
    d = ROOT / "work" / "clef_eval_crops"
    d.mkdir(parents=True, exist_ok=True)
    im = Image.open(JOB / "post" / "img_3.jpg").convert("RGB")
    w, h = im.size
    head, chat = d / "img_3_head.jpg", d / "img_3_chat.jpg"
    im.crop((0, 0, w, int(h * 0.17))).save(head, quality=92)
    im.crop((0, int(h * 0.74), w, int(h * 0.93))).save(chat, quality=92)
    return head, chat


def inspect_items():
    ai = sorted((JOB / "assets" / "ai").glob("ai_*.png"))
    cap = [JOB / "assets" / "cap" / f"c0{i}_{n}.png" for i, n in
           [(1, "head_a"), (2, "rows_a"), (3, "rows_b"), (5, "table_row"), (6, "score_summary"), (7, "sns_text")]]
    items = [("img_3", JOB / "post" / "img_3.jpg"), ("img_1", JOB / "post" / "img_1.jpg")]
    crops = make_crops()
    items += [("img_3_head", crops[0]), ("img_3_chat", crops[1])]
    items += [(p.stem, p) for p in cap] + [(p.stem, p) for p in ai]
    cs, ais = [p.stem for p in cap], [p.stem for p in ai]
    truth = {  # 질문 -> {항목: 0/1}   (없는 항목은 그 질문에서 제외: AI 그림의 "얼굴"은 정답이 애매해 뺌)
        "face": {"img_3": 1, "img_3_head": 1, "img_3_chat": 0, "img_1": 0, **{s: 0 for s in cs}},
        "personal_text": {"img_3": 1, "img_3_head": 1, "img_3_chat": 0, "img_1": 0, **{s: 0 for s in cs + ais}},
        "text_or_logo": {"img_3": 1, "img_3_head": 1, "img_3_chat": 1, "img_1": 1, **{s: 1 for s in cs}, **{s: 0 for s in ais}},
        "real_person_like": {"img_3": 1, "img_3_head": 1, "img_3_chat": 0, "img_1": 0, **{s: 0 for s in cs + ais}},
    }
    return items, truth


def run_inspect():
    items, _ = inspect_items()
    qs = {f"{k}_{v}": Q.inspect_q(k, v) for k in Q.INSPECT_KEYS for v in Q.VARIANTS}
    for run in (1, 2):
        for name, p in items:
            if run == 2 and name not in ("img_3", "c07_sns_text"):
                continue
            ask_cached(f"inspect|{name}|{run}", qs, state=Q.INSPECT_STATE, images=[p])


def report_inspect() -> dict:
    items, truth = inspect_items()
    out = {}
    for k in Q.INSPECT_KEYS:
        for v in Q.VARIANTS:
            pos, neg, wob = [], [], []
            for name, _ in items:
                if name not in truth[k] or f"inspect|{name}|1" not in raw:
                    continue
                r1 = raw[f"inspect|{name}|1"][f"{k}_{v}"]
                (pos if truth[k][name] else neg).append(r1)
                r2 = raw.get(f"inspect|{name}|2", {}).get(f"{k}_{v}")
                if r2 is not None:
                    wob.append(abs(r1 - r2))
            out[f"inspect.{k}.{v}"] = pn_verdict(pos, neg, wob)
    return out


# --------------------------------------------------------------------------- 3.5 목소리
def voice_items():
    t = json.loads((VOICE_JOB / "voice" / "timings.json").read_text(encoding="utf-8"))
    sents = [s["text"] for s in t["sentences"]]
    wavs = {i: VOICE_JOB / "voice" / "sentences_fit_redo" / f"s{i:02d}.wav" for i in range(1, 9)}
    return sents, wavs


def run_voice():
    sents, wavs = voice_items()
    qs = {f"{v}_{j}": Q.voice_q(v, s) for v in Q.VARIANTS for j, s in enumerate(sents)}
    for run in (1, 2):
        for i, w in wavs.items():
            if run == 2 and i not in (1, 3, 5, 7):
                continue
            ask_cached(f"voice|{i}|{run}", qs, state=Q.VOICE_STATE, audio=[w])


def report_voice() -> dict:
    sents, wavs = voice_items()
    out = {}
    for v in Q.VARIANTS:
        pos, neg, wob = [], [], []
        for i in wavs:
            r1 = raw.get(f"voice|{i}|1")
            if not r1:
                continue
            r2 = raw.get(f"voice|{i}|2")
            for j in range(len(sents)):
                x = r1[f"{v}_{j}"]
                (pos if j == i else neg).append(x)
                if r2:
                    wob.append(abs(x - r2[f"{v}_{j}"]))
        out[f"voice.{v}"] = pn_verdict(pos, neg, wob)
    return out


# --------------------------------------------------------------------------- 3.1 주제 분류
# 정답표(제목 목록을 보고 하나하나 매긴 것). 번호 = _topics_raw.json 의 순서. 분야는 허용 집합(애매한 것은 둘 다 인정).
CAT = {0: {"crime"}, 1: {"sexual"}, 2: {"politics"}, 3: {"sexual"}, 4: {"politics", "crime"}, 5: {"sports"}, 6: {"politics", "crime"},
       7: {"politics"}, 8: {"politics"}, 9: {"politics"}, 10: {"crime"}, 11: {"sports", "entertainment"}, 12: {"politics"},
       13: {"politics"}, 14: {"life_economy"}, 15: {"sports", "entertainment"}, 16: {"crime"}, 17: {"life_economy", "crime"},
       18: {"sexual"}, 19: {"crime"}, 20: {"entertainment", "crime"}, 21: {"crime"}, 22: {"politics", "other", "life_economy"},
       25: {"politics"}, 26: {"politics", "life_economy"}, 27: {"politics"}, 28: {"politics", "other"}, 29: {"life_economy"},
       30: {"life_economy", "politics"}, 31: {"politics"}, 32: {"crime", "other"}, 33: {"politics"}, 35: {"sexual", "entertainment"},
       36: {"crime"}, 37: {"sports", "entertainment"}, 38: {"sports", "entertainment"}, 39: {"life_economy"}, 40: {"politics", "crime", "other"},
       41: {"life_economy"}, 42: {"life_economy"}, 43: {"life_economy", "politics"}, 46: {"politics"}, 47: {"politics", "other"}}
NEWS_OK = [0, 4, 10, 14, 16, 17, 19, 21, 29, 36, 39, 41, 42, 43, 46, 47, 40, 28, 27, 26]
RISK_TRUE = {"person_attack": [2, 7, 8, 9, 20, 25, 31, 33],
             "sexual": [1, 3, 18, 35],
             "unverified_claim": [2, 7, 9, 13, 31]}
RISK_FALSE = {"person_attack": NEWS_OK + [5, 11, 15, 37, 38, 1, 3, 18, 35],
              "sexual": NEWS_OK + [11, 15, 37, 38, 2, 7, 8, 9, 25, 31, 33],
              "unverified_claim": NEWS_OK + [5, 11, 15, 37, 38]}
INTEREST_HIGH, INTEREST_LOW = [29, 14, 39, 42], [46, 17, 43, 28, 27]       # 약한 정답(사람이 매긴 것): 생활 호기심 vs 정치·제도·국제 뉴스


def topics():
    return json.loads((ROOT / "recap_shorts" / "clef" / "_topics_raw.json").read_text(encoding="utf-8"))


def triage_qs() -> dict:
    qs = {}
    for v in Q.VARIANTS:
        qs[f"cat_{v}"] = Q.category_q(v)
        qs[f"int_{v}"] = Q.interest_q(v)
        for r in Q.RISK_KEYS:
            qs[f"risk_{r}_{v}"] = Q.risk_q(r, v)
    return qs


def run_triage():
    qs = triage_qs()
    for run in (1, 2):
        for i, p in enumerate(topics()):
            if run == 2 and i not in (0, 16, 32):
                continue
            body = (p.get("text") or "").strip()[:BODY_CHARS]
            state = Q.TRIAGE_STATE + f"Title: {p['title']}" + (f"\nBody: {body}" if body else "")
            ask_cached(f"triage|{i}|{run}", qs, state=state)


def report_triage() -> dict:
    out = {}
    R = lambda i, run: raw.get(f"triage|{i}|{run}")  # noqa: E731
    for v in Q.VARIANTS:
        ok, tot, wob = 0, 0, []
        for i, allowed in CAT.items():
            r = R(i, 1)
            if not r:
                continue
            probs = r[f"cat_{v}"]
            ok += max(probs, key=probs.get) in allowed
            tot += 1
            r2 = R(i, 2)
            if r2:
                p2 = r2[f"cat_{v}"]
                wob.append(sum(abs(probs.get(k, 0) - p2.get(k, 0)) for k in set(probs) | set(p2)) / 2)   # 분포 거리
        d = verdict(ok / tot if tot else float("nan"), mean(wob), "top1_acc")
        d.update(n=tot)
        out[f"triage.category.{v}"] = d
        for rk in Q.RISK_KEYS:
            pos = [R(i, 1)[f"risk_{rk}_{v}"] for i in RISK_TRUE[rk] if R(i, 1)]
            neg = [R(i, 1)[f"risk_{rk}_{v}"] for i in RISK_FALSE[rk] if R(i, 1)]
            wob = [abs(R(i, 1)[f"risk_{rk}_{v}"] - R(i, 2)[f"risk_{rk}_{v}"]) for i in range(49) if R(i, 1) and R(i, 2)]
            out[f"triage.risk.{rk}.{v}"] = pn_verdict(pos, neg, wob)
        hi = [R(i, 1)[f"int_{v}"] + 1 for i in INTEREST_HIGH if R(i, 1)]
        lo = [R(i, 1)[f"int_{v}"] + 1 for i in INTEREST_LOW if R(i, 1)]
        wob = [abs(R(i, 1)[f"int_{v}"] - R(i, 2)[f"int_{v}"]) / 4 for i in range(49) if R(i, 1) and R(i, 2)]   # 0~1 로 정규화
        acc = (sum(x >= 3 for x in hi) / len(hi) + sum(x < 3 for x in lo) / len(lo)) / 2 if hi and lo else float("nan")
        d = verdict(acc, mean(wob), "high>=3/low<3 (weak labels)")
        d.update(auc=round(auc(hi, lo), 3), high_mean=round(mean(hi), 2), low_mean=round(mean(lo), 2))
        out[f"triage.interest.{v}"] = d
    return out


# --------------------------------------------------------------------------- 3.2 장면 배치
SKIP_IMAGES = {"assets/cap/c00_post_title.png", "assets/cap/c04_footer_note.png", "assets/cap/c10_final_title.png",
               "assets/ai/ai_06_corporate_league.png", "assets/ai/ai_10_commuter_glove.png", "assets/ai/ai_12_scoreboard_blank.png",
               "assets/ai/ai_04_paper_mill.png"}


def match_items():
    plan = json.loads((JOB / "shot_plan.json").read_text(encoding="utf-8"))["plan"]
    # 뉴런 예산 때문에 일부 그림은 뺐다(제목·꼬리말 카드, 겹치는 AI 그림 몇 장). 손 배치도 같은 그림만 남겨 비교.
    plan = {k: [x for x in ims if x not in SKIP_IMAGES] for k, ims in plan.items()}
    t = json.loads((JOB / "voice" / "timings.json").read_text(encoding="utf-8"))
    sents = [s["text"] for s in t["sentences"]]
    imgs = sorted({p for ps in plan.values() for p in ps})
    return plan, sents, imgs


def run_match():
    plan, sents, imgs = match_items()
    repeat = set(imgs[::12])
    for run in (1, 2):
        for im in imgs:
            if run == 2 and im not in repeat:
                continue
            for v in Q.VARIANTS:
                qs = {f"s{i}": Q.match_q(v, s) for i, s in enumerate(sents)}
                ask_cached(f"match|{im}|{v}|{run}", qs, state=Q.MATCH_STATE, images=[JOB / im])


def report_match() -> tuple[dict, dict]:
    plan, sents, imgs = match_items()
    hand = {(int(k), im) for k, ims in plan.items() for im in ims}
    out, mats = {}, {}
    for v in Q.VARIANTS:
        pos, neg, wob = [], [], []
        mat = [[None] * len(imgs) for _ in sents]
        for j, im in enumerate(imgs):
            r1 = raw.get(f"match|{im}|{v}|1")
            if not r1:
                continue
            r2 = raw.get(f"match|{im}|{v}|2")
            for i in range(len(sents)):
                x = r1[f"s{i}"]
                mat[i][j] = x
                (pos if (i, im) in hand else neg).append(x)
                if r2:
                    wob.append(abs(x - r2[f"s{i}"]))
        d = pn_extra(verdict(auc(pos, neg), mean(wob), "AUC"), pos, neg)
        d["acc_at_0_5"] = round(bal_acc(pos, neg), 3)
        hit = tot = 0                                   # 그림마다 "손으로 붙인 문장이 점수 순위 상위 3 안인가"
        for j, im in enumerate(imgs):
            if mat[0][j] is None:
                continue
            truth = {i for (i, x) in hand if x == im}
            hit += bool(truth & set(sorted(range(len(sents)), key=lambda i: -mat[i][j])[:3]))
            tot += 1
        d["image_top3_hit"] = round(hit / tot, 3) if tot else None
        out[f"match.{v}"] = d
        mats[v] = mat
    return out, mats


def overlap(mat, imgs, plan, allow_reuse) -> dict:
    a = M.assign(mat, (2, 3), allow_reuse)
    auto = {(int(k), imgs[j]) for k, js in a.items() for j in js}
    hand = {(int(k), im) for k, ims in plan.items() for im in ims}
    first = [a[k][0] == imgs.index(plan[k][0]) for k in plan if a.get(k) and plan[k]]
    return {"hand_pairs": len(hand), "auto_pairs": len(auto), "recall_of_hand": round(len(auto & hand) / len(hand), 3),
            "precision": round(len(auto & hand) / len(auto), 3),
            "first_pick_same": round(sum(first) / len(first), 3), "first_pick_n": len(first)}


# --------------------------------------------------------------------------- 보고
def report():
    plan, sents, imgs = match_items()
    questions = {}
    questions.update(report_inspect())
    questions.update(report_voice())
    questions.update(report_triage())
    mq, mats = report_match()
    questions.update(mq)
    full = {v: all(x is not None for row in m for x in row) for v, m in mats.items()}
    ov = {}
    for v, mat in mats.items():
        if full[v]:
            ov[v] = {"no_reuse": overlap(mat, imgs, plan, False), "reuse": overlap(mat, imgs, plan, True)}
    if all(full.values()) and mats:
        both = [[(mats["A"][i][j] + mats["B"][i][j]) / 2 for j in range(len(imgs))] for i in range(len(sents))]
        ov["A+B"] = {"no_reuse": overlap(both, imgs, plan, False), "reuse": overlap(both, imgs, plan, True)}
    res = {"criteria": {"accuracy_min": evalres.ACC_MIN, "wobble_max": evalres.WOBBLE_MAX},
           "neurons_used": raw.get("_neurons"), "calls": raw.get("_calls"), "questions": questions, "plan_overlap": ov,
           "note": "정확도=0.5 기준 균형 정확도(장면 적합도는 AUC, 분야는 top1). watch.* 는 정답 있는 영상이 없어 평가하지 않음(hint_only)."}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'question':34s} {'metric':8s} acc    wobble usable extra")
    for k, d in questions.items():
        extra = {x: d[x] for x in ("auc", "yes_mean", "no_mean", "n_yes", "n_no", "n", "image_top3_hit") if x in d}
        print(f"{k:34s} {d['metric'][:8]:8s} {d['accuracy']:<6} {d['wobble']:<6} {str(d['usable']):6s} {extra}")
    print("neurons", raw.get("_neurons"), "calls", raw.get("_calls"))
    print(json.dumps(ov, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(prog="python scripts/clef_eval.py")
    ap.add_argument("mode", choices=("run", "report"))
    ap.add_argument("part", nargs="?", choices=("inspect", "voice", "triage", "match"), help="run 일 때 평가 부문")
    ap.add_argument("--job", default=None, help="재료가 든 작업 폴더(기본 work/sample)")
    ap.add_argument("--voice-job", default=None, help="목소리 시험 재료 폴더(기본 --job)")
    args = ap.parse_args()
    if args.job:
        JOB = Path(args.job).resolve()
    if args.voice_job:
        VOICE_JOB = Path(args.voice_job).resolve()
    elif args.job:
        VOICE_JOB = JOB
    if args.mode == "report":
        report()
    else:
        if not args.part:
            ap.error("run 에는 inspect|voice|triage|match 중 하나가 필요합니다")
        c.METER.budget = BUDGET
        {"inspect": run_inspect, "voice": run_voice, "triage": run_triage, "match": run_match}[args.part]()
        print("neurons so far", raw.get("_neurons"))
