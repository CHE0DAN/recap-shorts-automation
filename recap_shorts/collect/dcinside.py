"""디시인사이드(PC 페이지) 글 수집·캡처. 정직한 UA, robots 확인(가장 긴 규칙 우선)·3초 간격은 http 계층이 담당.

- 비공식 dc-api는 쓰지 않음(가짜 안드로이드 브라우저 UA, robots가 막는 `?recommend=` 경로, 글쓰기/삭제 기능, 앱 접속 흉내).
- 작성자 닉네임·IP는 읽지도 저장하지도 않는다(Post/PostSummary에 해당 필드가 없음).
- robots가 막은 갤러리·글, 캡차 페이지는 건너뛰고 이유를 남긴다(BlockedError). 우회하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

from lxml import html as LH

from .browser import edge_browser
from .http import USER_AGENT, Blocked, BlockedError, HttpClient
from .screenshot import (CONFIG_SITES, Shot, _OVERLAY_JS, ad_selectors_for, apply_ad_hide, apply_blur, load_config, selectors_for,
                         _guard, _open)

HOST = "https://gall.dcinside.com"
_GID = re.compile(r"^[A-Za-z0-9_]{1,40}$")
MAX_H = 4000
COMMENTS_MAX_H = 2400          # 댓글 캡처 높이 제한(CSS px) — 위쪽 댓글 30개 남짓
# 본문 그림 위에 페이지 스크립트가 얹는 "이미지 순서 ON/OFF" 안내·번호표(그림이 많은 글에 나옴).
# 늦게 생길 수 있어 있는지 세지 않고 스타일을 미리 깔아 둔다.
OVERLAY_HIDE = ["#dcimg_num_tip", ".write_div .sp_btnimg", ".write_div span.num.img", ".write_div .img_numbering"]
PART_SELECTORS = {"head": ".view_content_wrap .gallview_head", "recommend": ".view_content_wrap .btn_recommend_box"}


class NotAllowed(Exception):
    """robots.txt가 허용하지 않는 기능(예: 키워드 검색)."""


@dataclass
class PostSummary:
    no: int
    title: str
    date: str
    views: int
    recommends: int
    comments: int
    url: str


@dataclass
class Post:
    gallery_id: str
    no: int
    url: str
    title: str
    text: str
    written_at: str
    views: int
    recommends: int
    images: list[str] = field(default_factory=list)
    origin_gallery: str = ""   # 실시간 베스트 글 끝의 "출처: ○○ 갤러리 [원본 보기]" (원본 갤러리 이름·주소). 일반 글은 빈 값
    origin_url: str = ""


_ORIGIN_NAME = re.compile(r"출처\s*:\s*(.+?)\s*갤러리")


def _base(gallery_id: str, minor: bool) -> str:
    if not _GID.match(gallery_id):
        raise ValueError(f"갤러리 id 형식이 이상합니다: {gallery_id!r}")
    return f"{HOST}/mgallery/board" if minor else f"{HOST}/board"


def list_url(gallery_id: str, minor: bool = False, page: int = 1, keyword: str | None = None,
             recommend: bool = False) -> str:
    """recommend=True: 개념글(추천 글) 목록 — PC 목록의 `exception_mode=recommend`."""
    q = {"id": gallery_id, "page": page}
    if recommend:
        q["exception_mode"] = "recommend"
    if keyword:
        q.update({"s_type": "search_subject_memo", "s_keyword": keyword})
    return f"{_base(gallery_id, minor)}/lists/?" + urlencode(q)


def view_url(gallery_id: str, no: int, minor: bool = False) -> str:
    return f"{_base(gallery_id, minor)}/view/?" + urlencode({"id": gallery_id, "no": no})


def _num(s: str) -> int:
    m = re.search(r"\d[\d,]*", s or "")
    return int(m.group(0).replace(",", "")) if m else 0


def parse_list(html: str, gallery_id: str, minor: bool = False) -> list[PostSummary]:
    doc = LH.fromstring(html)
    out = []
    for r in doc.xpath('//tr[contains(@class,"ub-content")][@data-no]'):
        if r.get("data-type") == "icon_notice" or not (r.get("data-no") or "").isdigit():
            continue  # 공지·광고 줄 제외(광고 줄에는 data-no가 없음)
        title = " ".join(t.strip() for t in r.xpath('.//td[contains(@class,"gall_tit")]//a[1]/text()') if t.strip())
        if not title:
            title = r.xpath('string(.//td[contains(@class,"gall_tit")]//a[1])').strip()
        no = int(r.get("data-no"))
        out.append(PostSummary(
            no=no, title=title, date=r.xpath('string(.//td[@class="gall_date"])').strip(),
            views=_num(r.xpath('string(.//td[@class="gall_count"])')),
            recommends=_num(r.xpath('string(.//td[@class="gall_recommend"])')),
            comments=_num(r.xpath('string(.//a[contains(@class,"reply_numbox")])')),
            url=view_url(gallery_id, no, minor)))
    return out


def parse_post(html: str, gallery_id: str, no: int, url: str) -> Post:
    doc = LH.fromstring(html)
    title = doc.xpath('string(//span[@class="title_subject"])').strip()
    head = doc.xpath('string(//span[@class="title_headtext"])').strip()
    if head:
        title = f"{head} {title}"
    date = doc.xpath('string(//div[contains(@class,"gallview_head")]//span[@class="gall_date"]/@title)').strip()
    views = _num(doc.xpath('string(//div[contains(@class,"gallview_head")]//span[@class="gall_count"])'))
    recs = _num(doc.xpath('string(//div[contains(@class,"gallview_head")]//span[@class="gall_reply_num"])'))
    body = doc.xpath('//div[@class="write_div"]')
    text, images = "", []
    origin_gallery = origin_url = ""
    if body:
        b = body[0]
        for bad in b.xpath('.//script|.//style|.//iframe|.//ins'):
            bad.getparent().remove(bad)
        # 실베 글은 원본 글의 복사본이고 끝에 "출처: ○○ 갤러리 [원본 보기]" 줄이 붙는다 — 본문(대본 재료)에서 빼고 따로 기록
        for a in b.xpath('.//a[contains(normalize-space(.), "원본 보기")]'):
            box = a.getparent()
            while box is not None and box is not b and box.tag != "div":
                box = box.getparent()
            if box is None or box is b or len(box.text_content().strip()) > 80:
                continue   # 출처 줄이 아닌 큰 덩어리면 건드리지 않음
            m = _ORIGIN_NAME.search(box.text_content())
            origin_gallery, origin_url = (m.group(1).strip() if m else ""), (a.get("href") or "")
            box.getparent().remove(box)
        text = "\n".join(t.strip() for t in b.itertext() if t.strip())
        for img in b.xpath('.//img'):
            src = img.get("data-original") or img.get("src") or ""
            if src and "nstatic.dcinside.com" not in src and "dccon" not in (img.get("class") or ""):
                images.append(src if not src.startswith("//") else "https:" + src)
    return Post(gallery_id=gallery_id, no=no, url=url, title=title, text=text, written_at=date,
                views=views, recommends=recs, images=images, origin_gallery=origin_gallery, origin_url=origin_url)


def _fetch(url: str, client: HttpClient):
    r = client.fetch(url)
    if isinstance(r, Blocked):
        raise BlockedError(r)
    return r


def list_posts(gallery_id: str, minor: bool = False, page: int = 1, keyword: str | None = None,
               client: HttpClient | None = None, recommend: bool = False) -> list[PostSummary]:
    client = client or HttpClient()
    url = list_url(gallery_id, minor, page, keyword, recommend)
    if (keyword or recommend) and not client.robots_allowed(url):
        raise NotAllowed("robots.txt가 이 검색 주소를 허용하지 않습니다")
    return parse_list(_fetch(url, client).text, gallery_id, minor)


def get_post(gallery_id: str, no: int, minor: bool = False, client: HttpClient | None = None) -> Post:
    client = client or HttpClient()
    url = view_url(gallery_id, no, minor)
    return parse_post(_fetch(url, client).text, gallery_id, no, url)


_MOBILE_BEST = re.compile(r"^/board/dcbest/(\d+)/?$")


def parse_dc_url(url: str) -> tuple[str, int, bool]:
    """PC 글 주소(gall.dcinside.com/board/view/?id=&no=, /mgallery/…) 또는 실시간 베스트 모바일 주소(m.dcinside.com/board/dcbest/<번호>)."""
    u = urlparse(url.strip())
    if u.netloc == "m.dcinside.com":
        m = _MOBILE_BEST.match(u.path)
        if m:
            return "dcbest", int(m.group(1)), False
        raise ValueError("m.dcinside.com 은 실시간 베스트(/board/dcbest/번호) 주소만 받습니다 — PC 글 주소를 붙여 넣어 주세요")
    q = parse_qs(u.query)
    if u.netloc != "gall.dcinside.com" or "id" not in q or "no" not in q:
        raise ValueError("gall.dcinside.com 글 주소가 아닙니다")
    return q["id"][0], int(q["no"][0]), u.path.startswith("/mgallery/")


def screenshot_post(url: str, out_png: Path | str, client: HttpClient | None = None,
                    config_path: Path | str | None = None) -> Shot:
    """글 영역(.view_content_wrap + 그 아래 .view_comment 댓글)을 PC 폭에서 찍는다. 닉네임·IP·고정닉 아이콘·댓글 작성자는 캡처 전에 흐림.

    선택자는 config/collect_sites.json 의 gall.dcinside.com 항목(실제 페이지에서 확인한 값)을 쓴다.
    """
    from PIL import Image
    config_path = config_path or CONFIG_SITES
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    parse_dc_url(url)
    _guard(url, client)
    blur = selectors_for(url, config_path)
    ads = ad_selectors_for(url, config_path)
    site = {}
    for k, v in load_config(config_path).get("sites", {}).items():
        if urlparse(url).netloc.endswith(k):
            site = v
    clip_sels = site.get("clip_selectors", ["body"])
    with edge_browser() as br:
        ctx = br.new_context(user_agent=USER_AGENT + " browser", locale="ko-KR",
                             viewport={"width": 1280, "height": 1200}, device_scale_factor=2)
        try:
            page = ctx.new_page()
            _open(page, url)
            try:  # 댓글은 페이지 스스로 불러옴
                page.wait_for_selector(".view_comment .comment_wrap", timeout=5000)
                page.wait_for_timeout(1200)
            except Exception:
                pass
            shot = Shot(path=out_png, url=url, final_url=page.url)
            shot.overlay_suspected = bool(page.evaluate(_OVERLAY_JS))
            shot.ads_hidden = apply_ad_hide(page, ads)
            page.add_style_tag(content=" ".join(f"{sel} {{ display: none !important; }}" for sel in OVERLAY_HIDE))
            shot.blurred = apply_blur(page, blur)
            shot.needs_manual_blur = (not blur) or all(n == 0 for n in shot.blurred.values())
            box = page.evaluate(
                "ss => { let x0=1e9,y0=1e9,x1=0,y1=0,n=0; for (const s of ss) { const e = document.querySelector(s); if (!e) continue; "
                "const r = e.getBoundingClientRect(); n++; x0=Math.min(x0,r.left+scrollX); y0=Math.min(y0,r.top+scrollY); "
                "x1=Math.max(x1,r.right+scrollX); y1=Math.max(y1,r.bottom+scrollY); } return n ? {x:x0,y:y0,w:x1-x0,h:y1-y0} : null; }",
                clip_sels)
            if not box:
                shot.needs_manual_blur = True
                page.screenshot(path=str(out_png))
            else:
                page.screenshot(path=str(out_png), full_page=True,
                                clip={"x": box["x"], "y": box["y"], "width": box["w"], "height": min(box["h"], MAX_H)})
                # 카드로 쓸 부분(글 머리=제목·조회·추천, 추천 상자)의 위치: 캡처 픽셀 좌표(×2)
                rects = page.evaluate(
                    "ps => { const o = {}; for (const [k, s] of Object.entries(ps)) { const e = document.querySelector(s); "
                    "if (!e) continue; const r = e.getBoundingClientRect(); if (r.width < 4 || r.height < 4) continue; "
                    "o[k] = [r.left + scrollX, r.top + scrollY, r.right + scrollX, r.bottom + scrollY]; } return o; }",
                    PART_SELECTORS)
                for k, (x0, y0, x1, y1) in (rects or {}).items():
                    b = [round((x0 - box["x"]) * 2), round((y0 - box["y"]) * 2), round((x1 - box["x"]) * 2), round((y1 - box["y"]) * 2)]
                    if b[1] >= 0 and b[3] <= 2 * min(box["h"], MAX_H):
                        shot.parts[k] = b
                # 댓글은 글 아래라 위 캡처 높이 제한에 잘리기 쉬움 → 따로 한 장(닉네임은 이미 흐림)
                cm = page.evaluate("s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); "
                                   "return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}; }", "#focus_cmt .comment_box")
                if cm and cm["h"] > 60:
                    cpath = out_png.with_name("comments.png")
                    page.screenshot(path=str(cpath), full_page=True,
                                    clip={"x": cm["x"], "y": cm["y"], "width": cm["w"], "height": min(cm["h"], COMMENTS_MAX_H)})
                    shot.parts["comments_file"] = cpath.name
            with Image.open(out_png) as im:
                shot.width, shot.height = im.size
            return shot
        finally:
            ctx.close()
