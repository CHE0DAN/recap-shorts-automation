"""MediaManager: 초안이 참조하는 모든 파일(영상, 음성, 음악, 효과음, 그림, 폰트)을 `<초안>/assets/<종류>/` 로 복사하고
CapCut 이 보게 될 경로 문자열을 돌려준다. 복사해 두면 초안 폴더를 옮기거나 zip 으로 묶어도 깨지지 않고, 미디어 누락이 뜨면
폴더 하나만 다시 연결하면 된다.

`json_root` 는 다른 위치·다른 PC 용 초안을 만들 때 쓴다(예: 여기서 만들어 `C:/Users/me/AppData/Local/CapCut/User Data/Projects/
com.lveditor.draft/<이름>` 로 폴더째 옮김). 남의 루트는 이 PC 의 파일을 가리킬 수 없으므로 그때는 호출하는 쪽이 copy=True 를 준다.
copy=False 는 원본을 제자리에서 참조한다(내보내는 중에 만든 파일은 `add(..., copy=True)` 로 따로 복사).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from PIL import Image

from recap_shorts.capcut.draft_format import US, uid

PHOTO_DURATION_US = 10_800 * US  # CapCut 은 정지 이미지를 3시간짜리 소재로 다룬다

_KIND_DIR = {"video": "video", "audio": "audio", "image": "image", "font": "font"}


@dataclass
class MediaItem:
    id: str                       # CapCut material id
    kind: str                     # video | audio | image | font
    src: Path                     # 이 PC 의 원본 파일
    local: Path                   # 쓰는 중인 초안 안의 파일
    json_path: str                # 초안 JSON 에 적는 경로 문자열
    name: str
    duration_us: int = 0
    width: int = 0
    height: int = 0
    has_audio: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def metetype(self) -> str:  # draft_meta_info 의 "metetype" (철자 그대로)
        return {"video": "video", "image": "photo", "audio": "music"}.get(self.kind, "none")


def _safe(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .")
    if len(name) > 80:   # 줄일 때 확장자는 남긴다
        suffix = Path(name).suffix[:16]
        name = name[:80 - len(suffix)] + suffix
    return name or "media"


def probe_media(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe 을(를) PATH 에서 찾지 못했습니다.")
    p = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",   # ffprobe 는 cp949 가 아니라 UTF-8 로 출력한다
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))               # 창 없는 앱에서 콘솔이 번쩍이지 않게
    if p.returncode != 0:
        raise FileNotFoundError(f"cannot probe {path}: {p.stderr[-300:]}")
    d = json.loads(p.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(d.get("format", {}).get("duration") or (a or v or {}).get("duration") or 0.0)
    return {"duration": dur, "width": int(v["width"]) if v else 0, "height": int(v["height"]) if v else 0,
            "has_audio": a is not None, "has_video": v is not None}


class MediaManager:
    def __init__(self, draft_dir: Path, *, json_root: str | None = None, copy: bool = True):
        self.draft_dir = Path(draft_dir)
        self.json_root = json_root
        self.copy = copy
        self._by_src: dict[tuple[str, str], MediaItem] = {}
        self._names: set[str] = set()

    # <draft>/<rel> 에 놓인 파일을 CapCut 이 보게 될 경로
    def _json_path(self, rel: PurePath) -> str:
        if self.json_root:
            root = PureWindowsPath(self.json_root) if re.match(r"^[A-Za-z]:[\\/]", self.json_root) else PurePosixPath(self.json_root)
            return (root / rel).as_posix()
        return (self.draft_dir / rel).resolve().as_posix()

    def _unique(self, kind: str, name: str) -> str:
        stem, suffix = Path(name).stem, Path(name).suffix
        cand, i = name, 2
        while f"{kind}/{cand}" in self._names:
            cand = f"{stem}_{i}{suffix}"
            i += 1
        self._names.add(f"{kind}/{cand}")
        return cand

    def add(self, src: str | Path, kind: str, *, name: str | None = None, copy: bool | None = None) -> MediaItem:
        src = Path(src)
        key = (str(src.resolve()), kind)
        if key in self._by_src:
            return self._by_src[key]
        if not src.exists():
            raise FileNotFoundError(f"media not found: {src}")
        do_copy = self.copy if copy is None else copy
        if do_copy:
            fname = self._unique(_KIND_DIR[kind], _safe(src.name))
            rel = PurePosixPath("assets") / _KIND_DIR[kind] / fname
            local = self.draft_dir / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() != local.resolve():
                shutil.copy2(src, local)
            json_path = self._json_path(rel)
        else:
            local, json_path = src, src.resolve().as_posix()
        item = MediaItem(id=uid(), kind=kind, src=src, local=local, json_path=json_path, name=name or src.name)
        if kind in ("video", "audio"):
            pr = probe_media(local)
            item.duration_us = int(round(pr["duration"] * US))
            item.width, item.height, item.has_audio = pr["width"], pr["height"], pr["has_audio"]
        elif kind == "image":
            with Image.open(local) as im:
                item.width, item.height = im.size
            item.duration_us = PHOTO_DURATION_US
        self._by_src[key] = item
        return item

    def items(self, kind: str | None = None) -> list[MediaItem]:
        return [m for m in self._by_src.values() if kind is None or m.kind == kind]

    def imported_for_meta(self) -> list[dict]:
        return [{"id": m.id, "metetype": m.metetype, "path": m.json_path, "name": m.name, "duration_us": m.duration_us,
                 "width": m.width, "height": m.height} for m in self.items() if m.kind in ("video", "audio", "image")]

    def total_bytes(self) -> int:
        return sum(m.local.stat().st_size for m in self.items() if m.local != m.src and m.local.exists())   # 복사한 바이트만
