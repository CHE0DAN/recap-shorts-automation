import json
from dataclasses import asdict
from datetime import datetime

import pytest

from recap_shorts.collect import blind as B
from recap_shorts.collect.http import BlockedError
from tests.collect.conftest import FakeResp

POST = "https://www.teamblind.com/kr/post/aaaa0001"
POST_SLUG = "https://www.teamblind.com/kr/post/%EA%B0%80%EC%83%81-%EC%A0%9C%EB%AA%A9-%ED%95%98%EB%82%98-aaaa0001"
ROBOTS = "https://www.teamblind.com/robots.txt"
RULES = "User-agent: *\nDisallow: /kr/search/\nDisallow: /kr/user/history\n"
NOW = datetime.fromisoformat("2026-11-02T12:00:00+09:00")


def test_urls():
    assert B.list_url() == "https://www.teamblind.com/kr/topics/%ED%86%A0%ED%94%BD-%EB%B2%A0%EC%8A%A4%ED%8A%B8"
    assert B.post_url("aaaa0001") == POST
    assert B.parse_blind_url(POST) == ("aaaa0001", POST)
    assert B.parse_blind_url(POST_SLUG) == ("aaaa0001", POST)
    assert B.parse_blind_url("teamblind.com/kr/post/aaaa0001") == ("aaaa0001", POST)
    for bad in ("https://gall.dcinside.com/board/view/?id=dcbest&no=1",
                "https://www.teamblind.com/kr/topics/%ED%86%A0%ED%94%BD-%EB%B2%A0%EC%8A%A4%ED%8A%B8",
                "https://www.teamblind.com/kr/post/", "https://www.teamblind.com/kr/post/a"):
        with pytest.raises(ValueError):
            B.parse_blind_url(bad)


def test_parse_list_skips_ads_and_products_and_orders(fix):
    items = B.parse_list(fix("blind_list.html").decode("utf-8"), NOW)
    got = {i.no: i for i in items}
    assert set(got) == {"aaaa0001", "bbbb0002", "cccc0003", "eeee0005"}   # 광고 줄·상품 줄·작성시간 없는 줄 제외
    a = got["aaaa0001"]
    assert a.title == "[가상] 테스트 제목 하나" and a.tag == ""
    assert a.views == 1234 and a.recommends == 12 and a.comments == 3
    assert a.age_hours == 5.0 and a.posted_at == "2026-11-02T07:00:00+09:00" and a.url == POST
    b = got["bbbb0002"]
    assert b.tag == "테스트토픽" and b.views == 13000 and b.comments == 78 and b.age_hours == 24.0
    assert got["cccc0003"].age_hours == 0.5
    assert got["eeee0005"].views == 1_200_000 and got["eeee0005"].age_hours == 72.0
    assert [i.no for i in B.sort_items(items, "views")][0] == "eeee0005"
    assert [i.no for i in B.sort_items(items, "comments")][0] == "cccc0003"
    assert [i.no for i in B.sort_items(items, "recent")][0] == "cccc0003"


def test_parse_list_has_no_author_fields(fix):
    dumped = json.dumps([asdict(i) for i in B.parse_list(fix("blind_list.html").decode("utf-8"), NOW)], ensure_ascii=False)
    for secret in ("가상회사", "다른회사", "가******", "나******"):
        assert secret not in dumped


def test_parse_post_and_no_author(fix):
    p = B.parse_post(fix("blind_post.html").decode("utf-8"), POST, "aaaa0001")
    assert p.title == "[가상] 테스트 제목 하나"          # h1 앞 회사 링크는 떼어 낸다
    assert p.text == "첫 줄 가상 본문\n둘째 줄 가상 본문\n셋째 줄 링크 끝"
    assert p.written_at == "2026-11-01 23:00"            # ld+json UTC → KST
    assert p.views == 1234 and p.recommends == 12
    assert p.images == ["https://d2u3dcdbebyaiu.cloudfront.net/uploads/atch_img/1/aaaa_res.jpeg",
                        "https://d2u3dcdbebyaiu.cloudfront.net/uploads/atch_img/2/bbbb_res.jpeg"]
    assert p.topic == "테스트토픽" and p.gallery_id == "blind" and p.no == "aaaa0001"
    dumped = json.dumps(asdict(p), ensure_ascii=False)
    for secret in ("가상회사", "가상작성자", "가******"):
        assert secret not in dumped
    assert {"nick", "nickname", "author", "writer", "company"}.isdisjoint(asdict(p))


def test_get_post_and_best_via_client(make_client, fix):
    c = make_client({ROBOTS: FakeResp(200, RULES), POST: FakeResp(200, fix("blind_post.html")),
                     B.BEST_URL: FakeResp(200, fix("blind_list.html"))})
    assert B.get_post("blind", "aaaa0001", client=c).title == "[가상] 테스트 제목 하나"
    got = B.fetch_best(hours=48, sort="comments", client=c, now=NOW)
    assert [i.no for i in got][0] == "cccc0003" and "eeee0005" not in [i.no for i in got]
    assert len(c.sess.calls) == 2 + 1                    # robots + 두 페이지(한 쪽뿐)


def test_blocked_and_wrong_host_not_bypassed(make_client):
    c = make_client({ROBOTS: FakeResp(200, "User-agent: *\nDisallow: /\n")})
    with pytest.raises(B.BlindNotAllowed):
        B.fetch_best(client=c)
    with pytest.raises(BlockedError):
        B.get_post("blind", "aaaa0001", client=c)
    assert not any("/kr/post/" in u for u in c.sess.calls)


def test_403_skipped(make_client):
    c = make_client({POST: FakeResp(403)})
    with pytest.raises(BlockedError) as e:
        B.get_post("blind", "aaaa0001", client=c)
    assert e.value.blocked.reason == "forbidden_403"


def test_screenshot_no_empty_overlay_style(monkeypatch, tmp_path):
    """블라인드는 늦게 얹히는 안내가 없어 지울 선택자가 비어 있다 — 빈 content 로 add_style_tag 를 부르면
    Playwright 가 'Provide an object with a url, path or content property' 로 죽어 캡처가 통째로 실패했다."""
    style_calls = []

    class Page:
        url = POST

        def goto(self, *a, **k):
            pass

        def wait_for_selector(self, *a, **k):
            raise RuntimeError("없음")

        def wait_for_timeout(self, *a, **k):
            pass

        def evaluate(self, *a, **k):
            return None

        def add_style_tag(self, **kw):
            assert kw.get("content"), "빈 content 로 부르면 안 된다"
            style_calls.append(kw)

        def screenshot(self, **kw):
            from PIL import Image
            Image.new("RGB", (40, 40), (255, 255, 255)).save(kw["path"])

    class Ctx:
        def new_page(self):
            return Page()

        def close(self):
            pass

    class Br:
        def new_context(self, **k):
            return Ctx()

    class Edge:
        def __enter__(self):
            return Br()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(B, "edge_browser", lambda: Edge())
    monkeypatch.setattr(B, "_guard", lambda url, client: None)
    monkeypatch.setattr(B, "apply_blur", lambda page, sels: {s: 1 for s in sels})
    monkeypatch.setattr(B, "apply_ad_hide", lambda page, sels: 0)
    out = tmp_path / "shot.png"
    shot = B.screenshot_post(POST, out)
    assert out.is_file() and shot.needs_manual_blur is True     # 글 영역 상자를 못 찾음 → 사람이 가림 확인
    assert style_calls == []                                     # 지울 안내 선택자가 없으면 style 태그도 넣지 않는다
