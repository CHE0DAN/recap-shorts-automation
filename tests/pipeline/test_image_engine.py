"""AI 그림 엔진(image_engine) 고르기 시험: 로컬 서버 켜짐/꺼짐 × Gemini 키 있음/없음 — 네트워크 없이."""
import requests
import pytest

from recap_shorts import settings
from recap_shorts.images import provider


class Resp:
    def __init__(self, status=200, content=b"", text=""):
        self.status_code, self.content, self.text = status, content, text


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    provider._limit_until[0] = 0.0
    provider._PROBE.update(at=0.0, up=False)
    monkeypatch.setattr(provider, "FALLBACK", "gemini")
    yield
    provider._limit_until[0] = 0.0
    provider._PROBE.update(at=0.0, up=False)


def server(up: bool):
    def get(*a, **k):
        if not up:
            raise requests.ConnectionError()
        return Resp(200)
    return get


def gemini_result(monkeypatch, calls):
    def fake(prompt, out_png, aspect="landscape", **kw):
        calls.append((prompt, str(out_png), aspect))
        return {"ok": True, "file": str(out_png), "seconds": 0.0, "error": None, "engine": "gemini"}
    monkeypatch.setattr("recap_shorts.images.gemini_image.generate", fake)


@pytest.mark.parametrize("engine,up,key,avail,mode", [
    ("local", True, False, True, "local"),
    ("local", False, False, False, "local"),
    ("local", False, True, False, "local"),
    ("gemini", True, True, True, "gemini"),
    ("gemini", True, False, False, "gemini"),
    ("off", True, True, False, "off"),
])
def test_available_and_engine_status(monkeypatch, engine, up, key, avail, mode):
    monkeypatch.setattr(requests, "get", server(up))
    settings.save({}, engine)
    if key:
        settings.save({"gemini_api_key": "test-gemini-key-0000000000"})
    assert provider.available() is avail
    assert provider.engine() == mode
    ok, used, detail = provider.engine_status()
    assert used == mode and ok is avail
    assert detail == {"local": "로컬 이미지 서버로 만듦", "gemini": "Gemini 이미지로 만듦",
                      "off": "AI 그림 꺼짐 — 캡처 카드만"}[mode]


def test_default_engine_is_gemini_even_with_server_up(monkeypatch, tmp_path):
    """고른 적이 없으면 Gemini — 로컬 서버가 켜져 있어도 그쪽으로 가지 않는다(예전 '자동'은 뺐다)."""
    calls = []
    gemini_result(monkeypatch, calls)
    monkeypatch.setattr(requests, "get", server(True))
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("로컬 서버로 가면 안 됨")))
    settings.save({"gemini_api_key": "test-gemini-key-0000000000"})
    assert settings.image_engine() == "gemini" and provider.engine() == "gemini"
    r = provider.generate("scene", tmp_path / "a.png")
    assert r["ok"] and calls == [("scene", str(tmp_path / "a.png"), "landscape")]


def test_generate_gemini_engine_ignores_local_server(monkeypatch, tmp_path):
    calls = []
    gemini_result(monkeypatch, calls)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("로컬 서버로 가면 안 됨")))
    settings.save({"gemini_api_key": "test-gemini-key-0000000000"}, "gemini")
    assert provider.generate("scene", tmp_path / "b.png")["ok"] and calls


def test_generate_off_makes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("부르면 안 됨")))
    settings.save({}, "off")
    r = provider.generate("scene", tmp_path / "c.png")
    assert not r["ok"] and "off" in r["error"] and not (tmp_path / "c.png").exists()


def test_generate_local_engine_uses_server(monkeypatch, tmp_path):
    from tests.pipeline.fakes import png as mk
    mk(tmp_path / "src.png")
    data = (tmp_path / "src.png").read_bytes()
    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(200, content=data))
    settings.save({}, "local")
    r = provider.generate("scene", tmp_path / "d.png")
    assert r["ok"] and (tmp_path / "d.png").read_bytes() == data


def test_usage_limit_falls_back_to_gemini(monkeypatch, tmp_path):
    calls = []
    gemini_result(monkeypatch, calls)

    def post(url, json=None, timeout=None):
        return Resp(400, text='{"error": "usage_limit_reached"}')
    monkeypatch.setattr(requests, "get", server(True))
    monkeypatch.setattr(requests, "post", post)
    settings.save({}, "local")
    r = provider.generate("scene", tmp_path / "f.png")
    assert r["ok"] and r.get("fallback_from") and calls
    assert provider._limit_until[0] > 0                 # 다음 장은 로컬 서버를 건너뛴다
    calls.clear()
    assert provider.generate("scene2", tmp_path / "g.png")["ok"] and calls


def test_local_server_up_is_cached(monkeypatch):
    hits = {"n": 0}

    def get(*a, **k):
        hits["n"] += 1
        return Resp(200)
    monkeypatch.setattr(requests, "get", get)
    assert provider.local_server_up() is True and provider.local_server_up() is True
    assert hits["n"] == 1
    provider._PROBE["at"] = 0.0                          # 60초 지난 것으로
    assert provider.local_server_up() is True and hits["n"] == 2


def test_legacy_base_url_ignores_engine(monkeypatch, tmp_path):
    from tests.pipeline.fakes import png as mk
    mk(tmp_path / "src.png")
    data = (tmp_path / "src.png").read_bytes()
    seen = {}

    def post(url, json=None, timeout=None):
        seen["url"] = url
        return Resp(200, content=data)
    monkeypatch.setattr(requests, "post", post)
    settings.save({}, "off")                            # off 여도 base_url 을 주면 로컬 서버(예전 동작)
    assert provider.generate("p", tmp_path / "h.png", base_url="http://127.0.0.1:9999")["ok"]
    assert seen["url"].startswith("http://127.0.0.1:9999/")


def test_local_url_reads_env_at_call_time(monkeypatch):
    monkeypatch.setenv("RECAP_IMAGE_URL", "http://127.0.0.1:1234")
    assert provider.local_url() == "http://127.0.0.1:1234"
    assert settings.public_view()["image_server"]["url"] == "http://127.0.0.1:1234"
