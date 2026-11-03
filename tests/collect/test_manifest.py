import json

import pytest

from recap_shorts.collect.manifest import KINDS, Manifest

FIELDS = {"asset_id", "kind", "source_url", "site", "fetched_at", "license", "attribution",
          "file", "sha256", "robots_allowed", "flags", "note"}


def test_manifest_jsonl(tmp_path):
    job = tmp_path / "job"
    f = job / "assets" / "news" / "a.png"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"png-bytes")
    m = Manifest(job)
    m.add(kind="news_screenshot", source_url="https://x.example/a", site="x.example", file=f,
          flags={"found_headline": True, "overlay_suspected": False, "needs_manual_blur": False})
    m.add(kind="user_source", source_url="u", site="s", file=f, robots_allowed=None, note="n")
    p = m.save()
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert set(rec) == FIELDS
    assert rec["file"] == "assets/news/a.png" and len(rec["sha256"]) == 64
    assert rec["fetched_at"].endswith("+00:00")
    assert rec["flags"]["found_headline"] is True
    assert Manifest.load(p)[1]["robots_allowed"] is None


def test_manifest_rejects_unknown_kind(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        Manifest(tmp_path).add(kind="bogus", source_url="", site="", file=f)
    assert "ai_image" in KINDS
