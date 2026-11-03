import io

import pytest
import json

from PIL import Image

from recap_shorts.collect import photos as P
from tests.collect.conftest import FakeResp


def test_license_filter():
    ok = ["CC0", "Public domain", "CC BY 2.0", "CC BY 4.0", "CC BY-SA 3.0", "CC BY-SA 4.0", "CC BY-SA 3.0 de", "CC BY 2.5"]
    bad = ["CC BY-NC 4.0", "CC BY-ND 2.0", "CC BY-NC-SA 3.0", "Fair use", "", "CC BY 1.0", "GFDL", "All rights reserved"]
    for s in ok:
        assert P.is_allowed_license(s), s
    for s in bad:
        assert not P.is_allowed_license(s), s


def test_parse_commons(fix):
    ph = P.parse_commons(json.loads(fix("commons_sample.json")))
    assert [p.title for p in ph] == ["File:Fake A.jpg", "File:Fake C.png"]  # NC, svg, fair use 제외
    a = ph[0]
    assert a.artist == "홍 길동 & 친구"  # HTML 제거, 엔티티 해제
    assert a.thumb_url.endswith("thumb/a.jpg") and a.page_url.startswith("https://commons")
    assert a.attribution_text() == "사진: 홍 길동 & 친구 / CC BY-SA 4.0 / Wikimedia Commons"
    assert "작성자 불명" in ph[1].attribution_text()


def test_search_commons_request(make_client, fix):
    c = make_client()
    calls = []

    class S:
        headers = {}

        def get(self, url, **kw):
            calls.append(url)
            if "/w/api.php" in url:
                return FakeResp(200, fix("commons_sample.json"), {"content-type": "application/json"})
            return FakeResp(404)

    c.session = S()
    res = P.search_commons("가짜", limit=10, client=c)
    assert len(res) == 2
    u = [x for x in calls if "/w/api.php" in x][0]
    for k in ("action=query", "generator=search", "gsrnamespace=6", "prop=imageinfo", "iiurlwidth=1080"):
        assert k in u


def test_download_photo(make_client, tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (20, 10), "red").save(buf, "JPEG")
    c = make_client({"https://upload.example/thumb/a.jpg": FakeResp(200, buf.getvalue(), {"content-type": "image/jpeg"})})
    ph = P.Photo("t", "p", "https://upload.example/a.jpg", "https://upload.example/thumb/a.jpg", "CC0", "", "x", 1, 1, "image/jpeg")
    out = P.download_photo(ph, tmp_path / "o" / "a.jpg", c)
    assert out.exists() and out.stat().st_size > 0


OV = {"results": [
    {"title": "가짜 A", "url": "https://o.example/a.jpg", "thumbnail": "https://api.openverse.org/v1/images/1/thumb/",
     "foreign_landing_url": "https://flickr.example/a", "creator": "작가 <b>A</b>", "license": "by-sa", "license_version": "4.0",
     "license_url": "https://creativecommons.org/licenses/by-sa/4.0/", "width": 800, "height": 600, "filetype": "jpg", "provider": "flickr"},
    {"title": "NC", "thumbnail": "t", "license": "by-nc", "license_version": "4.0", "filetype": "jpg"},
    {"title": "ND", "thumbnail": "t", "license": "by-nd", "license_version": "2.0", "filetype": "jpg"},
    {"title": "CC0", "thumbnail": "https://api.openverse.org/v1/images/2/thumb/", "license": "cc0", "license_version": "1.0",
     "creator": None, "filetype": "png", "provider": "wikimedia", "foreign_landing_url": "https://w.example/c"},
    {"title": "PDM", "thumbnail": "https://api.openverse.org/v1/images/3/thumb/", "license": "pdm", "license_version": "1.0",
     "creator": "누구", "filetype": "jpg", "provider": "met"},
    {"title": "old", "thumbnail": "t", "license": "by", "license_version": "1.0", "filetype": "jpg"},
    {"title": "svg", "thumbnail": "t", "license": "by", "license_version": "4.0", "filetype": "svg"},
]}


def test_parse_openverse_filter_and_attribution():
    ph = P.parse_openverse(OV)
    assert [p.title for p in ph] == ["가짜 A", "CC0", "PDM"]
    a = ph[0]
    assert a.license == "CC BY-SA 4.0" and a.artist == "작가 A"
    assert a.attribution_text() == "사진: 작가 A / CC BY-SA 4.0 / Openverse (flickr)"
    assert ph[1].license == "CC0" and ph[2].license == "Public domain"
    assert "작성자 불명" in ph[1].attribution_text()


def test_search_openverse_request_and_429(make_client):
    from recap_shorts.collect.http import BlockedError
    c = make_client({})
    calls = []

    class S:
        headers = {}

        def get(self, url, **kw):
            calls.append(url)
            return FakeResp(429, b"", {"content-type": "application/json"})
    c.session = S()
    with pytest.raises(BlockedError) as e:
        P.search_openverse("가짜", client=c)
    assert e.value.blocked.reason == "rate_limited_429"
    assert "license=cc0%2Cpdm%2Cby%2Cby-sa" in calls[-1] and "q=%EA%B0%80%EC%A7%9C" in calls[-1]
