"""썰쇼츠 job -> CapCut 초안 폴더(영상 파일 하나가 아니라 CapCut 에서 그림·글자·소리를 따로 고칠 수 있는 초안).

    python -m recap_shorts.capcut <job 폴더> [--drafts-dir 폴더] [--no-register]

순서: 초안 폴더 옆 임시 폴더 -> 렌더와 같은 계산으로 트랙 만들기(mapper) -> 초안 파일 쓰기 -> 이름 한 번에 바꾸기 ->
CapCut 프로젝트 목록(root_meta_info.json)에 올리기(백업 먼저, CapCut 이 켜져 있으면 건너뜀).
미디어는 늘 초안 안 assets/ 로 복사한다: 끝난 job 은 구글 드라이브로 옮겨지고 로컬에서 지워지므로 원본을 가리키면 깨진다.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import asdict
from pathlib import Path, PurePath

from recap_shorts.render import compose as C
from recap_shorts.render import layout as L

from . import desktop, writer
from . import draft_format as F
from .mapper import Mapper
from .media import MediaManager

RECORD = "out/capcut.json"      # job 쪽 기록(마지막으로 만든 초안)


def load_timeline(job_dir: Path) -> dict:
    """영상에 쓴 타임라인(timeline_fx.json 이 있으면 그것 — pipeline._final_timeline 과 같음)."""
    p = job_dir / "timeline_fx.json"
    if not p.is_file():
        p = job_dir / "timeline.json"
    if not p.is_file():
        raise FileNotFoundError("timeline.json 이 없습니다 — 장면 배치까지 끝난 뒤에 넘길 수 있습니다")
    return json.loads(p.read_text(encoding="utf-8"))


def _cover(tl: dict, job_dir: Path, out: Path, warnings: list[str]) -> bool:
    """CapCut 홈 화면 표지(360x640): 인트로 카드가 끝난 뒤 첫 그림이 보이는 프레임."""
    try:
        comp = C.Composer(tl, str(job_dir))
        cut = comp.intro.t_cut if comp.intro else float((tl.get("hook") or {}).get("end", 0) or 0)
        t = min(float(tl["duration"]) / 2, cut + 0.5)
        comp.frame_image(int(round(t * comp.fps))).resize((360, 640), resample=3).save(out, quality=88)
        return True
    except Exception:  # noqa: BLE001 — 표지는 꾸밈이라 실패해도 초안은 만든다
        warnings.append("표지 그림을 만들지 못했습니다 — 초안은 표지 없이 만듭니다")
        return False


def export_job(job_dir: Path | str, *, drafts_dir: Path | str | None = None, register: bool | None = None,
               draft_name: str | None = None, cfg: writer.CapCutConfig | None = None, bgm_mode: str | None = None,
               record: bool = True) -> dict:
    t0 = time.time()
    cfg = cfg or writer.CapCutConfig.from_env()
    job_dir = Path(job_dir)
    tl = load_timeline(job_dir)
    warnings: list[str] = []
    root = Path(drafts_dir) if drafts_dir else (desktop.detect_drafts_dir() or desktop.fallback_dir())
    root.mkdir(parents=True, exist_ok=True)
    in_capcut = desktop.is_capcut_root(root)
    if not in_capcut:
        warnings.append(f"CapCut 초안 폴더를 찾지 못해 {root} 에 만들었습니다. CapCut 설정의 '초안 위치'로 폴더를 옮긴 뒤 "
                        "CapCut 의 '미디어 다시 연결'로 assets 폴더를 지정하세요(RECAP_CAPCUT_DRAFTS_DIR 로 위치를 정할 수도 있습니다).")
    title = " ".join(t for t in (tl.get("title_lines") or []) if t) or job_dir.name
    name = draft_name or writer.folder_name(title)
    final = root / name
    if final.exists():
        name = f"{name}-{int(time.time()) % 10000}"
        final = root / name
    stage = root / f".recap-staging-{int(time.time() * 1000)}"
    stage.mkdir(parents=True)
    target_root = final.resolve().as_posix()      # 초안 JSON 은 이름을 바꾼 뒤의 자리를 가리켜야 한다
    try:
        mm = MediaManager(stage, json_root=target_root, copy=True)
        with tempfile.TemporaryDirectory(prefix="recap_capcut_") as td:
            mapped = Mapper(tl, job_dir, mm, Path(td), px_per_size=cfg.px_per_size, bgm_mode=bgm_mode).map()
        cover_ok = _cover(tl, job_dir, stage / "draft_cover.jpg", warnings)
        draft_id = F.uid()
        content = F.draft_content(draft_id=draft_id, name=name, width=L.W, height=L.H, fps=float(tl.get("fps", L.FPS)),
                                  duration_us=mapped.duration_us, tracks=mapped.tracks, materials=mapped.materials,
                                  draft_path=target_root, os_name=cfg.os_name, app_version=cfg.app_version,
                                  new_version=cfg.new_version)
        writer.write_draft(stage, content, name=name, draft_id=draft_id, fold_path=target_root,
                           root_path=PurePath(target_root).parent.as_posix(), mm=mm, has_cover=cover_ok)
        report = [asdict(r) for r in mapped.report]
        (stage / "recap_export.json").write_text(json.dumps({
            "job": job_dir.name, "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "draft_id": draft_id,
            "stats": mapped.stats, "report": report, "generator": "recap-shorts-automation recap_shorts/capcut",
            "format": {"os": cfg.os_name, "app_version": cfg.app_version, "new_version": cfg.new_version}},
            ensure_ascii=False, indent=1), encoding="utf-8")
        media_bytes = mm.total_bytes()
        stage.rename(final)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    check = writer.validate_draft(final)
    if not check["ok"]:
        warnings.append("초안 구조 검사에서 문제가 나왔습니다: " + "; ".join(check["errors"][:3]))
    reg = None
    if (cfg.register if register is None else register) and in_capcut:
        try:
            reg = desktop.register(final, root, json_name="draft_content.json" if cfg.os_name == "windows" else "draft_info.json")
        except Exception as e:  # noqa: BLE001 — 목록에 못 올려도 폴더는 남는다
            warnings.append(f"CapCut 프로젝트 목록에 올리지 못했습니다: {e}")
        if reg is not None and not reg.get("registered") and reg.get("reason"):
            warnings.append(reg["reason"])
    result = {"draft_dir": str(final), "draft_name": name, "draft_id": draft_id, "drafts_root": str(root),
              "in_capcut_folder": in_capcut, "registered": bool(reg and reg.get("registered")),
              "duration": round(mapped.duration_us / F.US, 3), "stats": mapped.stats, "report": report,
              "check": {"ok": check["ok"], "errors": check["errors"][:10]}, "media_bytes": media_bytes,
              "seconds": round(time.time() - t0, 2), "warnings": warnings,
              "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if record:
        try:
            p = job_dir / RECORD
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    return result


def last_export(job_dir: Path) -> dict | None:
    p = Path(job_dir) / RECORD
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(d, dict):
        d["exists"] = Path(str(d.get("draft_dir", ""))).is_dir()
        return d
    return None
