"""Playwright + 설치된 Edge 실행 도우미. 브라우저를 새로 내려받지 않는다."""
from __future__ import annotations

from contextlib import contextmanager

from .http import USER_AGENT

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


@contextmanager
def edge_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(executable_path=EDGE_PATH, headless=True)
        try:
            yield browser
        finally:
            browser.close()


def new_context(browser, *, mobile: bool = True):
    kw = dict(user_agent=USER_AGENT + " browser", locale="ko-KR")
    if mobile:
        kw.update(viewport={"width": 430, "height": 932}, device_scale_factor=3,
                  is_mobile=True, has_touch=True)
    return browser.new_context(**kw)
