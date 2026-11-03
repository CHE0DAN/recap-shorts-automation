"""TTS 에 넣는 문장만 숫자·약어를 한글 읽기로 바꾼다 (자막·대본 원문은 그대로 둠).

- 기본은 한자어 수(일 이 삼 ... 십 백 천 만 억). 쉼표 무시, 0 = 영.
- 고유어 수(1~99)를 쓰는 단위: 개 명 살 시 시간 번 번째 마리 잔 병 권 장 -> "한 개, 두 명, 스무 살".
  100 이상이거나 0, 소수, 쉼표가 있으면 한자어로.
- 월: 6월 = 유월, 10월 = 시월. 점수 "5대 0", "5:0" = "오 대 영". 소수 "0.362" = "영 점 삼육이". % = 퍼센트.
- 영문 대문자 약어는 알파벳 이름으로 (KBO = 케이비오).
"""
from __future__ import annotations

import re

from recap_shorts.script.text import num_to_korean

_ONES_DET = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉"}
_TENS = {1: "열", 2: "스물", 3: "서른", 4: "마흔", 5: "쉰", 6: "예순", 7: "일흔", 8: "여든", 9: "아흔"}
_DIGIT_READ = "영일이삼사오육칠팔구"

LETTERS = {"A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", "G": "지", "H": "에이치", "I": "아이",
           "J": "제이", "K": "케이", "L": "엘", "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알",
           "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유", "X": "엑스", "Y": "와이", "Z": "제트"}

# 긴 것부터. 시 는 시즌·시작 같은 낱말 앞에서는 단위가 아님.
_NATIVE_UNITS = ["번째", "시간", "마리", "번", "개", "명", "살", "시", "잔", "병", "권", "장"]
_UNIT_RE = "|".join(_NATIVE_UNITS)


def native_det(n: int) -> str:
    """1~99 의 고유어 관형형: 1 한, 2 두, 3 세, 4 네, 10 열, 20 스무, 21 스물한, 99 아흔아홉."""
    if n == 20:
        return "스무"
    t, o = divmod(n, 10)
    return (_TENS[t] if t else "") + (_ONES_DET[o] if o else "")


def _sino(tok: str) -> str:
    return num_to_korean(tok)


def _digits(tok: str) -> str:
    return "".join(_DIGIT_READ[int(c)] for c in tok)


def _decimal(tok: str) -> str:
    a, b = tok.replace(",", "").split(".", 1)
    return f"{_sino(a)} 점 {_digits(b)}"


_SCORE_RE = re.compile(r"(?<![\d,.])(\d[\d,]*)\s*(?:대|:)\s*(\d[\d,]*)(?![\d,])")
_NUM_RE = re.compile(rf"(\d[\d,]*\.\d+|\d[\d,]*)(\s?)(?:(월)|({_UNIT_RE})(?!즌|작|합|청|설|민|내|도|월)|)")
_ACRO_RE = re.compile(r"(?<![A-Za-z])[A-Z]+(?![A-Za-z])")
_MONTH = {6: "유월", 10: "시월"}


def _num_sub(m: re.Match) -> str:
    tok, sp, month, unit = m.group(1), m.group(2), m.group(3), m.group(4)
    if "." in tok:
        return _decimal(tok) + (sp if (month or unit) else "") + (month or unit or "")
    plain = tok.replace(",", "")
    n = int(plain) if plain.isdigit() and len(plain) <= 16 else None
    if month:
        if n in _MONTH:
            return _MONTH[n]
        return _sino(tok) + "월"
    if unit and n is not None and "," not in tok and 1 <= n <= 99 and not (len(plain) > 1 and plain[0] == "0"):
        if unit == "번째":
            return ("첫" if n == 1 else native_det(n)) + " 번째"
        return f"{native_det(n)} {unit}"
    return _sino(tok) + (sp if unit else "") + (unit or "")


# 목소리가 뭉개 읽는 외래어·용어를 소리 나는 대로 적은 것(자막은 원문 그대로). 받아쓰기 일치율로 골랐다.
# - 셧아웃: "샤사오/서사호"로 들림(0.80~0.83) → "셔다웃" 0.91
PRONOUNCE = {"셧아웃": "셔다웃"}


def to_spoken(text: str) -> str:
    for k, v in PRONOUNCE.items():
        text = text.replace(k, v)
    t = _SCORE_RE.sub(lambda m: f"{_sino(m.group(1))} 대 {_sino(m.group(2))}", text)
    t = _NUM_RE.sub(_num_sub, t)
    t = t.replace("%", " 퍼센트")
    t = _ACRO_RE.sub(lambda m: "".join(LETTERS[c] for c in m.group(0)), t)
    return t
