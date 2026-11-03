import json

import pytest

pytestmark = pytest.mark.live


def test_live_pipeline(tmp_path):
    from recap_shorts.collect.__main__ import run
    f = tmp_path / "n.json"
    f.write_text(json.dumps([{"title": "가짜 예시 제목", "outlet": "가짜일보", "date": "2026-10-05", "url": "https://x.example/a"}]),
                 encoding="utf-8")
    r = run("National Museum of Korea", "live_test", max_articles=1, photos=1, work_root=tmp_path, news_json=str(f))
    assert r["ok"]
