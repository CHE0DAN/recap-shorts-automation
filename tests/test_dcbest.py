from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from recap_shorts.collect import dcbest as B
from recap_shorts.collect import dcinside as D

FIX = Path(__file__).parent / "fixtures" / "dcbest"
KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=KST)


def html():
    return (FIX / "list_page1.html").read_text(encoding="utf-8")


def test_parse_list_fields():
    items = B.parse_best_list(html(), NOW)
    by = {i.no: i for i in items}
    assert 3001 not in by and len(items) == 6            # 공지 줄·설문 줄 제외
    a = by[1001]
    assert (a.tag, a.views, a.recommends, a.comments) == ("더갤", 830, 9, 39)
    assert a.title.startswith("속보]") and "[더갤]" not in a.title
    assert a.posted_at == "2026-10-18T12:10:02+09:00" and a.age_hours == 0.3
    assert a.url == "https://gall.dcinside.com/board/view/?id=dcbest&no=1001"
    assert by[1004].tag == "싱갤" and by[1004].views == 12528 and by[1004].comments == 181


def test_no_writer_info_fields():
    assert set(B.BestItem.__dataclass_fields__) == {"no", "title", "tag", "views", "recommends", "comments", "posted_at",
                                                    "age_hours", "url"}


def test_reply_with_voice_count():
    assert B._reply("[61/1]") == 61 and B._reply("") == 0


def test_sorts():
    items = B.parse_best_list(html(), NOW)
    assert [i.views for i in B.sort_items(items, "views")] == sorted((i.views for i in items), reverse=True)
    assert [i.comments for i in B.sort_items(items, "comments")] == sorted((i.comments for i in items), reverse=True)
    assert [i.age_hours for i in B.sort_items(items, "recent")] == sorted(i.age_hours for i in items)


class FakeClient:
    def __init__(self, pages, allowed=True):
        self.pages, self.allowed, self.urls = pages, allowed, []

    def robots_allowed(self, url):
        return self.allowed

    def fetch(self, url, **kw):
        self.urls.append(url)
        n = int(url.rsplit("page=", 1)[1])
        text = self.pages.get(n, "<html><body></body></html>")

        class R:
            pass
        r = R()
        r.text = text
        return r


def test_fetch_pages_window_and_robots():
    c = FakeClient({1: html(), 2: html()})
    items = B.fetch_best(pages=2, hours=48, client=c, now=NOW)
    assert len(c.urls) == 2 and len(items) == 6                      # 같은 글 중복 제거
    assert len(B.fetch_best(pages=1, hours=1, client=FakeClient({1: html()}), now=NOW)) == 4   # 1시간 안: 12:10 12:00 11:50 11:40
    assert len(B.fetch_best(pages=1, hours=48, client=FakeClient({1: html()}), now=NOW + timedelta(days=5))) == 0
    with pytest.raises(B.DcbestNotAllowed):
        B.fetch_best(pages=1, client=FakeClient({}, allowed=False), now=NOW)
    c2 = FakeClient({1: html(), 2: html(), 3: html()})
    B.fetch_best(pages=99, client=c2, now=NOW + timedelta(days=5))     # 최대 5쪽, 창 밖이면 일찍 멈춤
    assert len(c2.urls) == 1


def test_source_check_rules():
    cfg = B.load_config()
    assert B.source_check("싱갤", "아무 제목", cfg)
    assert B.source_check("", "트위터에서 화제된 글", cfg)
    assert B.source_check("잡갤", "jtbc) 백악관 대변인 경질", cfg)
    assert B.source_check("디갤", "가볍게 단렌즈로 저녁산책", cfg) is None
    assert B.source_check("디갤", "제목", {"source_check": {"galleries": ["디갤"]}})


def test_parse_dc_url_variants():
    assert D.parse_dc_url("https://m.dcinside.com/board/dcbest/1007") == ("dcbest", 1007, False)
    assert D.parse_dc_url("https://gall.dcinside.com/board/view/?id=dcbest&no=1007&_dcbest=1&page=1") == ("dcbest", 1007, False)
    with pytest.raises(ValueError):
        D.parse_dc_url("https://m.dcinside.com/board/programming/1")
    with pytest.raises(ValueError):
        D.parse_dc_url("https://example.com/board/dcbest/1")


VIEW = """<html><body><div class="view_content_wrap"><header><div class="gallview_head clear ub-content">
<h3 class="title ub-word"><span class="title_headtext"></span><span class="title_subject">[가상] 풍경</span></h3>
<div class="gall_writer ub-writer"><span class="gall_date" title="2026-10-18 09:20:02">2026.10.18 09:20:02</span>
<span class="gall_count">조회 8713</span><span class="gall_reply_num">추천 55</span></div></div></header>
<div class="write_div"><p>본문 한 줄</p><div><img src="x.jpg" data-original="https://dcimg6.dcinside.co.kr/viewimage.php?id=1&no=2"></div>
<div style='clear:both;'><br><br><b>출처: 가상풍경 갤러리 <a href='https://gall.dcinside.com/board/view/?id=testgallery&no=2001' target='_blank'>[원본 보기]</a></b></div>
</div></div></body></html>"""


def test_parse_post_origin_line_removed():
    p = D.parse_post(VIEW, "dcbest", 1008, "u")
    assert p.text == "본문 한 줄" and "원본" not in p.text
    assert p.origin_gallery == "가상풍경" and p.origin_url.endswith("no=2001")
    assert p.images and p.views == 8713 and p.recommends == 55


def test_parse_post_ordinary_unchanged():
    p = D.parse_post(VIEW.replace("출처: 가상풍경 갤러리 ", "").replace("[원본 보기]", "링크"), "dcbest", 1, "u")
    assert p.origin_gallery == "" and "링크" in p.text
