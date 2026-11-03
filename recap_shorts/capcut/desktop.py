"""CapCut Desktop 연동: 초안 폴더 찾기, root_meta_info.json 등록, 프로젝트 목록, 앱 실행, 옮긴 초안 재연결, zip.

등록·재연결은 clipcraft-labs/capcut-draft (MIT) 의 방식을 따랐다: root_meta_info.json 을 백업하고, `all_draft_store` 에서 이
초안의 항목을 바꾸거나 덧붙이고, 폴더를 옮겼을 때는 초안에 기록된 `path` 로 시작하는 절대 경로를 새 위치로 바꾼다. 직접 다시
구현했고 코드를 가져오지 않았다. 읽을 수 없는 목록은 절대 다시 쓰지 않는다(기존 초안이 캡컷 홈에서 사라지기 때문).

설정은 환경변수로 받는다: RECAP_CAPCUT_DRAFTS_DIR(비우면 자동 탐지), RECAP_CAPCUT_EXE, RECAP_WORK_ROOT(없으면 <저장소>/work).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_JSONS = ("draft_content.json", "draft_info.json")
EXE_NAME = "CapCut.exe"     # launch() 가 켜는 프로그램은 이것뿐: 설정한 경로의 파일 이름이 다르면 무시한다
INDEX_NAME = "root_meta_info.json"
EXPORT_INFO_NAME = "recap_export.json"   # 우리가 만든 초안임을 알리는 표지 파일
BACKUP_KEEP = 10            # 목록 옆에 남기는 날짜 백업 수: root_meta_info.json.<YYYYMMDD-HHMMSS>.bak
_BACKUP_STAMP = re.compile(r"^(\d{8}-\d{6})(?:-(\d+))?$")
RELINK_BAK = ".relink.bak"  # relink() 가 고치기 전 파일을 <이름>.relink.bak 로 남긴다 (".bak" 아님: 캡컷이 Timelines/*/draft_info.json.bak 을 따로 쓴다)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def work_root() -> Path:
    return Path(_env("RECAP_WORK_ROOT") or REPO_ROOT / "work")


def candidate_dirs() -> list[Path]:
    home = Path.home()
    out: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft")
    out += [home / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft",
            home / "Movies/CapCut/User Data/Projects/com.lveditor.draft",
            home / "Library/Containers/com.lemon.lvoverseas/Data/Movies/CapCut/User Data/Projects/com.lveditor.draft"]
    return out


def detect_drafts_dir() -> Path | None:
    configured = _env("RECAP_CAPCUT_DRAFTS_DIR")
    if configured:      # 지정했는데 폴더가 없으면 자동 탐지로 넘어가지 않고 미탐지로 본다
        p = Path(os.path.expandvars(os.path.expanduser(configured)))
        return p if p.is_dir() else None
    return next((p for p in candidate_dirs() if p.is_dir()), None)


def fallback_dir() -> Path:
    p = work_root() / "_capcut"
    p.mkdir(parents=True, exist_ok=True)
    return p


def status() -> dict:
    d = detect_drafts_dir()
    exe = find_exe()
    return {"platform": sys.platform, "drafts_dir": str(d) if d else None, "detected": d is not None,
            "configured": bool(_env("RECAP_CAPCUT_DRAFTS_DIR")), "fallback_dir": str(fallback_dir()),
            "exe": str(exe) if exe else None, "can_launch": exe is not None or sys.platform == "darwin",
            "candidates": [str(p) for p in candidate_dirs()]}


def is_capcut_root(drafts_dir: Path) -> bool:
    return (drafts_dir / "root_meta_info.json").exists() or drafts_dir.name == "com.lveditor.draft"


def capcut_running() -> bool:
    """CapCut.exe 가 Windows 프로세스 목록에 있다. 확인에 실패하면(tasklist 없음, 시간 초과, 다른 OS) 실행 중이 아닌 것으로 본다."""
    if sys.platform != "win32":
        return False
    try:
        p = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/NH"], capture_output=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = p.stdout.decode("utf-8", "replace").lower().splitlines()
    except Exception:  # noqa: BLE001 - 확인이 실패해도 내보내기를 막지 않는다
        return False
    return p.returncode == 0 and any(ln.split()[:1] == [EXE_NAME.lower()] for ln in lines)


def _load_index(idx: Path) -> tuple[dict | None, str, str]:
    """읽을 수 있는 root_meta_info.json 이면 (목록 객체, 초안 목록 키, ""), 아니면 (None, "", 이유). 추측하지 않는다."""
    try:
        root = json.loads(idx.read_text(encoding="utf-8"))
    except OSError:
        return None, "", "파일을 열 수 없음"
    except ValueError:      # JSONDecodeError, UnicodeDecodeError
        return None, "", "JSON 형식이 깨져 있음"
    if not isinstance(root, dict):
        return None, "", "최상위가 객체가 아님"
    key = next((k for k, v in root.items() if isinstance(v, list) and "draft_store" in k), None)
    if key is None:
        if "all_draft_store" in root:
            return None, "", "초안 목록이 배열이 아님"
        key = "all_draft_store"
    return root, key, ""


def _dated_backups(idx: Path) -> list[tuple[tuple[str, int], Path]]:
    """우리가 만든 날짜 백업, 오래된 순: ((YYYYMMDD-HHMMSS, 순번), 경로). 예전 .bak 이나 사용자가 붙인 이름은 우리 것이 아니다."""
    found = []
    for p in idx.parent.glob(f"{idx.name}.*.bak"):
        m = _BACKUP_STAMP.match(p.name[len(idx.name) + 1:-4])
        if m:
            found.append(((m.group(1), int(m.group(2) or 1)), p))
    return sorted(found)


def _backup_index(idx: Path) -> Path:
    """읽히는 목록의 날짜 백업을 만들고 최신 BACKUP_KEEP 개만 남긴다."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = max((k[1] for k, _ in _dated_backups(idx) if k[0] == stamp), default=0) + 1     # 같은 초: -2, -3 ... (지운 이름은 다시 쓰지 않음)
    bak = idx.with_name(f"{idx.name}.{stamp}.bak" if n == 1 else f"{idx.name}.{stamp}-{n}.bak")
    shutil.copy2(idx, bak)
    for _, old in _dated_backups(idx)[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return bak


def register(draft_dir: Path, drafts_dir: Path, *, json_name: str = "draft_content.json") -> dict:
    """초안을 캡컷 프로젝트 목록 맨 앞에 올린다. -> {"registered": True, "index", "backup", "draft_id"}. 목록을 읽을 수 없거나 캡컷이
    실행 중이라 건드리지 않았으면 {"registered": False, "reason": <한국어>, "index", "backup": None, "draft_id"}."""
    draft_dir, drafts_dir = draft_dir.resolve(), drafts_dir.resolve()
    content = json.loads((draft_dir / json_name).read_text(encoding="utf-8"))
    meta_p = draft_dir / "draft_meta_info.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    now = int(time.time() * 1_000_000)
    entry = {
        "draft_cover": str(draft_dir / "draft_cover.jpg"), "draft_fold_path": str(draft_dir), "draft_id": content["id"],
        "draft_json_file": str(draft_dir / json_name), "draft_name": content.get("name") or draft_dir.name,
        "draft_root_path": str(drafts_dir), "draft_new_version": meta.get("draft_new_version", ""),
        "draft_is_invisible": False, "draft_is_cloud_temp_draft": False, "draft_is_ai_shorts": False,
        "draft_timeline_materials_size": 0, "draft_type": "", "draft_web_draft_id": "", "streaming_edit_draft_ready": True,
        "tm_draft_create": meta.get("tm_draft_create", now), "tm_draft_modified": now, "tm_draft_removed": 0,
        "tm_duration": int(content.get("duration") or 0), "cloud_draft_sync": False, "cloud_draft_cover": False,
    }
    idx = drafts_dir / INDEX_NAME

    def skipped(why: str) -> dict:
        return {"registered": False, "reason": why, "index": str(idx), "backup": None, "draft_id": entry["draft_id"]}

    if capcut_running():    # 캡컷은 목록을 메모리에 들고 있다가 종료할 때 우리가 쓴 것을 덮어쓸 수 있다(여기서 확인한 것은 아님)
        return skipped(f"캡컷이 실행 중이라 프로젝트 목록({INDEX_NAME})에는 올리지 않았습니다 - 실행 중에 바꾼 목록은 캡컷이 종료될 때 덮어쓸 수 있습니다. "
                       "초안 폴더는 만들어져 있습니다. 캡컷을 완전히 종료한 뒤 다시 내보내면 목록에 올릴 수 있습니다.")
    root: dict = {"all_draft_store": [], "draft_ids": 0, "root_path": str(drafts_dir)}
    key, backup = "all_draft_store", None
    if idx.exists():
        loaded, key, why = _load_index(idx)
        if loaded is None:  # 이 초안 하나만 든 목록을 쓰면 다른 초안이 캡컷 홈에서 전부 사라진다
            return skipped(f"{INDEX_NAME}을(를) 읽을 수 없어({why}) 캡컷 프로젝트 목록은 건드리지 않았습니다 - 기존 초안이 목록에서 사라지지 않게 하려는 것입니다. "
                           "초안 폴더는 만들어져 있습니다. 파일을 확인한 뒤 다시 내보내세요.")
        root, backup = loaded, _backup_index(idx)
    store = [e for e in root.get(key, []) if isinstance(e, dict) and e.get("draft_id") != entry["draft_id"]
             and Path(str(e.get("draft_fold_path", ""))) != draft_dir]
    store.insert(0, entry)   # 최신이 앞: 캡컷 홈 화면과 같은 순서
    root[key] = store
    root["draft_ids"] = len(store)
    tmp = idx.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(root, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, idx)
    return {"registered": True, "index": str(idx), "backup": str(backup) if backup else None, "draft_id": entry["draft_id"]}


def _read_json_object(p: Path) -> dict | None:
    """JSON 파일의 객체. 없거나 읽을 수 없거나 깨졌거나 객체가 아니면 None (그런 초안도 목록에는 나오고, 우리 것으로만 표시되지 않는다)."""
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_projects(drafts_dir: Path | None = None, limit: int = 50) -> list[dict]:
    drafts_dir = drafts_dir or detect_drafts_dir() or fallback_dir()
    out = []
    if not drafts_dir.is_dir():
        return out
    for d in drafts_dir.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta_p = d / "draft_meta_info.json"
        if not meta_p.exists() and not any((d / n).exists() for n in DRAFT_JSONS):
            continue
        meta = _read_json_object(meta_p) or {}
        info = _read_json_object(d / EXPORT_INFO_NAME)
        stats = (info or {}).get("stats")
        out.append({"name": meta.get("draft_name") or d.name, "path": str(d), "folder": d.name,
                    "modified": (meta.get("tm_draft_modified") or int(d.stat().st_mtime * 1e6)) / 1e6,
                    "duration": (meta.get("tm_duration") or 0) / 1e6, "cover": str(d / "draft_cover.jpg") if (d / "draft_cover.jpg").exists() else None,
                    "ours": info is not None, "job_id": (info or {}).get("job_id"),
                    "segments": stats.get("segments") if isinstance(stats, dict) else None})
    out.sort(key=lambda x: x["modified"], reverse=True)
    return out[:limit]


def find_exe() -> Path | None:
    configured = _env("RECAP_CAPCUT_EXE")
    cands = [Path(configured)] if configured else []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands += [Path(local) / "CapCut" / "Apps" / EXE_NAME]
    cands += [Path("C:/Program Files/CapCut") / EXE_NAME]
    return next((p for p in cands if p.name.lower() == EXE_NAME.lower() and p.is_file()), None)


def launch() -> dict:
    exe = find_exe()
    if exe and sys.platform == "win32":
        os.startfile(str(exe))  # type: ignore[attr-defined]  # noqa: S606
        return {"launched": True, "exe": str(exe)}
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "CapCut"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"launched": True, "exe": "CapCut.app"}
    return {"launched": False, "reason": "CapCut 실행 파일을 찾지 못했습니다 (Windows: RECAP_CAPCUT_EXE 설정)"}


