"""문장 -> 자막 카드(약 8음절), 카드 안 줄바꿈."""
from __future__ import annotations

from typing import Callable, Optional

from . import layout

TARGET = 8
MIN_SYL, MAX_SYL = 6, 10
MIN_CARD_SEC = 0.6
GLUE_COST = 100         # 붙어야 할 두 어절 사이에서 카드·줄을 끊는 값 — 짧은 카드(4음절)나 11음절 카드보다 크게
BARE_COST = 8           # 조사·어미 없이 끝난 말(기존·세입자 같은 맨 명사) 뒤에서 끊는 값 — 되도록 피함
COMMA_BONUS = 4         # 쉼표 뒤에서 끊으면 덜어 줌
# 끊어도 자연스러운 끝 글자(조사·어미, 꾸미는 말 ~는·~ㄴ·~ㄹ). 이 밖의 글자로 끝나면 맨 명사로 본다(기존·내년·세입자)
_END_OK = set("은는이가을를에의도만로과와랑서게고며면데지요다래대야어아해니까던죠네군걸든엔선여냐나라"
              "한할된될인일난날간갈온올본볼낸린진친운른런긴던뺏산살탄쓴")


def syllables(text: str) -> int:
    """공백·문장부호를 뺀 글자(한글 음절, 영문, 숫자) 수."""
    return sum(1 for c in text if c.isalnum())


# ---------- 끊으면 안 되는 곳 ("안 / 주고", "못 / 구하면", "생각해 / 낸" 처럼 끊기지 않게) ----------
_AUX_HEADS = ("내", "냈", "낸", "놓", "놨", "놔", "두", "둬", "뒀", "둔", "버리", "버렸", "버린", "봐", "봤", "본", "보니", "보면",
              "보고", "보자", "줘", "줬", "준", "주고", "주면", "주는", "주기", "드리", "드렸", "드린", "가지", "대", "댔")
_AUX_AFTER_GO = ("있", "싶", "말", "나서", "계")       # ~고 있다·싶다·말았다·나서
_BOUND_HEADS = ("수", "거", "것", "줄", "적", "뿐", "듯", "척", "채", "만큼", "리가", "리는", "법", "참이", "때")
# 늘 뒤 명사를 꾸미는 말(관형사·꾸밈 명사): '기존 / 세입자가' 처럼 끊지 않게
_PRENOMINAL = {"모든", "각종", "여러", "어떤", "무슨", "어느", "온갖", "갖은", "기존", "신규", "해당", "동일", "현행", "전직", "현직"}


def _core(w: str) -> str:
    return w.strip("\"'“”‘’()[]…·")


def _final_consonant(ch: str) -> int:
    """한글 음절의 받침 번호(0 = 없음, 4 = ㄴ, 8 = ㄹ). 한글이 아니면 -1."""
    return (ord(ch) - 0xAC00) % 28 if "가" <= ch <= "힣" else -1


def glued(a: str, b: str) -> bool:
    """어절 a 와 바로 뒤 어절 b 사이에서 끊으면 어색한가(카드·줄 모두).
    - a 가 한 음절 꾸밈말·부정어(안·못·새·한·두·이·그·잘·더 …)이고 문장부호로 끝나지 않음
    - 본용언 + 보조용언: '생각해 낸', '기다려 줬', '먹어 봤', '하고 있어'
    - 꾸미는 말 + 의존 명사: '할 수', '본 적', '그럴 거야', '필기할 때'
    - '~기만 하면' 꼴, 늘 뒤 명사를 꾸미는 말('기존 세입자')"""
    if not a or not b or a[-1] in ",.!?…~":
        return False
    ca, cb = _core(a), _core(b)
    if not ca or not cb:
        return False
    if len(ca) == 1 and "가" <= ca <= "힣" or ca in _PRENOMINAL:
        return True
    last = ca[-1]
    if last in "해어아여워와려쳐춰겨져혀떠써" and cb.startswith(_AUX_HEADS):    # '~해서 내가' 같은 이음말은 뺌('서' 없음)
        return True
    if last == "고" and cb.startswith(_AUX_AFTER_GO):
        return True
    if ca.endswith(("기만", "기는", "기도", "기라도", "기조차")) and cb.startswith(("하", "했", "해", "한", "할")):
        return True                                       # '기다려주기만 하면', '하기는 했는데'
    if _final_consonant(last) in (4, 8) and (cb in _BOUND_HEADS or cb.startswith(_BOUND_HEADS) and len(cb) <= 3):
        return True
    return False


