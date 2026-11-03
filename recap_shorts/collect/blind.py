"""블라인드(teamblind.com/kr) 인기글·글 수집 — 디시인사이드와 같은 자리에 쓰는 두 번째 글 출처.

- 인기글: https://www.teamblind.com/kr/topics/토픽-베스트 (robots.txt: `User-agent: *` 는 /kr/search/·/kr/user/history 만 막음).
  한 쪽뿐이고 더보기·쪽 넘김이 없다. 줄은 `div.article-list-pre` 이고, 그중 `/kr/post/` 링크가 있는 줄만 글이다
  (광고 div 줄과 쿠팡 상품 줄은 링크가 link.coupang.com 이라 걸러진다).
- 글 주소: /kr/post/<제목-slug>-<8자 별칭>. 별칭만 있는 /kr/post/<별칭> 도 열린다. 별칭을 `no`(문자열)로 쓴다.
- 글 화면은 Nuxt 2 SSR 이라 본문이 HTML 에 그대로 있다. 작성자 닉네임·회사명은 읽지도 저장하지도 않는다
  (h1 앞의 회사 링크는 제목에서 떼고, 목록의 작성자 줄은 아예 건드리지 않는다). 화면 캡처는 config/collect_sites.json 의
  흐림 선택자로 가린다. 댓글은 로그인 없이 처음 보이는 만큼만 보인다(서버가 일부만 그려 주고 '더보기'는 눌러야 나옴).
- GitHub 의 teamblind 스크래퍼들은 라이선스가 없어 코드를 가져오지 않았다. 구조만 참고하고 이 파일은 직접 작성했다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from lxml import html as LH

from .browser import edge_browser
from .dcinside import _fetch
from .http import USER_AGENT, HttpClient
from .screenshot import (CONFIG_SITES, Shot, _guard, _OVERLAY_JS, ad_selectors_for, apply_ad_hide, apply_blur, load_config,
                         selectors_for)

MAX_H = 4000
COMMENTS_MAX_H = 2400          # 댓글 캡처 높이 제한(CSS px) — 디시와 같은 값

KST = timezone(timedelta(hours=9))
HOST = "https://www.teamblind.com"
BEST_URL = HOST + "/kr/topics/" + quote("토픽-베스트")
SORTS = ("views", "comments", "recent")
_POST_PATH = re.compile(r"^/kr/post/([^/?#]+)/?$")
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,40}$")


class BlindNotAllowed(Exception):
    """robots.txt 가 블라인드 주소를 허용하지 않음."""


@dataclass
class BestItem:
    """dcbest.BestItem 과 같은 모양(no 만 문자열). 화면·API 에 그대로 쓴다."""
    no: str
    title: str
    tag: str              # 토픽 이름(예: 블라블라) — 디시의 갤러리 태그 자리
    views: int
    recommends: int
    comments: int
    posted_at: str        # ISO 8601, +09:00
    age_hours: float
    url: str


@dataclass
class Post:
    """dcinside.Post 와 같은 항목 + topic(블라인드 토픽 이름). gallery_id 는 늘 "blind"."""
    gallery_id: str
    no: str
    url: str
    title: str
    text: str
    written_at: str
    views: int
    recommends: int
    images: list[str] = field(default_factory=list)
    origin_gallery: str = ""
    origin_url: str = ""
    topic: str = ""


# ---------------------------------------------------------------- 주소·목록
def post_url(alias: str) -> str:
    return f"{HOST}/kr/post/{quote(str(alias).strip())}"


def list_url(page: int = 1) -> str:
    """블라인드 인기글은 한 쪽뿐이라 page 는 받기만 하고 무시한다."""
    return BEST_URL


def parse_blind_url(url: str) -> tuple[str, str]:
    """블라인드 글 주소 → (별칭, 표준 주소). 제목-slug 주소와 별칭만 있는 주소 둘 다 받는다."""
    u = urlparse((url or "").strip() if "://" in (url or "") else "https://" + (url or "").strip())
    host = (u.netloc or "").lower()
    if host not in ("www.teamblind.com", "teamblind.com"):
        raise ValueError("www.teamblind.com 글 주소가 아닙니다")
    m = _POST_PATH.match(u.path)
    if not m:
        raise ValueError("블라인드 글 주소(/kr/post/…)가 아닙니다")
    seg = m.group(1)
    alias = seg.rsplit("-", 1)[-1]
    if not _ALIAS.match(alias):
        raise ValueError("블라인드 글 주소의 별칭을 읽지 못했습니다")
    return alias, post_url(alias)


def _num(s: str) -> int:
    """"1,136" → 1136, "13K" → 13000, "1.2M" → 1200000. 숫자가 없으면 0."""
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([KkMm])?", s or "")
    if not m:
        return 0
    v = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").upper()
    if unit == "K":
        v *= 1_000
    elif unit == "M":
        v *= 1_000_000
    return int(round(v))


def _age_hours(label: str, now: datetime) -> float | None:
    """'작성시간5시간'·'작성시간어제'·'3일'·'방금' → 지난 시간. 못 읽으면 None."""
    s = re.sub(r"작성시간|작성일", "", label or "").strip()
    if not s:
        return None
    if "방금" in s or "방금 전" in s:
        return 0.0
    m = re.search(r"(\d+)\s*분", s)
    if m:
        return int(m.group(1)) / 60
    m = re.search(r"(\d+)\s*시간", s)
    if m:
        return float(m.group(1))
    if "어제" in s:
        return 24.0
    m = re.search(r"(\d+)\s*일", s)
    if m:
        return 24.0 * int(m.group(1))
    return None


def _row_title(a) -> str:
    return re.sub(r"\s+", " ", a.text_content()).strip()


def parse_list(html: str, now: datetime | None = None) -> list[BestItem]:
    now = now or datetime.now(KST)
    doc = LH.fromstring(html)
    out: list[BestItem] = []
    for r in doc.xpath('//div[contains(@class,"article-list")]/div[contains(@class,"article-list-pre")]'):
        cls = r.get("class") or ""
        if "article-list-ad" in cls:
            continue                       # 광고 div 줄
        a = r.xpath('.//div[contains(@class,"tit")]/h3/a[starts-with(@href,"/kr/post/")]')
        if not a:
            continue                       # 쿠팡 상품 줄(link.coupang.com) 등 글 링크가 없는 줄
        href = a[0].get("href") or ""
        try:
            alias, url = parse_blind_url(HOST + href)
        except ValueError:
            continue
        past = " ".join(r.xpath('string(.//div[contains(@class,"wrap-info")]//*[contains(@class,"past")])').split())
        age = _age_hours(past, now)
        if age is None:
            continue                       # 작성 시간을 모르면 최근 창 거르기를 못 한다(광고 줄도 여기서 빠진다)
        tag = " ".join(r.xpath('string(.//span[contains(@class,"category")]//a[contains(@class,"topic-name")])').split())
        out.append(BestItem(
            no=alias, title=_row_title(a[0]), tag=tag,
            views=_num(r.xpath('string(.//div[contains(@class,"wrap-info")]//*[contains(@class,"pv")])')),
            recommends=_num(r.xpath('string(.//div[contains(@class,"wrap-info")]//*[contains(@class,"like")])')),
            comments=_num(r.xpath('string(.//div[contains(@class,"wrap-info")]//*[contains(@class,"cmt")])')),
            posted_at=(now - timedelta(hours=age)).isoformat(timespec="seconds"),
            age_hours=round(age, 1), url=url))
    return out


def sort_items(items: list[BestItem], sort: str = "views") -> list[BestItem]:
    if sort == "comments":
        return sorted(items, key=lambda i: (-i.comments, -i.views))
    if sort == "recent":
        return sorted(items, key=lambda i: i.age_hours)
    return sorted(items, key=lambda i: (-i.views, -i.comments))


def fetch_best(pages: int = 1, hours: float = 48, sort: str = "views", client: HttpClient | None = None,
               now: datetime | None = None, max_pages: int = 1) -> list[BestItem]:
    """인기글 한 쪽(더보기·쪽 넘김 없음)을 읽어 최근 hours 시간 안의 글만 sort 순으로 돌려준다."""
    if sort not in SORTS:
        raise ValueError(f"sort 는 {', '.join(SORTS)} 중 하나")
    client = client or HttpClient()
    now = now or datetime.now(KST)
    if not client.robots_allowed(BEST_URL):
        raise BlindNotAllowed("robots.txt 가 블라인드 인기글 목록을 허용하지 않습니다")
    items = parse_list(_fetch(BEST_URL, client).text, now)   # _fetch 가 robots·간격을 지키고 Blocked 를 예외로 바꾼다
    return sort_items([i for i in items if i.age_hours <= float(hours)], sort)


# ---------------------------------------------------------------- 글
def _ld(doc) -> dict:
    """per-post ld+json(배열)에서 DiscussionForumPosting 하나. 작성자(author)는 읽지 않는다."""
    for s in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(s.text or "")
        except ValueError:
            continue
        for it in data if isinstance(data, list) else [data]:
            if isinstance(it, dict) and str(it.get("@type")) == "DiscussionForumPosting":
                return it
    return {}


def _ld_when(obj: dict) -> str:
    raw = str(obj.get("datePublished") or "")
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _text_with_breaks(el) -> str:
    """<br> 을 줄바꿈으로 살려 글자를 모은다(문단 태그 경계도 줄바꿈)."""
    parts: list[str] = []

    def walk(node) -> None:
        if node.text:
            parts.append(node.text)
        for ch in node:
            if not isinstance(ch.tag, str):
                if ch.tail:
                    parts.append(ch.tail)
                continue
            if ch.tag == "br":
                parts.append("\n")
            else:
                walk(ch)
                if ch.tag in ("p", "div", "li", "blockquote"):
                    parts.append("\n")
            if ch.tail:
                parts.append(ch.tail)

    walk(el)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in "".join(parts).splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _topic_of(head) -> str:
    links = [a for a in head.xpath('.//h2//a[starts-with(@href,"/kr/topics/")]') if (a.get("href") or "") != "/kr/topics/%EC%A0%84%EC%B2%B4"]
    return " ".join(links[-1].text_content().split()) if links else ""


def _title_of(head) -> str:
    h1 = head.xpath('.//h1[1]')
    if not h1:
        return ""
    el = h1[0]
    for a in list(el.xpath('.//a[starts-with(@href,"/kr/company/")]')):
        a.drop_tree()                       # 제목 앞 회사 이름 — 읽지도 저장하지도 않는다
    return re.sub(r"\s+", " ", el.text_content()).strip()


def parse_post(html: str, url: str, alias: str, now: datetime | None = None) -> Post:
    now = now or datetime.now(KST)
    doc = LH.fromstring(html)
    heads = doc.xpath('//div[contains(@class,"article-view-head")]')
    if not heads:
        raise ValueError("블라인드 글 화면에서 글 머리를 찾지 못했습니다(로그인·차단 화면일 수 있음)")
    head = heads[0]
    ld = _ld(doc)
    title = _title_of(head) or str(ld.get("headline") or "").strip()
    topic = _topic_of(head)
    # 본문: p#contentArea(없으면 article-view-contents) — 광고 tag-actions 는 넣지 않는다
    boxes = doc.xpath('//p[@id="contentArea"]') or doc.xpath('//div[contains(@class,"article-view-contents")]')
    text = _text_with_breaks(boxes[0]) if boxes else str(ld.get("text") or "")
    images: list[str] = []
    for img in doc.xpath('//div[contains(@class,"article-view-contents")]//p[contains(@class,"attach-img")]//img[@src]'):
        src = img.get("src") or ""
        if src.startswith("//"):
            src = "https:" + src
        if src and src not in images:
            images.append(src)
    when = _ld_when(ld)
    if not when:                            # ld+json 이 없을 때만 화면의 상대 시각으로 어림한다
        label = " ".join(head.xpath('string(.//div[contains(@class,"wrap-info")]//*[contains(@class,"date")])').split())
        age = _age_hours(label, now)
        if age is not None:
            when = (now - timedelta(hours=age)).strftime("%Y-%m-%d %H:%M")
    views = _num(head.xpath('string(.//div[contains(@class,"wrap-info")]//*[contains(@class,"pv")])'))
    rec = _num(doc.xpath('string(//div[contains(@class,"article_info")]//*[contains(@class,"like")])'))
    stat = (ld.get("interactionStatistic") or {}) if isinstance(ld.get("interactionStatistic"), dict) else {}
    if not rec:
        rec = _num(str(stat.get("userInteractionCount") or ""))
    return Post(gallery_id="blind", no=alias, url=url, title=title, text=text, written_at=when,
                views=views, recommends=rec, images=images, topic=topic)


def get_post(gallery_id: str, no: str, minor: bool = False, client: HttpClient | None = None,
             now: datetime | None = None) -> Post:
    client = client or HttpClient()
    url = post_url(no)
    return parse_post(_fetch(url, client).text, url, str(no), now)


# ---------------------------------------------------------------- 화면 캡처
_PART_SELECTORS = {"head": ".article-view-head", "body": ".article-view-contents"}   # body: 글만 있는 글의 본문 캡처(pipeline.post_body_attachment)
_CLIP = [".article-view-head", ".article-view-contents", ".article-comments"]


def _comments_seen(page) -> dict:
    """로그인 없이 그려진 댓글 수와 전체 댓글 수(머리 '댓글 78') — '더보기'는 눌러야 나온다."""
    try:
        return page.evaluate(
            """() => {
              const total = Number((document.querySelector('.article-comments .write_area h3')?.textContent || '').replace(/[^0-9]/g, '')) || 0;
              const n = document.querySelectorAll('.article-comments .wrap-comment, .article-comments .wrap-reply').length;
              const more = [...document.querySelectorAll('.article-comments button')].some(b => /더보기/.test(b.textContent || ''));
              return {total, shown: n, more};
            }""")
    except Exception:  # noqa: BLE001 — 못 세면 캡처는 그대로 한다
        return {}


def screenshot_post(url: str, out_png: Path | str, client: HttpClient | None = None,
                    config_path: Path | str | None = None) -> Shot:
    """글 머리·본문·댓글 영역을 PC 폭에서 찍는다. 닉네임·회사명은 캡처 전에 흐림(config/collect_sites.json).

    parts 에 {"head": [x0,y0,x1,y1], "body": [...], "comments_file": "comments.png", "comments_total", "comments_shown"} 를 담는다.
    """
    from PIL import Image
    config_path = config_path or CONFIG_SITES
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    parse_blind_url(url)
    _guard(url, client)
    blur = selectors_for(url, config_path)
    ads = ad_selectors_for(url, config_path)
    site = {}
    for k, v in load_config(config_path).get("sites", {}).items():
        if urlparse(url).netloc.endswith(k):
            site = v
    clip_sels = site.get("clip_selectors", _CLIP)
    with edge_browser() as br:
        ctx = br.new_context(user_agent=USER_AGENT + " browser", locale="ko-KR",
                             viewport={"width": 1280, "height": 1200}, device_scale_factor=2)
        try:
            page = ctx.new_page()
            _guard(url, client)
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                page.wait_for_selector(".article-view-head", timeout=8000)
                page.wait_for_timeout(1200)
            except Exception:  # noqa: BLE001
                pass
            shot = Shot(path=out_png, url=url, final_url=page.url)
            shot.overlay_suspected = bool(page.evaluate(_OVERLAY_JS))
            shot.ads_hidden = apply_ad_hide(page, ads)
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
                rects = page.evaluate(
                    "ps => { const o = {}; for (const [k, s] of Object.entries(ps)) { const e = document.querySelector(s); "
                    "if (!e) continue; const r = e.getBoundingClientRect(); if (r.width < 4 || r.height < 4) continue; "
                    "o[k] = [r.left + scrollX, r.top + scrollY, r.right + scrollX, r.bottom + scrollY]; } return o; }",
                    _PART_SELECTORS)
                for k, (x0, y0, x1, y1) in (rects or {}).items():
                    b = [round((x0 - box["x"]) * 2), round((y0 - box["y"]) * 2), round((x1 - box["x"]) * 2), round((y1 - box["y"]) * 2)]
                    if b[1] >= 0 and b[3] <= 2 * min(box["h"], MAX_H):
                        shot.parts[k] = b
                cm = page.evaluate("s => { const e = document.querySelector(s); if (!e) return null; "
                                   "const r = e.getBoundingClientRect(); return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}; }",
                                   ".article-comments")
                if cm and cm["h"] > 60:
                    cpath = out_png.with_name("comments.png")
                    page.screenshot(path=str(cpath), full_page=True,
                                    clip={"x": cm["x"], "y": cm["y"], "width": cm["w"], "height": min(cm["h"], COMMENTS_MAX_H)})
                    shot.parts["comments_file"] = cpath.name
                seen = _comments_seen(page)
                if seen:
                    shot.parts.update({f"comments_{k}": v for k, v in seen.items()})
                    if seen.get("more") and (seen.get("total") or 0) > (seen.get("shown") or 0):
                        shot.parts["comments_truncated"] = True
            with Image.open(out_png) as im:
                shot.width, shot.height = im.size
            return shot
        finally:
            ctx.close()


def to_dict(it: BestItem) -> dict:
    return asdict(it)
