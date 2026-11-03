import json
from dataclasses import asdict

import pytest

from recap_shorts.collect import dcinside as D
from recap_shorts.collect.http import BlockedError
from tests.collect.conftest import FakeResp

LIST = "https://gall.dcinside.com/board/lists/?id=fakegall&page=1"
VIEW = "https://gall.dcinside.com/board/view/?id=fakegall&no=2001"
ROBOTS = "https://gall.dcinside.com/robots.txt"
RULES = "User-agent: *\nAllow: /\nDisallow: /board/lists/?id=blocked\nDisallow: /board/view/?id=blocked\nDisallow: /*s_keyword=\n"


def test_urls():
    assert D.list_url("programming") == "https://gall.dcinside.com/board/lists/?id=programming&page=1"
    assert "mgallery" in D.list_url("x", minor=True)
    assert "s_keyword=%ED%8C%8C" in D.list_url("x", keyword="파")
    with pytest.raises(ValueError):
        D.list_url("a/../b")


def test_parse_list_skips_ads_and_notices(fix):
    ps = D.parse_list(fix("dc_list.html").decode("utf-8"), "fakegall")
    assert [p.no for p in ps] == [2001, 2000]
    a = ps[0]
    assert a.title == "파이썬 가짜 질문입니다" and a.views == 1234 and a.recommends == 5 and a.comments == 3
    assert a.url == VIEW


def test_parse_post_and_no_nick_ip(fix):
    post = D.parse_post(fix("dc_view.html").decode("utf-8"), "fakegall", 2001, VIEW)
    assert post.title == "잡담 파이썬 가짜 질문입니다"
    assert post.text == "가짜 본문 첫 줄입니다.\n둘째 줄\n강조" or "가짜 본문 첫 줄입니다." in post.text
    assert post.written_at == "2026-10-17 02:15:11" and post.views == 1234 and post.recommends == 5
    assert post.images == ["https://dcimg.example/real.jpg"]  # 아이콘·iframe 제외
    dumped = json.dumps(asdict(post), ensure_ascii=False)
    for secret in ("가짜닉네임", "댓글닉", "1.2", "9.9"):
        assert secret not in dumped
    assert {"nick", "nickname", "ip", "author", "writer"}.isdisjoint(asdict(post))


def test_list_and_get_via_client(make_client, fix):
    c = make_client({ROBOTS: FakeResp(200, RULES), LIST: FakeResp(200, fix("dc_list.html")),
                     VIEW: FakeResp(200, fix("dc_view.html"))})
    assert len(D.list_posts("fakegall", client=c)) == 2
    assert D.get_post("fakegall", 2001, client=c).no == 2001


def test_blocked_gallery_skipped_not_fetched(make_client):
    c = make_client({ROBOTS: FakeResp(200, RULES)})
    with pytest.raises(BlockedError) as e:
        D.list_posts("blocked", client=c)
    assert e.value.blocked.reason == "robots"
    with pytest.raises(BlockedError):
        D.get_post("blocked", 1, client=c)
    assert not any("id=blocked" in u for u in c.sess.calls)


def test_keyword_search_not_allowed(make_client):
    c = make_client({ROBOTS: FakeResp(200, RULES)})
    with pytest.raises(D.NotAllowed):
        D.list_posts("fakegall", keyword="파이썬", client=c)


def test_403_and_captcha_skipped(make_client):
    c = make_client({VIEW: FakeResp(403)})
    with pytest.raises(BlockedError) as e:
        D.get_post("fakegall", 2001, client=c)
    assert e.value.blocked.reason == "forbidden_403"


def test_parse_dc_url():
    assert D.parse_dc_url(VIEW) == ("fakegall", 2001, False)
    assert D.parse_dc_url("https://gall.dcinside.com/mgallery/board/view/?id=a&no=3") == ("a", 3, True)
    with pytest.raises(ValueError):
        D.parse_dc_url("https://example.com/?id=a&no=1")


def test_list_url_recommend_mode():
    from recap_shorts.collect.dcinside import list_url
    u = list_url("baseball_new11", recommend=True)
    assert "exception_mode=recommend" in u and "id=baseball_new11" in u
