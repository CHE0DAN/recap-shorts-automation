"""CLI: python -m recap_shorts.collect "키워드" --job 이름 [...]

뉴스는 사용자가 적은 목록(--news-json)만 쓰고, 뉴스 사이트 페이지는 열지 않는다. 기사 대신 우리가 그린 뉴스 카드를 만든다.
네이버 검색 API 는 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from . import dcinside
from .community import community_text
from .http import BlockedError, HttpClient
from .manifest import Manifest
from .news_api import items_from_json
from .news_card import FontNotFound, draw_news_card, fmt_date
from .photos import download_photo, search_commons, search_openverse
from .screenshot import CONFIG_SITES, ad_selectors_for, screenshot_page, selectors_for


def _slug(s: str) -> str:
    return re.sub(r"[^\w-]+", "_", s, flags=re.UNICODE).strip("_")[:40] or "x"


def run(keyword: str, job: str, max_articles: int = 5, photos: int = 5,
        community_urls: list[str] | None = None, work_root: Path | str = "work",
        news_json: str | None = None, dc: str | None = None, dc_minor: bool = False, dc_count: int = 3,
        engine: str = "auto") -> dict:
    job_dir = Path(work_root) / job
    (job_dir / "assets").mkdir(parents=True, exist_ok=True)
    client = HttpClient(job_dir)
    manifest = Manifest(job_dir)
    ok: list[str] = []
    skipped: list[tuple[str, str]] = []

    def skip(what, why):
        skipped.append((what, why))
        print(f"  - 건너뜀: {what} -> {why}")

    # 1. 뉴스(사용자 목록) -> 카드
    print(f"[1] 뉴스: {keyword}")
    items, source = [], ""
    if news_json:
        items, source = items_from_json(news_json), "news_json"
    elif keyword:
        skip("뉴스 카드", "news_json_missing")   # 뉴스 검색은 하지 않는다 — 카드는 --news-json 목록으로만
    print(f"  뉴스 {len(items)}건 (출처: {source or '없음'})")
    (job_dir / "news_items.json").write_text(json.dumps(
        [{**asdict(i), "pub_date": i.pub_date.isoformat()} for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8")
    for n, it in enumerate(items[:max_articles], 1):
        try:
            png = draw_news_card(it.title, it.outlet, it.pub_date, job_dir / "assets" / "news" / f"card_{n:02d}.png")
        except FontNotFound as e:
            skip("뉴스 카드", str(e))
            break
        manifest.add(kind="news_card", source_url=it.originallink, site=urlparse(it.originallink).netloc, file=png,
                     license="기사 제목 인용(출처 표기)", attribution=f"출처: {it.outlet} ({fmt_date(it.pub_date)})",
                     robots_allowed=None, flags={"source": source}, note=it.title[:80])
        ok.append(f"뉴스 카드 {n}: {it.outlet}")

    # 2. 사진(Commons, Openverse)
    if photos > 0 and keyword:
        for name, fn in (("commons", search_commons), ("openverse", search_openverse)):
            print(f"[2] 사진 검색({name}): {keyword}")
            try:
                found = fn(keyword, limit=photos, client=client)
            except BlockedError as e:
                skip(f"사진 검색 {name}", e.blocked.reason + (f" ({e.blocked.detail})" if e.blocked.detail else ""))
                continue
            except Exception as e:
                skip(f"사진 검색 {name}", type(e).__name__)
                continue
            print(f"  허용 라이선스 {len(found)}건")
            if not found:
                skip(f"사진 {name}", "검색 결과 없음(또는 허용 라이선스 없음)")
            for i, ph in enumerate(found, 1):
                try:
                    p = download_photo(ph, job_dir / "assets" / "photos" / f"{name}_{i:02d}.jpg", client)
                except BlockedError as e:
                    skip(f"사진 {ph.title[:30]}", e.blocked.reason)
                    continue
                except Exception as e:
                    skip(f"사진 {ph.title[:30]}", type(e).__name__)
                    continue
                manifest.add(kind="commons_photo", source_url=ph.page_url, site=urlparse(ph.page_url).netloc, file=p,
                             license=ph.license, attribution=ph.attribution_text(), robots_allowed=None,
                             flags={"width": ph.width, "height": ph.height, "source": ph.source}, note=ph.title[:80])
                ok.append(f"사진({name}) {i}: {ph.title[:40]} ({ph.license})")

    # 3. 사용자가 준 커뮤니티 주소
    for i, cu in enumerate(community_urls or [], 1):
        host = urlparse(cu).netloc
        is_dc = host == "gall.dcinside.com"
        try:
            if is_dc:
                shot = dcinside.screenshot_post(cu, job_dir / "assets" / "community" / f"dc_{i:02d}.png", client)
            else:
                shot = screenshot_page(cu, job_dir / "assets" / "community" / f"community_{i:02d}_{_slug(host)}.png",
                                       selectors_for(cu, CONFIG_SITES), client, ad_selectors_for(cu, CONFIG_SITES))
        except BlockedError as e:
            skip(f"커뮤니티 {host}", e.blocked.reason)
            continue
        except Exception as e:
            skip(f"커뮤니티 {host}", type(e).__name__)
            continue
        manifest.add(kind="community_screenshot", source_url=cu, site=host, file=shot.path,
                     license="사용자 제공 링크(권리 확인은 사용자)", attribution=host, flags=shot.flags())
        ok.append(f"커뮤니티 캡처 {i}: {host}" + (" (수동 흐림 필요)" if shot.needs_manual_blur else ""))
        if not is_dc:
            try:
                ct = community_text(cu, job_dir / "assets" / "community" / f"community_{i:02d}.md", client, engine)
                manifest.add(kind="user_source", source_url=cu, site=host, file=ct.path, license="사용자 제공 링크",
                             attribution=host, flags={"engine": ct.engine, "chars": len(ct.markdown)})
                ok.append(f"커뮤니티 본문 {i}: {ct.engine} {len(ct.markdown)}자")
            except BlockedError as e:
                skip(f"커뮤니티 본문 {host}", e.blocked.reason)
            except Exception as e:
                skip(f"커뮤니티 본문 {host}", type(e).__name__)

    # 4. 디시인사이드 --dc GALLERY[:NO]
    if dc:
        gid, _, no = dc.partition(":")
        try:
            if no:
                targets = [(int(no), None)]
            else:
                try:
                    posts = dcinside.list_posts(gid, dc_minor, 1, keyword or None, client)
                except dcinside.NotAllowed:
                    skip("디시 키워드 검색", "robots_not_allowed (목록 1쪽에서 제목으로 거름)")
                    posts = dcinside.list_posts(gid, dc_minor, 1, None, client)
                    posts = [p for p in posts if keyword.lower() in p.title.lower()]
                targets = [(p.no, p) for p in posts[:dc_count]]
                print(f"  디시 {gid}: 목록에서 {len(targets)}개 선택")
            if not targets:
                skip(f"디시 {gid}", "키워드에 맞는 글 없음")
            for no_, _p in targets:
                url = dcinside.view_url(gid, no_, dc_minor)
                try:
                    post = dcinside.get_post(gid, no_, dc_minor, client)
                    shot = dcinside.screenshot_post(url, job_dir / "assets" / "community" / f"dc_{gid}_{no_}.png", client)
                except BlockedError as e:
                    skip(f"디시 {gid}/{no_}", e.blocked.reason)
                    continue
                jp = job_dir / "assets" / "community" / f"dc_{gid}_{no_}.json"
                jp.write_text(json.dumps(asdict(post), ensure_ascii=False, indent=2), encoding="utf-8")  # 닉네임·IP 없음
                manifest.add(kind="community_screenshot", source_url=url, site="gall.dcinside.com", file=shot.path,
                             license="공개 게시글 캡처(권리 확인은 사용자)", attribution="디시인사이드 " + gid,
                             flags=shot.flags(), note=post.title[:80])
                manifest.add(kind="user_source", source_url=url, site="gall.dcinside.com", file=jp,
                             license="공개 게시글 본문(닉네임·IP 저장 안 함)", attribution="디시인사이드 " + gid,
                             flags={"views": post.views, "recommends": post.recommends})
                ok.append(f"디시 {gid}/{no_}: 캡처+본문" + (" (수동 흐림 필요)" if shot.needs_manual_blur else ""))
        except BlockedError as e:
            skip(f"디시 {gid}", e.blocked.reason)
        except ValueError as e:
            skip(f"디시 {dc}", str(e))

    manifest.save()
    print("\n===== 요약 =====")
    print(f"성공 {len(ok)}건 / 건너뜀 {len(skipped)}건 / manifest: {manifest.path}")
    for s in ok:
        print("  OK  ", s)
    for what, why in skipped:
        print("  SKIP", what, "->", why)
    return {"news_source": source, "ok": ok, "skipped": skipped, "manifest": str(manifest.path),
            "job_dir": str(job_dir)}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "topics-fit":      # 채널 대주제 맞춤 점수를 지금 목록에 한 번 찍어 보기 (collect/topicfit.py)
        from .topicfit import cli_main
        sys.exit(cli_main(args[1:]))
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.collect")
    ap.add_argument("keyword", nargs="?", default="")
    ap.add_argument("--job", required=True)
    ap.add_argument("--max-articles", type=int, default=5, help="만들 뉴스 카드 수")
    ap.add_argument("--photos", type=int, default=5)
    ap.add_argument("--community-url", nargs="*", default=[])
    ap.add_argument("--news-json", help="[{title, outlet, date, url}] 목록(키 없이 카드만 그림)")
    ap.add_argument("--dc", help="GALLERY_ID[:NO] 디시인사이드(글 번호 없으면 목록에서 키워드에 맞는 최근 글)")
    ap.add_argument("--dc-minor", action="store_true", help="마이너 갤러리")
    ap.add_argument("--dc-count", type=int, default=3)
    ap.add_argument("--work-root", default="work")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run(a.keyword, a.job, a.max_articles, a.photos, a.community_url, a.work_root,
        a.news_json, a.dc, a.dc_minor, a.dc_count)


if __name__ == "__main__":
    main()
