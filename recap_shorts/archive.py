"""끝난 job 을 구글 드라이브(데스크톱 앱이 연결한 G:\\내 드라이브)로 옮긴다.

- 폴더 통째로 복사 → 양쪽 파일을 SHA-256 으로 비교 → 모두 같을 때만 로컬 폴더를 지운다. 하나라도 다르면 로컬을 둔다.
- 옮긴 job 목록은 work/_archive.json(작은 색인)에 로컬로 남긴다. 드라이브가 꺼져 있어도 목록에 보이도록 state 요약을 함께 둔다.
- 설정은 config/storage.json(기본 꺼짐) 위에 config/storage.local.json(gitignore, 이 PC 에서만 켤 때)을 덮어 읽는다.
  시험(pytest) 중에는 set_config_override 로 정하지 않는 한 항상 꺼져 있다(진짜 드라이브를 건드리지 않음).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import string
import sys
import threading
from datetime import datetime
from pathlib import Path

from recap_shorts import errors

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "storage.json"
LOCAL_CONFIG_PATH = ROOT / "config" / "storage.local.json"   # gitignore — 이 PC 에서만 바꾼 값
INDEX_NAME = "_archive.json"
MANIFEST_NAME = "_archive_manifest.json"
DRIVE_DIR_NAMES = ("내 드라이브", "My Drive")
DEFAULT = {"enabled": False, "root": "auto", "folder": "recap-shorts-보관", "delete_local": True}

_override: dict | None = None
_index_lock = threading.Lock()
_active: set[str] = set()          # 지금 옮기는 중인 job id (같은 job 을 두 번 옮기지 않게)
_active_lock = threading.Lock()


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ------------------------------------------------------------------ 설정
def set_config_override(cfg: dict | None) -> None:
    """시험용: 설정 파일 대신 이 값을 쓴다(None 이면 해제). 예: {"enabled": True, "root": str(tmp)}"""
    global _override
    _override = None if cfg is None else {**DEFAULT, **(cfg.get("archive", cfg))}


def load_config() -> dict:
    """archive 설정(dict). pytest 중이고 override 가 없으면 꺼진 설정."""
    if _override is not None:
        return dict(_override)
    if "pytest" in sys.modules:
        return {**DEFAULT, "enabled": False, "root": None}
    cfg = dict(DEFAULT)
    for path in (CONFIG_PATH, LOCAL_CONFIG_PATH):
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {**DEFAULT, "enabled": False}      # 설정을 못 읽으면 옮기지 않는다
        cfg.update(raw.get("archive") or {})
    return cfg


def drive_root(cfg: dict | None = None) -> Path | None:
    """구글 드라이브의 '내 드라이브' 폴더. 못 찾으면 None. cfg 는 archive 설정(또는 그것을 담은 전체 설정)."""
    cfg = load_config() if cfg is None else cfg.get("archive", cfg)
    root = cfg.get("root", "auto")
    if not root:
        return None
    if str(root).lower() != "auto":
        p = Path(root)
        return p if p.is_dir() else None
    if os.name != "nt":
        return None
    letters = ["G"] + [c for c in string.ascii_uppercase if c not in "GAB"]
    for c in letters:
        for name in DRIVE_DIR_NAMES:
            p = Path(f"{c}:/{name}")
            try:
                if p.is_dir():
                    return p
            except OSError:
                continue
    return None


def archive_base(cfg: dict | None = None) -> Path | None:
    """<드라이브>/<folder> (없으면 만들지 않음). 드라이브가 없으면 None."""
    cfg = load_config() if cfg is None else cfg.get("archive", cfg)
    r = drive_root(cfg)
    return r / (cfg.get("folder") or DEFAULT["folder"]) if r else None


def storage_info(cfg: dict | None = None) -> dict:
    cfg = load_config() if cfg is None else cfg.get("archive", cfg)
    r = drive_root(cfg)
    out = {"enabled": bool(cfg.get("enabled")), "found": r is not None, "root": str(r) if r else None,
           "folder": cfg.get("folder"), "path": str(r / (cfg.get("folder") or DEFAULT["folder"])) if r else None,
           "delete_local": bool(cfg.get("delete_local", True)), "free_bytes": None, "total_bytes": None}
    if r:
        try:
            u = shutil.disk_usage(r)
            out["free_bytes"], out["total_bytes"] = u.free, u.total
        except OSError:
            pass
    return out


# ------------------------------------------------------------------ 복사·검증
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file())


def rmtree_force(p: Path) -> None:
    """읽기 전용 파일(윈도)도 지운다."""
    def fix(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=fix)
    else:
        shutil.rmtree(p, onerror=fix)


def archive_job(job_dir: Path | str, dest_dir: Path | str, delete_local: bool = True) -> dict:
    """job 폴더를 dest_dir 로 복사·검증하고 _archive_manifest.json 을 쓴다. 모두 같을 때만 delete_local 이면 로컬을 지운다.
    돌려주는 값: {ok, error, files, bytes, dest, deleted_local, delete_error}. 오류가 나면 로컬은 그대로 둔다."""
    src, dest = Path(job_dir), Path(dest_dir)
    out = {"ok": False, "error": None, "files": 0, "bytes": 0, "dest": str(dest), "deleted_local": False,
           "delete_error": None}
    try:
        if not src.is_dir():
            raise FileNotFoundError(f"폴더 없음: {src}")
        if src.resolve() == dest.resolve():
            raise ValueError("원본과 보관 위치가 같습니다")
        dest.mkdir(parents=True, exist_ok=True)
        files = _files(src)
        for f in files:
            target = dest / f.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        entries = []
        for f in files:                            # 복사가 끝난 뒤 양쪽을 다시 읽어 비교
            rel = f.relative_to(src)
            a, b = _sha256(f), _sha256(dest / rel)
            if a != b:
                raise ValueError(f"해시가 다름: {rel.as_posix()}")
            entries.append({"rel": rel.as_posix(), "bytes": f.stat().st_size, "sha256": a})
        manifest = {"archived_at": now(), "source": str(src), "files": entries}
        (dest / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        out.update(ok=True, files=len(entries), bytes=sum(e["bytes"] for e in entries))
    except Exception as e:  # noqa: BLE001  화면·기록에 가는 문구 — 예외 이름·경로 없이(errors)
        out["error"] = errors.screen_text(e, "구글 드라이브로 옮기지 못했습니다 — 파일을 복사하지 못했습니다")
        out["detail"] = f"{type(e).__name__}: {str(e)[:300]}"     # 로그 파일에만
        return out
    if delete_local:
        try:
            rmtree_force(src)
            out["deleted_local"] = True
        except OSError as e:
            out["delete_error"] = errors.screen_text(e, "복사는 됐지만 로컬 폴더를 지우지 못했습니다")
            out["delete_detail"] = f"{type(e).__name__}: {str(e)[:200]}"
    return out


# ------------------------------------------------------------------ 색인 work/_archive.json
def index_path(work_root: Path | str) -> Path:
    return Path(work_root) / INDEX_NAME


def load_index(work_root: Path | str) -> list[dict]:
    try:
        data = json.loads(index_path(work_root).read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and e.get("id") and e.get("path")]
    except (OSError, ValueError, TypeError):
        return []


def _write_index(work_root: Path, entries: list[dict]) -> None:
    p = index_path(work_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def add_index_entry(work_root: Path | str, entry: dict) -> None:
    """같은 id 가 있으면 바꾸고 없으면 덧붙인다."""
    with _index_lock:
        entries = [e for e in load_index(work_root) if e["id"] != entry["id"]]
        entries.append(entry)
        entries.sort(key=lambda e: e.get("created_at") or "")
        _write_index(Path(work_root), entries)


def make_entry(state: dict, path: Path | str, files: int, nbytes: int, archived_at: str | None = None) -> dict:
    snap = {k: v for k, v in json.loads(json.dumps(state)).items() if k != "log"}
    return {"id": state["id"], "title": state.get("title"), "created_at": state.get("created_at"),
            "archived_at": archived_at or now(), "path": str(path), "files": files, "bytes": nbytes, "state": snap}


# ------------------------------------------------------------------ job 단위
def archive_state(job) -> dict:
    return job.state.get("archive") or {}


def archive_job_record(job, cfg: dict | None = None) -> dict:
    """끝난 job 을 드라이브로 옮기고 job.state["archive"] 를 정한다. 절대 예외를 내지 않는다(job 자체는 실패시키지 않음).
    돌려주는 값은 state["archive"]."""
    cfg = load_config() if cfg is None else cfg.get("archive", cfg)
    try:
        if archive_state(job).get("status") == "done":
            return archive_state(job)
        base = archive_base(cfg)
        if base is None:
            with job.lock:
                job.state["archive"] = {"status": "skipped", "at": now(), "error": "구글 드라이브를 찾지 못했습니다"}
                job.log("구글 드라이브를 찾지 못해 로컬에 그대로 둡니다")
            return job.state["archive"]
        with _active_lock:
            if job.id in _active:
                return archive_state(job)
            _active.add(job.id)
        try:
            return _move(job, base, bool(cfg.get("delete_local", True)))
        finally:
            with _active_lock:
                _active.discard(job.id)
    except Exception as e:  # noqa: BLE001
        job.state["archive"] = {"status": "error", "at": now(),
                                "error": errors.screen_text(e, "구글 드라이브로 옮기지 못했습니다")}
        try:
            job.log(f"구글 드라이브로 옮기지 못함: {job.state['archive']['error']}")
        except Exception:  # noqa: BLE001
            pass
        return job.state["archive"]


def _move(job, base: Path, delete_local: bool) -> dict:
    dest = base / job.id
    job.log("구글 드라이브로 옮기는 중…")
    # 복사본의 state.json 이 '옮김' 으로 적히도록 복사 전에 먼저 적는다(실패하면 아래에서 error 로 되돌림)
    with job.lock:
        job.state["archive"] = {"status": "done", "path": str(dest), "at": now(), "error": None}
        job.log(f"구글 드라이브로 옮김: {dest}")
    res = archive_job(job.dir, dest, delete_local=delete_local)
    if not res["ok"]:
        with job.lock:
            job.state["archive"] = {"status": "error", "path": str(dest), "at": now(), "error": res["error"]}
            job.log(f"구글 드라이브로 옮기지 못함 — 로컬에 그대로 둡니다: {res['error']}")
        return job.state["archive"]
    with job.lock:
        job.dir = dest
        job.readonly = True
        if res.get("delete_error"):
            job.state["archive"]["warning"] = f"로컬 폴더를 다 지우지 못함: {res['delete_error']}"
        add_index_entry(job.root, make_entry(job.state, dest, res["files"], res["bytes"]))
    return job.state["archive"]
