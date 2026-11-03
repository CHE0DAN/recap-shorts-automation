"""위키미디어 공용(Commons) 사진 검색·다운로드. 허용 라이선스만 남긴다."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from .http import Blocked, BlockedError, HttpClient

API = "https://commons.wikimedia.org/w/api.php"
THUMB_W = 1080
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}

# CC0 / Public domain / CC BY 2.0~4.0 / CC BY-SA 2.0~4.0 (국가 접미사 허용, NC·ND 제외)
_LICENSE_RE = re.compile(
    r"^(?:cc0(?:[ -]1\.0)?|public domain.*|pd(?:[ -].*)?|"
    r"cc[ -]by(?:-sa)?[ -](?:2\.0|2\.1|2\.5|3\.0|4\.0)(?:[ -][a-z]{2,3})?)$",
    re.I,
)


@dataclass
class Photo:
    title: str
    page_url: str
    file_url: str
    thumb_url: str
    license: str
    license_url: str
    artist: str
    width: int
    height: int
    mime: str
    source: str = "Wikimedia Commons"

    def attribution_text(self) -> str:
        artist = self.artist or "작성자 불명"
        return f"사진: {artist} / {self.license} / {self.source}"


def is_allowed_license(name: str) -> bool:
    name = (name or "").strip()
    if re.search(r"\b(nc|nd)\b", name, re.I):
        return False
    return bool(_LICENSE_RE.match(name))


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def parse_commons(data: dict) -> list[Photo]:
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        infos = p.get("imageinfo") or []
        if not infos:
            continue
        ii = infos[0]
        if ii.get("mime") not in _ALLOWED_MIME:
            continue
        meta = ii.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not is_allowed_license(lic):
            continue
        out.append(Photo(
            title=p.get("title", ""),
            page_url=ii.get("descriptionurl", ""),
            file_url=ii.get("url", ""),
            thumb_url=ii.get("thumburl") or ii.get("url", ""),
            license=lic,
            license_url=(meta.get("LicenseUrl") or {}).get("value", ""),
            artist=strip_html((meta.get("Artist") or {}).get("value", "")),
            width=ii.get("width", 0), height=ii.get("height", 0), mime=ii.get("mime", ""),
        ))
    return out


def search_commons(query: str, limit: int = 10, client: HttpClient | None = None) -> list[Photo]:
    from urllib.parse import urlencode
    client = client or HttpClient()
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": query, "gsrlimit": min(max(limit * 3, 10), 50),  # 라이선스로 걸러지므로 넉넉히
        "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": THUMB_W,
    }
    # 위키미디어 공식 API: 정직한 UA·속도 제한은 그대로 적용, robots.txt 확인만 생략(크롤러용 규칙)
    r = client.fetch(API + "?" + urlencode(params), check_robots=False)
    if isinstance(r, Blocked):
        raise BlockedError(r)
    import json
    return parse_commons(json.loads(r.text))[:limit]


def download_photo(photo: Photo, out_path: Path | str, client: HttpClient | None = None) -> Path:
    """1080px 이하 썸네일을 받아 저장하고 Pillow로 열어 검증."""
    from PIL import Image
    client = client or HttpClient()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = client.fetch(photo.thumb_url, check_robots=False)
    if isinstance(r, Blocked):
        raise BlockedError(r)
    out_path.write_bytes(r.content)
    with Image.open(out_path) as im:
        im.verify()
    return out_path


# ---- Openverse (키 없이 익명 호출, CC 메타데이터 포함) ----
OPENVERSE_API = "https://api.openverse.org/v1/images/"
_OV_ALLOWED = {"cc0": None, "pdm": None, "by": {"2.0", "2.1", "2.5", "3.0", "4.0"},
               "by-sa": {"2.0", "2.1", "2.5", "3.0", "4.0"}}  # nc·nd 제외
_OV_NAMES = {"cc0": "CC0", "pdm": "Public domain", "by": "CC BY", "by-sa": "CC BY-SA"}


def openverse_license_name(code: str, version: str | None) -> str:
    base = _OV_NAMES.get(code, code)
    return f"{base} {version}".strip() if code in ("by", "by-sa") and version else base


def is_allowed_openverse(code: str, version: str | None) -> bool:
    code = (code or "").lower()
    if code not in _OV_ALLOWED:
        return False
    vers = _OV_ALLOWED[code]
    return vers is None or (version or "") in vers


def parse_openverse(data: dict) -> list[Photo]:
    out = []
    for r in data.get("results", []):
        code, ver = (r.get("license") or "").lower(), r.get("license_version")
        if not is_allowed_openverse(code, ver):
            continue
        if (r.get("filetype") or "jpg").lower() not in ("jpg", "jpeg", "png", "webp"):
            continue
        thumb = r.get("thumbnail") or ""
        if not thumb:
            continue
        out.append(Photo(
            title=r.get("title") or "", page_url=r.get("foreign_landing_url") or "", file_url=r.get("url") or "",
            thumb_url=thumb, license=openverse_license_name(code, ver), license_url=r.get("license_url") or "",
            artist=strip_html(r.get("creator") or ""), width=r.get("width") or 0, height=r.get("height") or 0,
            mime="image/" + ("jpeg" if (r.get("filetype") or "jpg").lower() in ("jpg", "jpeg") else (r.get("filetype") or "").lower()),
            source=f"Openverse ({r.get('provider') or r.get('source') or '?'})"))
    return out


def search_openverse(query: str, limit: int = 10, client: HttpClient | None = None) -> list[Photo]:
    """익명 호출 한도(429)면 BlockedError(rate_limited_429). api.openverse.org의 robots는 /v1/images/를 막지만
    공식 공개 API(익명 사용 문서화)라서 Commons와 같이 robots 확인만 생략한다(정직한 UA·3초 간격은 유지)."""
    from urllib.parse import urlencode
    import json
    client = client or HttpClient()
    params = {"q": query, "page_size": min(max(limit * 3, 10), 50), "license": "cc0,pdm,by,by-sa"}
    r = client.fetch(OPENVERSE_API + "?" + urlencode(params), check_robots=False, timeout=60)  # 익명 호출이 느림(20초 넘게 걸림)
    if isinstance(r, Blocked):
        raise BlockedError(r)
    return parse_openverse(json.loads(r.text))[:limit]
