from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "collect"


class FakeResp:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code = status
        self.content = content if isinstance(content, bytes) else content.encode("utf-8")
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")


class FakeSession:
    """routes: {url: FakeResp | [FakeResp,...]}. 등록 안 된 주소(robots.txt 포함)는 404."""
    def __init__(self, routes=None):
        self.headers = {}
        self.routes = routes or {}
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        r = self.routes.get(url)
        if r is None:
            return FakeResp(404, b"")
        if isinstance(r, list):
            return r.pop(0) if len(r) > 1 else r[0]
        return r


class Clock:
    def __init__(self):
        self.t = 100.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def fix():
    return lambda name: (FIX / name).read_bytes()


@pytest.fixture
def make_client(tmp_path):
    from recap_shorts.collect.http import HttpClient

    def _make(routes=None, **kw):
        clock = Clock()
        sess = FakeSession(routes)
        c = HttpClient(tmp_path / "job", session=sess, time_fn=clock.now, sleep_fn=clock.sleep, **kw)
        c.clock, c.sess = clock, sess
        return c
    return _make
