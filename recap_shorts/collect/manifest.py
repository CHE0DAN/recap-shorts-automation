"""자료 manifest: work/<job>/assets/manifest.jsonl, 자료마다 한 줄."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("news_card", "news_screenshot", "commons_photo", "community_screenshot", "ai_image", "user_source")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class AssetRecord:
    asset_id: str
    kind: str
    source_url: str
    site: str
    fetched_at: str
    license: str
    attribution: str
    file: str            # job 폴더 기준 상대경로(슬래시)
    sha256: str
    robots_allowed: bool | None
    flags: dict = field(default_factory=dict)
    note: str = ""


class Manifest:
    def __init__(self, job_dir: Path | str):
        self.job_dir = Path(job_dir)
        self.path = self.job_dir / "assets" / "manifest.jsonl"
        self.records: list[AssetRecord] = []

    def add(self, *, kind: str, source_url: str, site: str, file: Path | str, license: str = "",
            attribution: str = "", robots_allowed: bool | None = True, flags: dict | None = None,
            note: str = "") -> AssetRecord:
        if kind not in KINDS:
            raise ValueError(f"unknown kind: {kind}")
        f = Path(file)
        digest = sha256_file(f)
        rec = AssetRecord(
            asset_id=f"{kind}-{digest[:10]}", kind=kind, source_url=source_url, site=site,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            license=license, attribution=attribution,
            file=f.resolve().relative_to(self.job_dir.resolve()).as_posix(),
            sha256=digest, robots_allowed=robots_allowed, flags=flags or {}, note=note)
        self.records.append(rec)
        return rec

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            for r in self.records:
                fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
        return self.path

    @staticmethod
    def load(path: Path | str) -> list[dict]:
        return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