def _break_cost(words: list[str], k: int) -> float:
    """words[k-1] 와 words[k] 사이에서 끊는 값. 0 < k < len(words)."""
    a = words[k - 1]
    if glued(a, words[k]):
        return GLUE_COST
    if a.endswith(","):
        return -COMMA_BONUS
    ca = _core(a)
    if len(ca) >= 2 and "가" <= ca[-1] <= "힣" and ca[-1] not in _END_OK:
        return BARE_COST
    return 0.0


def _card_cost(s: int) -> float:
    c = (s - TARGET) ** 2
    if s > MAX_SYL:
        c += 50 * (s - MAX_SYL)
    elif s < MIN_SYL:
        c += 20 * (MIN_SYL - s)
    return c


def split_words(words: list[str]) -> list[list[str]]:
    """어절 단위로만 끊어 음절 수 합이 8에 가깝게 되는 최적 분할(DP)."""
    n = len(words)
    if n == 0:
        return []
    syl = [syllables(w) for w in words]
    pre = [0]
    for s in syl:
        pre.append(pre[-1] + s)
    INF = float("inf")
    best = [INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for i in range(1, n + 1):
        for j in range(i):
            c = best[j] + _card_cost(pre[i] - pre[j]) + 1.0 + (_break_cost(words, j) if j > 0 else 0.0)
            if c < best[i]:
                best[i], back[i] = c, j
    out: list[list[str]] = []
    i = n
    while i > 0:
        out.append(words[back[i]:i])
        i = back[i]
    return out[::-1]


def _merge_short(cards: list[dict]) -> list[dict]:
    while len(cards) > 1:
        durs = [c["end"] - c["start"] for c in cards]
        k = min(range(len(cards)), key=lambda i: durs[i])
        if durs[k] >= MIN_CARD_SEC - 1e-9:
            break
        if k == 0:
            nb = 1
        elif k == len(cards) - 1:
            nb = k - 1
        else:
            nb = k - 1 if durs[k - 1] <= durs[k + 1] else k + 1
        a, b = sorted((k, nb))
        merged = {
            "words": cards[a]["words"] + cards[b]["words"],
            "start": cards[a]["start"],
            "end": cards[b]["end"],
        }
        cards[a:b + 1] = [merged]
    return cards


# ---------- 줄바꿈 ----------

def _text_w(text: str, size: int) -> float:
    return layout.load_font(size).getlength(text) + 2 * layout.CAPTION_STROKE


def fit_text(text: str, max_w: int = layout.TEXT_MAX_W, max_lines: int = 2,
             size_max: int = layout.CAPTION_SIZE_MAX,
             size_min: int = layout.CAPTION_SIZE_MIN):
    """(size, [줄들], 첫줄 어절 수 리스트) 또는 None(최소 크기로도 안 들어감).

    1줄에 들어가면 1줄, 아니면 두 줄의 넓은 쪽이 가장 좁아지는 어절 경계.
    """
    words = text.split()
    for size in range(size_max, size_min - 1, -2):
        if _text_w(" ".join(words), size) <= max_w:
            return size, [" ".join(words)], [len(words)]
        if max_lines >= 2 and len(words) >= 2:
            best = None
            for k in range(1, len(words)):
                l1, l2 = " ".join(words[:k]), " ".join(words[k:])
                w = max(_text_w(l1, size), _text_w(l2, size))
                key = (glued(words[k - 1], words[k]), w)          # 붙은 말 사이 줄바꿈은 다른 곳이 없을 때만
                if w <= max_w and (best is None or key < best[0]):
                    best = (key, k, l1, l2)
            if best:
                return size, [best[2], best[3]], [best[1], len(words) - best[1]]
    if max_lines >= 3 and len(words) >= 3:
        for size in range(size_max, size_min - 1, -2):
            best = None
            for a in range(1, len(words) - 1):
                for b in range(a + 1, len(words)):
                    ls = [" ".join(words[:a]), " ".join(words[a:b]), " ".join(words[b:])]
                    w = max(_text_w(x, size) for x in ls)
                    key = (glued(words[a - 1], words[a]) + glued(words[b - 1], words[b]), w)
                    if w <= max_w and (best is None or key < best[0]):
                        best = (key, ls, [a, b - a, len(words) - b])
            if best:
                return size, best[1], best[2]
    return None


def _split_card_in_two(card: dict) -> list[dict]:
    words = card["words"]
    if len(words) < 2:
        return [card]
    syl = [syllables(w) for w in words]
    total = sum(syl) or len(words)
    best_k, best_d = 1, None
    run = 0
    for k in range(1, len(words)):
        run += syl[k - 1]
        d = (glued(words[k - 1], words[k]), abs(run - total / 2))    # 붙은 말 사이는 마지막 수단
        if best_d is None or d < best_d:
            best_k, best_d = k, d
    a, b = words[:best_k], words[best_k:]
    sa, sb = sum(syllables(w) for w in a), sum(syllables(w) for w in b)
    frac = sa / (sa + sb) if (sa + sb) else 0.5
    mid = card["start"] + (card["end"] - card["start"]) * frac
    return [
        {"words": a, "start": card["start"], "end": mid},
        {"words": b, "start": mid, "end": card["end"]},
    ]


def _fit_split(card: dict, measure: bool) -> list[dict]:
    if not measure:
        return [card]
    if fit_text(" ".join(card["words"])) is not None:
        return [card]
    parts = _split_card_in_two(card)
    if len(parts) == 1:
        return parts  # 한 어절이 너무 길다: 그대로 두고 그리기에서 최소 크기 사용
    return _fit_split(parts[0], True) + _fit_split(parts[1], True)


def _ratio_cards(words: list[str], st: float, en: float) -> list[dict]:
    """어절 목록을 약 8음절 카드로 나누고 [st, en] 을 음절 비율로 나눠 시각을 붙인다(합치기·폭 맞춤 전)."""
    groups = split_words(words)
    weights = [syllables(" ".join(g)) for g in groups]
    if sum(weights) == 0:
        weights = [1] * len(groups)
    total = sum(weights)
    dur = en - st
    cards, acc = [], 0
    for g, w in zip(groups, weights):
        cards.append({"words": g, "start": st + dur * acc / total,
                      "end": st + dur * (acc + w) / total})
        acc += w
    cards[-1]["end"] = en
    return cards


def _valid_breaks(breaks, n_words: int, st: float, en: float) -> list[tuple[int, float]]:
    """문장 안에서 카드를 반드시 끊을 자리 [(어절 경계 번호, 시각)]: 번호는 1..n_words-1, 시각은 문장 안, 둘 다 순서대로인 것만."""
    out: list[tuple[int, float]] = []
    for b in breaks or []:
        try:
            k, t = int(b[0]), float(b[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 < k < n_words and st + 0.05 < t < en - 0.05 and (not out or (k > out[-1][0] and t > out[-1][1])):
            out.append((k, t))
    return out


def make_cards(sentences: list[dict], measure: bool = True) -> list[dict]:
    """문장({text,start,end,emphasis[,breaks]}) -> 카드({text,start,end,emphasis}).

    measure=True 이면 실제 글꼴로 폭을 재서, 최소 글자 크기에서 2줄에도 안 들어가는 카드를 더 쪼갠다
    (글꼴이 없으면 폭 검사를 건너뜀).
    breaks=[(어절 경계 번호 k, 시각 t)] 가 있으면(그림 컷을 어절 사이에 놓았을 때, timeline.build) 앞 k 어절과 뒤 어절은
    같은 카드에 들어가지 않고, 그 경계가 정확히 t 에서 바뀐다 — 그림이 바뀔 때 자막도 같이 바뀐다. 시각은 컷 사이 구간마다 따로 음절 비율로 나눈다.
    """
    if measure:
        try:
            layout.find_font()
        except layout.FontNotFoundError:
            measure = False
    out: list[dict] = []
    for s in sentences:
        text = " ".join(str(s.get("text", "")).split())
        st, en = float(s["start"]), float(s["end"])
        emph = (s.get("emphasis") or "").strip()
        if not text:
            continue
        words = text.split()
        brk = _valid_breaks(s.get("breaks"), len(words), st, en)
        if brk:
            ks = [0] + [k for k, _ in brk] + [len(words)]
            ts = [st] + [t for _, t in brk] + [en]
            cards = []
            for a, b, t0, t1 in zip(ks, ks[1:], ts, ts[1:]):
                cards += _merge_short(_ratio_cards(words[a:b], t0, t1))      # 합치기도 구간 안에서만
        else:
            cards = _merge_short(_ratio_cards(words, st, en))
        final: list[dict] = []
        for c in cards:
            final.extend(_fit_split(c, measure))
        for c in final:
            t = " ".join(c["words"])
            out.append({
                "text": t,
                "start": round(c["start"], 4),
                "end": round(c["end"], 4),
                "emphasis": emph if emph and emph in t else None,
            })
    return out


def emphasis_mask(text: str, emphasis: Optional[str]) -> list[bool]:
    """text 의 글자별 강조 여부(처음 나오는 한 곳만)."""
    mask = [False] * len(text)
    if emphasis:
        i = text.find(emphasis)
        if i >= 0:
            for j in range(i, i + len(emphasis)):
                mask[j] = True
    return mask
