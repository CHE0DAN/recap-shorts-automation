"""Playwright(Edge, headless) 캡처: 사용자가 준 커뮤니티 글 주소 전용. 뉴스 페이지는 열지 않는다.

쿠키 창을 누르지 않고, 덮여 있으면 표시만 한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .browser import edge_browser, new_context
from .http import Blocked, BlockedError, HttpClient

CONFIG_SITES = Path(__file__).resolve().parents[2] / "config" / "collect_sites.json"
VIEW_W, VIEW_H, SCALE = 430, 932, 3
MAX_PAGE_H = 4000  # 캡처 최대 높이(CSS px)

_OVERLAY_JS = r"""
() => {
  const kw = /cookie|consent|쿠키|개인정보|동의|gdpr|privacy/i;
  let found = false;
  for (const e of document.querySelectorAll('body *')) {
    const s = getComputedStyle(e);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    const r = e.getBoundingClientRect();
    if (r.width < 200 || r.height < 60) continue;
    const area = (Math.min(r.right, innerWidth) - Math.max(r.left, 0)) * (Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
    const big = area > 0.2 * innerWidth * innerHeight;
    const label = (e.id + ' ' + e.className + ' ' + (e.innerText||'').slice(0, 200));
    if (big && kw.test(label)) { found = true; break; }
    if (area > 0.6 * innerWidth * innerHeight && parseInt(s.zIndex || '0') > 100) { found = true; break; }
  }
  return found;
}
"""

# 광고로 보이는 요소만, 보수적으로(본문이 사라질 위험이 있어 목록을 짧게). config의 ad_hide로 끄거나 바꿈.
DEFAULT_AD_SELECTORS = ["iframe", "ins.adsbygoogle", '[id^="google_ads"]', '[class*="banner"]']


@dataclass
class Shot:
    path: Path
    url: str
    final_url: str = ""
    found_headline: bool = False
    overlay_suspected: bool = False
    needs_manual_blur: bool = False
    headline_text: str = ""
    blurred: dict = field(default_factory=dict)
    ads_hidden: dict = field(default_factory=dict)
    width: int = 0
    height: int = 0
    parts: dict = field(default_factory=dict)   # 디시 글: {"head": [x0,y0,x1,y1], "recommend": [...], "comments_file": "comments.png"}

    def flags(self) -> dict:
        d = {"overlay_suspected": self.overlay_suspected, "needs_manual_blur": self.needs_manual_blur}
        if self.blurred:
            d["blurred"] = self.blurred
        if self.ads_hidden:
            d["ads_hidden"] = sum(self.ads_hidden.values())
            d["ads_hidden_by_selector"] = self.ads_hidden
        return d


def _guard(url: str, client: HttpClient | None):
    if client is None:
        return
    if not client.robots_allowed(url):
        raise BlockedError(Blocked(url, "robots"))
    client.wait_turn(url)


def _open(page, url: str):
    resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    status = resp.status if resp else 0
    if status in (401, 403, 429):
        reason = {401: "auth_401", 403: "forbidden_403", 429: "rate_limited_429"}[status]
        raise BlockedError(Blocked(url, reason))
    return status


def load_config(path: Path | str) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _site_cfg(url: str, config_path: Path | str) -> dict:
    host = urlparse(url).netloc.lower()
    for key, cfg in load_config(config_path).get("sites", {}).items():
        if host == key or host.endswith("." + key):
            return cfg
    return {}


def selectors_for(url: str, config_path: Path | str) -> list[str]:
    return list(_site_cfg(url, config_path).get("blur_selectors", []))


def ad_selectors_for(url: str, config_path: Path | str) -> list[str]:
    """전역 ad_hide 설정(enabled/selectors)과 사이트별 ad_hide(false로 끄기)를 합친다."""
    cfg = load_config(config_path)
    ad = cfg.get("ad_hide", {})
    if not ad.get("enabled", True):
        return []
    if _site_cfg(url, config_path).get("ad_hide") is False:
        return []
    extra = list(_site_cfg(url, config_path).get("ad_selectors", []))  # 사이트별 추가(확인한 광고 칸)
    return list(ad.get("selectors", DEFAULT_AD_SELECTORS)) + extra


def apply_ad_hide(page, selectors: list[str]) -> dict:
    hidden = {}
    for sel in selectors:
        try:
            n = page.evaluate("s => document.querySelectorAll(s).length", sel)
            if n:
                page.add_style_tag(content=f"{sel} {{ display: none !important; }}")
        except Exception:
            n = 0
        hidden[sel] = n
    return hidden


def apply_blur(page, selectors: list[str]) -> dict:
    out = {}
    for sel in selectors:
        try:
            n = page.evaluate("s => document.querySelectorAll(s).length", sel)
            page.add_style_tag(content=f"{sel} {{ filter: blur(8px) !important; }}")
        except Exception:
            n = 0
        out[sel] = n
    return out


def shoot_page(page, url: str, out_png: Path, blur_selectors: list[str], ad_selectors: list[str]) -> Shot:
    """열려 있는 페이지에 광고 숨김·흐림을 적용하고 찍는다. needs_manual_blur: 선택자가 없거나 하나도 못 찾음."""
    from PIL import Image
    shot = Shot(path=out_png, url=url, final_url=page.url)
    shot.overlay_suspected = bool(page.evaluate(_OVERLAY_JS))
    shot.ads_hidden = apply_ad_hide(page, ad_selectors)
    shot.blurred = apply_blur(page, blur_selectors)
    shot.needs_manual_blur = (not blur_selectors) or all(n == 0 for n in shot.blurred.values())
    height = page.evaluate("document.documentElement.scrollHeight")
    page.screenshot(path=str(out_png), full_page=True,
                    clip={"x": 0, "y": 0, "width": VIEW_W, "height": min(max(height, VIEW_H), MAX_PAGE_H)})
    with Image.open(out_png) as im:
        shot.width, shot.height = im.size
    return shot


def screenshot_page(url: str, out_png: Path | str, blur_selectors: list[str] | None = None,
                    client: HttpClient | None = None, ad_selectors: list[str] | None = None) -> Shot:
    """사용자가 준 커뮤니티 글 캡처(모바일 폭 430, 배율 3). 선택자 영역을 캡처 전에 흐리게."""
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    blur_selectors = [s for s in (blur_selectors or []) if s.strip()]
    _guard(url, client)
    with edge_browser() as br:
        ctx = new_context(br, mobile=True)
        try:
            page = ctx.new_page()
            _open(page, url)
            return shoot_page(page, url, out_png, blur_selectors, ad_selectors or [])
        finally:
            ctx.close()
