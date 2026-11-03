import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recap_shorts.app import create_app
from recap_shorts.collect import dcbest as B
from tests.pipeline.fakes import FakeDeps

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=KST)
FIX = Path(__file__).parent / "fixtures" / "dcbest"


@pytest.fixture
def env(tmp_path, monkeypatch):
    items = B.parse_best_list((FIX / "list_page1.html").read_text(encoding="utf-8"), NOW)
    calls = {"fetch": 0, "triage": []}

    def fake_fetch(pages=3, hours=48, sort="views", client=None, now=None, max_pages=5):
        calls["fetch"] += 1
        return B.sort_items([i for i in items if i.age_hours <= hours], sort)
    monkeypatch.setattr(B, "fetch_best", fake_fetch)
    deps = FakeDeps()

    def triage(posts):
        calls["triage"] += [p["no"] for p in posts]
        return [{"no": p["no"], "category": {"politics": 0.8, "other": 0.2}, "hidden": p["no"] == 1001,
                 "hidden_by": ["person_attack"] if p["no"] == 1001 else []} for p in posts]
    deps.clef_triage = triage
    app = create_app(work_root=tmp_path, deps=deps)
    with TestClient(app) as client:
        yield client, calls, tmp_path


def test_dcbest_topics_shape_and_hidden(env):
    client, calls, root = env
    r = client.get("/api/topics?source=dcbest&sort=views&hours=48&pages=3").json()
    assert r["source"] == "dcbest" and r["triage"] == "ok" and len(r["items"]) == 6
    assert [i["views"] for i in r["items"]] == sorted((i["views"] for i in r["items"]), reverse=True)
    top = next(i for i in r["items"] if i["no"] == 1006)
    assert top["tag"] == "싱갤" and top["source_check"] is True and top["category"]["label"] == "정치"
    hid = next(i for i in r["items"] if i["no"] == 1001)
    assert hid["hidden"] and hid["hidden_reason"] == ["특정인 비난·조롱이 중심"] and r["hidden_count"] == 1
    assert top["url"].endswith("id=dcbest&no=1006")
    assert "nick" not in json.dumps(r).lower()


def test_triage_cached_per_post(env):
    client, calls, root = env
    client.get("/api/topics?source=dcbest")
    n = len(calls["triage"])
    assert n == 6 and len(list((root / "_topics").glob("triage_*.json"))) == 6
    client.post("/api/topics/refresh", json={"source": "dcbest"})
    assert calls["fetch"] == 2 and len(calls["triage"]) == n          # 목록은 다시 받아도 분류는 다시 안 물음


def test_sort_and_window(env):
    client, calls, root = env
    r = client.get("/api/topics?source=dcbest&sort=comments").json()
    assert [i["comments"] for i in r["items"]] == sorted((i["comments"] for i in r["items"]), reverse=True)
    assert len(client.get("/api/topics?source=dcbest&hours=1").json()["items"]) == 4
    assert client.get("/api/topics?source=dcbest&sort=zzz").status_code == 400


def test_triage_unavailable_state(env):
    client, calls, root = env
    client.app.state.deps.clef_triage = lambda posts: None            # 키 없음·하루 한도(429) 흉내
    r = client.get("/api/topics?source=dcbest&refresh=true").json()
    assert r["triage"] == "unavailable" and r["triage_note"] and len(r["items"]) == 6
    assert all(i["category"] is None and not i["hidden"] and not i["triaged"] for i in r["items"])
    assert not list((root / "_topics").glob("triage_*.json")) if (root / "_topics").exists() else True


def test_budget_stops_triage():
    items = [B.BestItem(n, "t", "디갤", 1, 1, 1, "x", 1.0, "u") for n in range(1, 25)]
    spent = {"n": 0.0}

    def tri(posts):
        spent["n"] += 100
        return [{"no": p["no"]} for p in posts]
    got, state, note = B.triage_items(items, tri, None, batch=8, neuron_budget=150, spent_fn=lambda: spent["n"])
    assert state == "partial" and len(got) == 16 and "한도" in note


def test_job_from_topic_url(env):
    client, calls, root = env
    r = client.post("/api/jobs", json={"url": "https://gall.dcinside.com/board/view/?id=dcbest&no=1006", "title": "t"})
    assert r.status_code == 200 and "dcbest_1006" in r.json()["id"]
    r = client.post("/api/jobs", json={"url": "https://m.dcinside.com/board/dcbest/1007"})
    assert r.status_code == 200 and "dcbest_1007" in r.json()["id"]


def test_all_errors_429_stops_after_first_batch():
    items = [B.BestItem(n, "t", "디갤", 1, 1, 1, "x", 1.0, "u") for n in range(1, 25)]
    asked = []

    def tri(posts):
        asked.append(len(posts))
        return [{"no": p["no"], "error": "Cloudflare answered HTTP 429: 4006: daily free allocation"} for p in posts]
    got, state, note = B.triage_items(items, tri, None, batch=8)
    assert asked == [8] and state == "unavailable" and "429" in note and got == {}
