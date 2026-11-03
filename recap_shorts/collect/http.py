"""공통 요청 계층: 속도 제한, robots.txt, 재시도, 캐시, 차단 처리.

설계 원칙: 정직한 User-Agent만 쓰고, 막히면(robots/401/403/429/캡차) 우회하지 않고
그 출처를 건너뛰며 이유를 기록한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .robots import Robots

import requests

import os

# 연락처는 환경변수 COLLECT_CONTACT로 바꿀 수 있음(기본: README 참고)
USER_AGENT = "recap-shorts-collector/0.1 (+personal research; contact %s)" % (os.environ.get("COLLECT_CONTACT") or "in README")
MIN_INTERVAL = 3.0
TIMEOUT = 20
MAX_REDIRECTS = 5

_CAPTCHA_MARKERS = (
    "g-recaptcha", "h-captcha", "hcaptcha", "cf-challenge", "challenge-platform",
    "captcha", "자동입력 방지", "로봇이 아닙니다", "비정상적인 트래픽",
)


@dataclass
class Blocked:
    """가져오지 못한 이유. reason: robots | auth_401 | forbidden_403 | rate_limited_429 | captcha | http_<code> | error"""
    url: str
    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.reason}: {self.url}" + (f" ({self.detail})" if self.detail else "")


class BlockedError(Exception):
    def __init__(self, blocked: Blocked):
        super().__init__(str(blocked))
        self.blocked = blocked


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    content: bytes
    headers: dict = field(default_factory=dict)
    from_cache: bool = False

    @property
    def text(self) -> str:
        ctype = self.headers.get("content-type", "")
        m = re.search(r"charset=([\w-]+)", ctype, re.I)
        cands = []
        if m:
            cands.append(m.group(1))
        else:
            m2 = re.search(rb"charset=[\"']?([\w-]+)", self.content[:3000], re.I)
            if m2:
                cands.append(m2.group(1).decode("ascii", "ignore"))
        cands += ["utf-8", "cp949"]
        for enc in cands:
            try:
                return self.content.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.content.decode("utf-8", "replace")


def looks_like_captcha(text: str) -> bool:
    """짧은 페이지에 캡차 표식이 있으면 캡차/봇 차단 페이지로 본다."""
    head = text[:20000].lower()
    if len(text) > 60000:
        return False
    return any(mark in head for mark in _CAPTCHA_MARKERS) and (
        len(text) < 20000 or "g-recaptcha" in head or "hcaptcha" in head
    )


class HttpClient:
    def __init__(self, job_dir: Path | str | None = None, *, min_interval: float = MIN_INTERVAL,
                 timeout: float = TIMEOUT, session: requests.Session | None = None,
                 time_fn=time.monotonic, sleep_fn=time.sleep, retry_wait: float = 2.0):
        self.job_dir = Path(job_dir) if job_dir else None
        self.cache_dir = (self.job_dir / "cache") if self.job_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._time = time_fn
        self._sleep = sleep_fn
        self.retry_wait = retry_wait
        self._last: dict[str, float] = {}
        self._robots: dict[str, Robots | None] = {}
        self.events: list[dict] = []

    # ---- 속도 제한 ----
    def wait_turn(self, url: str) -> None:
        """같은 도메인 요청 사이에 최소 min_interval초를 둔다(브라우저 접속에도 사용)."""
        host = urlparse(url).netloc.lower()
        last = self._last.get(host)
        if last is not None:
            gap = self.min_interval - (self._time() - last)
            if gap > 0:
                self._sleep(gap)
        self._last[host] = self._time()

    # ---- robots ----
    def _robots_for(self, url: str):
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        robots_url = origin + "/robots.txt"
        try:
            self.wait_turn(robots_url)
            r = self.session.get(robots_url, timeout=self.timeout, allow_redirects=True)
            if r.status_code in (401, 403):
                rp = Robots.disallow_all()
            elif r.status_code >= 500:
                rp = Robots.disallow_all()  # 불확실하면 보수적으로 금지
            elif r.status_code >= 400:
                rp = Robots.allow_all()  # robots.txt 없음 = 제한 없음
            else:
                rp = Robots(r.text)
        except requests.RequestException:
            rp = None  # 확인 불가
        self._robots[origin] = rp
        return rp

    def robots_allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        if rp is None:
            return False  # robots.txt를 확인할 수 없으면 가져오지 않음
        return rp.can_fetch(url)

    # ---- 캐시 ----
    def _cache_paths(self, url: str):
        if not self.cache_dir:
            return None, None
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{key}.body", self.cache_dir / f"{key}.json"

    def _cache_get(self, url: str) -> Response | None:
        body, meta = self._cache_paths(url)
        if body and body.exists() and meta.exists():
            m = json.loads(meta.read_text(encoding="utf-8"))
            return Response(url, m.get("final_url", url), m["status"], body.read_bytes(),
                            m.get("headers", {}), from_cache=True)
        return None

    def _cache_put(self, url: str, resp: Response) -> None:
        body, meta = self._cache_paths(url)
        if body:
            body.write_bytes(resp.content)
            meta.write_text(json.dumps({
                "url": url, "final_url": resp.final_url, "status": resp.status,
                "headers": {k.lower(): v for k, v in resp.headers.items()
                            if k.lower() in ("content-type", "content-length")},
            }, ensure_ascii=False), encoding="utf-8")

    # ---- 요청 ----
    def _log(self, url, outcome):
        self.events.append({"url": url, "outcome": outcome})

    def _get_once(self, url: str, timeout: float | None = None):
        """한 번 요청(재시도 1회 포함). 리다이렉트는 따라가지 않음. Response | Blocked."""
        last_err = ""
        for attempt in range(2):
            self.wait_turn(url)
            try:
                r = self.session.get(url, timeout=timeout or self.timeout, allow_redirects=False)
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}"
                if attempt == 0:
                    self._sleep(self.retry_wait)
                    continue
                return Blocked(url, "error", last_err)
            if r.status_code >= 500 and attempt == 0:
                self._sleep(self.retry_wait)
                continue
            return r
        return Blocked(url, "error", last_err)

    def fetch(self, url: str, *, check_robots: bool = True, use_cache: bool = True, timeout: float | None = None) -> Response | Blocked:
        """URL을 가져온다. 리다이렉트는 단계마다 robots·속도 제한을 적용해 직접 따라간다."""
        if use_cache:
            cached = self._cache_get(url)
            if cached:
                self._log(url, "cache")
                return cached
        cur = url
        for _ in range(MAX_REDIRECTS + 1):
            if check_robots and not self.robots_allowed(cur):
                self._log(cur, "blocked:robots")
                return Blocked(cur, "robots")
            r = self._get_once(cur, timeout)
            if isinstance(r, Blocked):
                self._log(cur, f"blocked:{r.reason}")
                return r
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                cur = urljoin(cur, r.headers["Location"])
                continue
            break
        else:
            return Blocked(cur, "error", "too many redirects")

        code = r.status_code
        if code == 401:
            b = Blocked(cur, "auth_401", "로그인 필요")
        elif code == 403:
            b = Blocked(cur, "forbidden_403")
        elif code == 429:
            b = Blocked(cur, "rate_limited_429", r.headers.get("Retry-After", ""))
        elif code >= 400:
            b = Blocked(cur, f"http_{code}")
        else:
            b = None
        if b:
            self._log(cur, f"blocked:{b.reason}")
            return b
        resp = Response(url, cur, code, r.content, dict(r.headers))
        ctype = resp.headers.get("content-type", "").lower()
        if "html" in ctype or not ctype:
            if looks_like_captcha(resp.text):
                self._log(cur, "blocked:captcha")
                return Blocked(cur, "captcha")
            if len(resp.content) < 2000 and len(re.sub(r"<[^>]+>|\s+", "", re.sub(r"(?is)<(style|script).*?</\1>", "", resp.text))) < 20:
                self._log(cur, "blocked:soft_block")
                return Blocked(cur, "soft_block", "200이지만 본문 없는 짧은 페이지(사실상 차단)")
        self._cache_put(url, resp)
        self._log(url, "ok")
        return resp

    def follow_redirects_only(self, url: str) -> tuple[str, Blocked | None]:
        """본문은 쓰지 않고 최종 주소만 알아낸다(구글 뉴스 링크 풀기용). 캐시 사용 안 함."""
        cur = url
        for _ in range(MAX_REDIRECTS + 1):
            if not self.robots_allowed(cur):
                return cur, Blocked(cur, "robots")
            r = self._get_once(cur)
            if isinstance(r, Blocked):
                return cur, r
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                cur = urljoin(cur, r.headers["Location"])
                continue
            if r.status_code in (401, 403, 429):
                return cur, Blocked(cur, {401: "auth_401", 403: "forbidden_403", 429: "rate_limited_429"}[r.status_code])
            return cur, None
        return cur, Blocked(cur, "error", "too many redirects")
