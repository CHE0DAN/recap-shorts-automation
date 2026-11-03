"""초안 폴더 쓰기와 구조 검사 — 내용(트랙·세그먼트)을 어떻게 만드는지와 무관한 공용 부분.

    content = draft_format.draft_content(...)            # 호출하는 쪽(mapper)이 트랙·소재를 채워 만든다
    write_draft(stage, content, name=..., draft_id=..., fold_path=..., root_path=..., mm=mm, has_cover=True)
    validate_draft(stage)                                 # {"ok": bool, "errors": [...], ...}

write_draft 는 draft_content.json + draft_info.json + Timelines/<id>/ + draft_meta_info.json + attachment_pc_common.json +
performance_opt_info.json 을 쓴다. CapCut 9.x 로 열리는 것이 확인된 구현이다.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from recap_shorts.capcut import draft_format as F
from recap_shorts.capcut.media import MediaManager

_TRUE = {"1", "true", "yes"}
_FALSE = {"0", "false", "no"}


def _env_str(name: str, default: str) -> str:
    v = (os.environ.get(name) or "").strip()
    return v or default


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or "").strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return True if v in _TRUE else False if v in _FALSE else default


@dataclass
class CapCutConfig:
    px_per_size: float = 5.5        # 캔버스 px 몇 개가 CapCut 글자 크기 1인가 (캡컷에서 글자가 크면 올린다)
    app_version: str = "6.7.0"      # 초안에 적는 편집기 버전 (더 낮게 적힌 초안은 캡컷이 열 때 업그레이드한다)
    new_version: str = "140.0.0"    # 초안 new_version (포맷 버전)
    os_name: str = "windows"        # windows 는 draft_content.json, 그 외(mac)는 draft_info.json 을 등록 대상으로 쓴다
    copy_media: bool = True         # 미디어를 <초안>/assets 로 복사 (False 면 원본을 제자리에서 참조)
    register: bool = True           # root_meta_info.json 에 등록

    @classmethod
    def from_env(cls) -> "CapCutConfig":
        d = cls()
        return cls(px_per_size=_env_float("RECAP_CAPCUT_PX_PER_SIZE", d.px_per_size),
                   app_version=_env_str("RECAP_CAPCUT_APP_VERSION", d.app_version),
                   new_version=_env_str("RECAP_CAPCUT_NEW_VERSION", d.new_version),
                   os_name=_env_str("RECAP_CAPCUT_OS", d.os_name),
                   copy_media=_env_bool("RECAP_CAPCUT_COPY_MEDIA", d.copy_media),
                   register=_env_bool("RECAP_CAPCUT_REGISTER", d.register))


def folder_name(title: str) -> str:
    """초안 폴더 이름: 제목(금지 문자 제거, 40자) + _MMDD-HHMMSS. 제목이 비면 "recap"."""
    base = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", title or "").strip(" .")[:40] or "recap"
    return f"{base}_{time.strftime('%m%d-%H%M%S')}"


def write_draft(d: Path, content: dict, *, name: str, draft_id: str, fold_path: str, root_path: str,
                mm: MediaManager, has_cover: bool) -> None:
    enc = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    (d / "draft_content.json").write_text(enc, encoding="utf-8")   # Windows CapCut 이 읽는 본체
    (d / "draft_info.json").write_text(enc, encoding="utf-8")      # macOS·신버전이 읽는다
    tl_id = F.uid()
    tdir = d / "Timelines" / tl_id
    tdir.mkdir(parents=True)
    tl = dict(content, id=tl_id)
    tl_enc = json.dumps(tl, ensure_ascii=False, separators=(",", ":"))
    (tdir / "draft_info.json").write_text(tl_enc, encoding="utf-8")
    (tdir / "draft_info.json.bak").write_text(tl_enc, encoding="utf-8")
    now = int(time.time() * F.US)
    project = {"config": {}, "create_time": now, "id": draft_id, "main_timeline_id": tl_id, "update_time": now, "version": 0,
               "timelines": [{"create_time": now, "id": tl_id, "is_marked_delete": False, "name": name, "update_time": now}]}
    p_enc = json.dumps(project, ensure_ascii=False, separators=(",", ":"))
    (d / "Timelines" / "project.json").write_text(p_enc, encoding="utf-8")
    (d / "Timelines" / "project.json.bak").write_text(p_enc, encoding="utf-8")
    meta = F.meta_info(draft_id=draft_id, name=name, fold_path=fold_path, root_path=root_path, duration_us=content["duration"],
                       new_version=content["new_version"], imported=mm.imported_for_meta(), cover="draft_cover.jpg" if has_cover else "")
    (d / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (d / "attachment_pc_common.json").write_text(json.dumps(F.ATTACHMENT_PC_COMMON), encoding="utf-8")
    (d / "performance_opt_info.json").write_text(json.dumps(F.PERFORMANCE_OPT), encoding="utf-8")


GROUP_FOR_TRACK = {"video": "videos", "audio": "audios", "text": "texts"}


def _styles_ok(styles: object, text_len: int) -> bool:
    """style 들의 range 가 0 에서 시작해 빈틈·겹침 없이 이어져 len(text) 에서 끝난다."""
    if not isinstance(styles, list) or not styles:
        return False
    pos = 0
    for st in styles:
        rng = st.get("range") if isinstance(st, dict) else None
        if not (isinstance(rng, list) and len(rng) == 2) or rng[0] != pos or rng[1] < rng[0]:
            return False
        pos = rng[1]
    return pos == text_len


def validate_draft(draft_dir: Path, *, check_files: bool = True) -> dict:
    """써 놓은 초안의 구조 검사(시험과 내보내기 화면에서 쓴다)."""
    draft_dir = Path(draft_dir)
    errors: list[str] = []
    c = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    info = json.loads((draft_dir / "draft_info.json").read_text(encoding="utf-8"))
    if info != c:
        errors.append("draft_info.json != draft_content.json")
    mats = c["materials"]
    ids = {m["id"] for group in mats.values() for m in group if isinstance(m, dict) and "id" in m}
    by_id = {m["id"]: m for group in mats.values() for m in group if isinstance(m, dict) and "id" in m}
    end_max = 0
    for t in c["tracks"]:
        group = GROUP_FOR_TRACK.get(t["type"])
        prev_end = 0
        segs = t["segments"]
        for i, sg in enumerate(segs):
            tr = sg["target_timerange"]
            if tr["start"] < prev_end:
                errors.append(f"overlap in track {t['name']} at segment {i}")
            prev_end = tr["start"] + tr["duration"]
            end_max = max(end_max, prev_end)
            m = by_id.get(sg["material_id"])
            if m is None or (group and m not in mats[group]):
                errors.append(f"track {t['name']} segment {i}: material {sg['material_id']} missing from {group}")
                continue
            for ref in sg.get("extra_material_refs", []):
                if ref not in ids:
                    errors.append(f"track {t['name']} segment {i}: dangling ref {ref}")
            src = sg.get("source_timerange")
            if src and t["type"] in ("video", "audio"):
                if src["start"] + src["duration"] > m.get("duration", 0) + 1000:
                    errors.append(f"track {t['name']} segment {i}: source range beyond material ({src}, {m.get('duration')})")
                if abs(src["duration"] / max(1e-6, sg["speed"]) - tr["duration"]) > 2:
                    errors.append(f"track {t['name']} segment {i}: speed/duration mismatch")
            if t["type"] == "text":
                content = json.loads(m["content"])
                if not _styles_ok(content.get("styles"), len(content["text"])):
                    errors.append(f"text range mismatch: {content['text']!r}")
        if t["type"] == "video" and t is c["tracks"][0]:
            pos = 0
            for i, sg in enumerate(segs):
                if sg["target_timerange"]["start"] != pos:
                    errors.append(f"main track gap before segment {i}")
                pos = sg["target_timerange"]["start"] + sg["target_timerange"]["duration"]
    if end_max != c["duration"]:
        errors.append(f"duration {c['duration']} != last segment end {end_max}")
    files = 0
    if check_files:
        for group in ("videos", "audios"):
            for m in mats[group]:
                files += 1
                if not Path(m["path"]).exists():
                    errors.append(f"missing media file {m['path']}")
        for m in mats["texts"]:
            fonts = {st.get("font", {}).get("path") for st in json.loads(m["content"]).get("styles", []) if isinstance(st, dict)}
            for fp in sorted(f for f in fonts if f):
                if not Path(fp).exists():
                    errors.append(f"missing font file {fp}")
    for name in ("draft_meta_info.json", "Timelines/project.json", "attachment_pc_common.json"):
        if not (draft_dir / name).exists():
            errors.append(f"missing {name}")
    return {"ok": not errors, "errors": errors[:50], "tracks": len(c["tracks"]),
            "segments": sum(len(t["segments"]) for t in c["tracks"]), "files_checked": files, "duration_us": c["duration"]}
