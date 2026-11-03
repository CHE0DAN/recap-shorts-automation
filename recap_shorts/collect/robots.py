"""robots.txt 해석(RFC 9309 방식: 가장 긴 규칙 우선, 같으면 Allow, `*`·`$` 지원).

urllib.robotparser는 파일에서 먼저 나온 규칙을 쓰기 때문에 `Allow: /`가 맨 앞에 있는 사이트(예: 디시인사이드)의
세부 Disallow를 놓친다. 그래서 직접 만든다.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


def _pattern_to_re(pat: str):
    anchored = pat.endswith("$")
    if anchored:
        pat = pat[:-1]
    rx = ".*".join(re.escape(p) for p in pat.split("*"))
    return re.compile("^" + rx + ("$" if anchored else ""))


class Robots:
    def __init__(self, text: str = "", agent: str = "recap-shorts-collector"):
        self.agent = agent.lower()
        self.rules: list[tuple[bool, str, re.Pattern]] = []
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = [x.strip() for x in line.split(":", 1)]
            key = key.lower()
            if key == "user-agent":
                if not last_was_agent:
                    if agents:
                        groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(val.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if val == "" and key == "disallow":
                    continue  # 빈 Disallow = 제한 없음
                rules.append((key == "allow", val))
            else:
                last_was_agent = False
        if agents:
            groups.append((agents, rules))
        specific = [r for ag, r in groups if any(a != "*" and a in self.agent for a in ag)]
        star = [r for ag, r in groups if "*" in ag]
        chosen = specific or star
        for r in chosen:
            for allow, pat in r:
                self.rules.append((allow, pat, _pattern_to_re(pat)))

    def can_fetch(self, url: str) -> bool:
        u = urlparse(url)
        target = (u.path or "/") + (("?" + u.query) if u.query else "")
        best_len, allowed = -1, True
        for allow, pat, rx in self.rules:
            if rx.match(target):
                n = len(pat)
                if n > best_len or (n == best_len and allow):
                    best_len, allowed = n, allow
        return allowed

    @classmethod
    def allow_all(cls) -> "Robots":
        return cls("")

    @classmethod
    def disallow_all(cls) -> "Robots":
        return cls("User-agent: *\nDisallow: /")