def reveal(path: Path) -> dict:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])
        return {"opened": True}
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return {"opened": True}
    return {"opened": False, "path": str(path)}


def _rebase(value, old: str, new: str):
    if isinstance(value, dict):
        return {k: _rebase(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_rebase(v, old, new) for v in value]
    if isinstance(value, str):
        if value.startswith(old):
            return new + value[len(old):]
        if value.startswith("{") and old in value:  # 폰트 경로가 든 글자 content JSON
            try:
                return json.dumps(_rebase(json.loads(value), old, new), ensure_ascii=False)
            except json.JSONDecodeError:
                return value
    return value


def relink(draft_dir: Path) -> dict:
    """초안 폴더를 다른 곳/다른 PC 로 복사한 뒤: 옛 폴더 아래를 가리키던 모든 경로를 새 폴더로 바꾼다."""
    draft_dir = draft_dir.resolve()
    new = draft_dir.as_posix()
    changed = 0
    tl = sorted(f for f in (draft_dir / "Timelines").glob("*/draft_info.json*") if not f.name.endswith(RELINK_BAK))
    files = [draft_dir / n for n in DRAFT_JSONS] + tl + [draft_dir / "draft_meta_info.json"]
    old = None
    for f in files:
        if f.is_file() and f.name in DRAFT_JSONS:
            old = json.loads(f.read_text(encoding="utf-8")).get("path")
            break
    if not old or old == new:
        return {"changed": 0, "old": old, "new": new}
    plan: list[tuple[Path, str]] = []   # 첫 쓰기 전에 전부 읽고 바꿔 둔다: 깨진 파일이 있으면 초안은 그대로 남는다
    for f in files:
        if not f.is_file():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        data = _rebase(data, old, new)
        if f.name == "draft_meta_info.json":
            data["draft_fold_path"], data["draft_root_path"] = new, draft_dir.parent.as_posix()
        plan.append((f, json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
    staged: list[tuple[Path, Path]] = []   # (임시 파일, 대상): 첫 교체 전에 전부 써 두므로 디스크가 차도 어느 파일도 바뀌기 전에 멈춘다
    try:
        for f, text in plan:
            shutil.copy2(f, f.with_name(f.name + RELINK_BAK))   # 바꾸기 전 모습, 다음 relink 가 덮어쓴다
            tmp = f.with_name(f.name + ".tmp")
            staged.append((tmp, f))
            tmp.write_text(text, encoding="utf-8")
        for tmp, f in staged:
            os.replace(tmp, f)
            changed += 1
    finally:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
    return {"changed": changed, "old": old, "new": new}


def zip_draft(draft_dir: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(draft_dir.rglob("*")):
            if f.is_file():
                z.write(f, Path(draft_dir.name) / f.relative_to(draft_dir))
    return out


__all__ = ["detect_drafts_dir", "fallback_dir", "status", "register", "capcut_running", "list_projects", "launch", "reveal", "relink",
           "zip_draft", "is_capcut_root", "find_exe", "candidate_dirs", "work_root", "REPO_ROOT"]
