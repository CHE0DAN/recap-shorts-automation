"""한국어 글자 처리: 음절 세기, 비교용 정규화, 숫자 읽기.

음절 수 = 말로 읽었을 때의 음절. 한글 글자는 1, 숫자는 한국어로 읽은 음절 수(980 -> 구백팔십 = 5),
알파벳은 글자당 1(KBO -> 3)로 어림한다. 기호·공백은 세지 않는다.
"""
from __future__ import annotations

import re
import unicodedata

_DIG = "영일이삼사오육칠팔구"
_UNIT_S = ["", "십", "백", "천"]
_UNIT_B = ["", "만", "억", "조"]


def _section(n: int) -> str:
    out = ""
    for i, ch in enumerate(reversed(str(n))):
        d = int(ch)
        if d == 0:
            continue
        out = ("" if (d == 1 and i > 0) else _DIG[d]) + _UNIT_S[i] + out
    return out


def num_to_korean(s: str) -> str:
    """'980' -> '구백팔십', '10000' -> '만'. 쉼표는 무시. 너무 길면(>16자리) 숫자별로 읽는다."""
    s = s.replace(",", "")
    if not s.isdigit():
        return s
    if len(s) > 16 or (len(s) > 1 and s[0] == "0"):
        return "".join(_DIG[int(c)] for c in s)
    n = int(s)
    if n == 0:
        return "영"
    parts = []
    i = 0
    while n > 0:
        n, r = divmod(n, 10000)
        if r:
            sec = _section(r)
            if r == 1 and i == 1:
                sec = ""          # 일만 -> 만
            parts.append(sec + _UNIT_B[i])
        i += 1
    return "".join(reversed(parts))


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _read_number(m: re.Match) -> str:
    tok = m.group(0)
    if "." in tok:
        a, b = tok.split(".", 1)
        return num_to_korean(a) + "점" + "".join(_DIG[int(c)] for c in b)
    return num_to_korean(tok)


def spoken_form(text: str) -> str:
    """숫자를 한국어 낱말로 바꾼 글. 음절 세기·받아쓰기 비교에 쓴다."""
    return _NUM_RE.sub(_read_number, unicodedata.normalize("NFC", text))


def count_syllables(text: str) -> int:
    t = spoken_form(text)
    n = 0
    for ch in t:
        if "가" <= ch <= "힣":
            n += 1
        elif ch.isascii() and ch.isalpha():
            n += 1
    return n


_STRIP_RE = re.compile(r"[^0-9a-z가-힣ㄱ-ㆎ]+")


def normalize_loose(text: str) -> str:
    """근거 대조용: 공백·따옴표·문장부호를 모두 없애고 소문자로. (한글·영숫자만 남김)"""
    t = unicodedata.normalize("NFKC", text or "").lower()
    return _STRIP_RE.sub("", t)


def normalize_spoken(text: str) -> str:
    """받아쓰기 비교용: 숫자를 읽은 꼴로 바꾼 뒤 normalize_loose."""
    return normalize_loose(spoken_form(unicodedata.normalize("NFKC", text or "")))
