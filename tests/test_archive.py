"""구글 드라이브 보관 시험 — 임시 폴더만 쓴다(진짜 G: 는 건드리지 않음)."""
import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from recap_shorts import archive
from recap_shorts import pipeline as P
from recap_shorts.app import create_app
from tests.pipeline.fakes import FakeDeps

SRC = {"gallery": "baseball_new13", "no": 2101, "url": "https://gall.dcinside.com/board/view/?id=baseball_new13&no=2101",
       "minor": False}
ALL_AUTO = {"auto_steps": list(P.CONFIRM_STEPS)}


@pytest.fixture(autouse=True)
def reset_override():
    archive.set_config_override(None)
    yield
    archive.set_config_override(None)


def drive_cfg(tmp_path, **kw):
    d = tmp_path / "drive"
    d.mkdir(exist_ok=True)
    return {"enabled": True, "root": str(d), "folder": "보관", **kw}


def make_job_dir(root, name="job1"):
    d = root / name
    (d / "out").mkdir(parents=True)
    (d / "state.json").write_text("{}", encoding="utf-8")
    (d / "out" / "final.mp4").write_bytes(b"video" * 1000)
    (d / "note.txt").write_text("안녕", encoding="utf-8")
    ro = d / "ro.txt"
    ro.write_text("읽기 전용", encoding="utf-8")
    os.chmod(ro, stat.S_IREAD)
    return d


def run_done(tmp_path, cfg=None, jobs_dir="work"):
    """끝까지 도는 job 하나 (확인 단계 전부 자동)."""
    if cfg is not None:
        archive.set_config_override(cfg)
    store = P.JobStore(tmp_path / jobs_dir)
    runner = P.Runner(store, FakeDeps())
    runner.start()
    job = store.create(dict(SRC), dict(ALL_AUTO))
    runner.submit(job)
    assert runner.wait_idle(60)
    return store, runner, job


# ------------------------------------------------------------------ archive_job
def test_archive_job_success_deletes_local_and_manifest_matches(tmp_path):
    src = make_job_dir(tmp_path)
    dest = tmp_path / "drive" / "job1"
    res = archive.archive_job(src, dest, delete_local=True)
    assert res["ok"] and res["deleted_local"] and res["files"] == 4
    assert not src.exists()
    mf = json.loads((dest / archive.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert {"archived_at", "source", "files"} <= set(mf)
    by = {e["rel"]: e for e in mf["files"]}
    assert set(by) == {"state.json", "out/final.mp4", "note.txt", "ro.txt"}
    for rel, e in by.items():
        assert e["bytes"] == (dest / rel).stat().st_size and e["sha256"] == archive._sha256(dest / rel)


def test_archive_job_keep_local_when_not_deleting(tmp_path):
    src = make_job_dir(tmp_path)
    res = archive.archive_job(src, tmp_path / "d" / "job1", delete_local=False)
    assert res["ok"] and not res["deleted_local"] and src.is_dir()


def test_archive_job_mismatch_keeps_local(tmp_path, monkeypatch):
    src = make_job_dir(tmp_path)
    dest = tmp_path / "drive" / "job1"
    real = archive._sha256
    monkeypatch.setattr(archive, "_sha256", lambda p: "bad" if dest in p.parents else real(p))
    res = archive.archive_job(src, dest, delete_local=True)
    assert not res["ok"] and "해시" in res["error"] and not res["deleted_local"]
    assert (src / "out" / "final.mp4").is_file() and (src / "ro.txt").is_file()
    assert not (dest / archive.MANIFEST_NAME).exists()


def test_archive_job_missing_source(tmp_path):
    res = archive.archive_job(tmp_path / "없음", tmp_path / "d", True)
    assert not res["ok"] and res["error"]


# ------------------------------------------------------------------ 설정·드라이브 찾기
def test_drive_root_explicit_and_missing(tmp_path):
    assert archive.drive_root({"root": str(tmp_path)}) == tmp_path
    assert archive.drive_root({"archive": {"root": str(tmp_path / "없음")}}) is None
    assert archive.drive_root({"root": None}) is None


def test_config_disabled_under_pytest_by_default():
    cfg = archive.load_config()
    assert not cfg["enabled"] and archive.drive_root(cfg) is None


# ------------------------------------------------------------------ 색인
def test_index_roundtrip(tmp_path):
    state = {"id": "a1", "title": "제목", "created_at": "2026-10-21T00:00:00+09:00", "log": [{"t": "x", "msg": "긴 로그"}],
             "steps": [], "status": "done"}
    assert archive.load_index(tmp_path) == []
    archive.add_index_entry(tmp_path, archive.make_entry(state, tmp_path / "d" / "a1", 3, 99))
    archive.add_index_entry(tmp_path, archive.make_entry({**state, "title": "새 제목"}, tmp_path / "d" / "a1", 3, 99))
    es = archive.load_index(tmp_path)
    assert len(es) == 1
    e = es[0]
    assert (e["id"], e["title"], e["files"], e["bytes"]) == ("a1", "새 제목", 3, 99)
    assert {"created_at", "archived_at", "path", "state"} <= set(e) and "log" not in e["state"]


# ------------------------------------------------------------------ 자동 보관
def test_runner_auto_archives_after_last_step(tmp_path):
    cfg = drive_cfg(tmp_path)
    store, runner, job = run_done(tmp_path, cfg)
    assert job.state["status"] == "done"
    a = job.state["archive"]
    dest = tmp_path / "drive" / "보관" / job.id
    assert a["status"] == "done" and a["path"] == str(dest)
    assert job.dir == dest and job.archived
    assert (dest / "out" / "final.mp4").is_file() and (dest / archive.MANIFEST_NAME).is_file()
    assert not (tmp_path / "work" / job.id).exists()                 # 로컬은 지워짐
    msgs = [x["msg"] for x in job.state["log"]]
    assert "구글 드라이브로 옮기는 중…" in msgs and f"구글 드라이브로 옮김: {dest}" in msgs
    # 드라이브 쪽 state.json 에도 옮김이 적혀 있다
    assert json.loads((dest / "state.json").read_text(encoding="utf-8"))["archive"]["status"] == "done"
    assert [e["id"] for e in archive.load_index(tmp_path / "work")] == [job.id]
    n = len((dest / "state.json").read_text(encoding="utf-8"))
    job.log("더 쓰기")                                                # 보관된 job 은 state.json 을 다시 쓰지 않는다
    assert len((dest / "state.json").read_text(encoding="utf-8")) == n


def test_archive_skipped_when_no_drive(tmp_path):
    cfg = {"enabled": True, "root": str(tmp_path / "없는 드라이브"), "folder": "보관"}
    store, runner, job = run_done(tmp_path, cfg)
    assert job.state["status"] == "done"
    assert job.state["archive"]["status"] == "skipped" and not job.archived
    assert (tmp_path / "work" / job.id / "out" / "final.mp4").is_file()
    assert any("찾지 못" in x["msg"] for x in job.state["log"])
    assert archive.load_index(tmp_path / "work") == []


def test_archive_disabled_does_nothing(tmp_path):
    store, runner, job = run_done(tmp_path, drive_cfg(tmp_path, enabled=False))
    assert "archive" not in job.state and (tmp_path / "work" / job.id).is_dir()


def test_archive_error_keeps_job_done_and_local(tmp_path, monkeypatch):
    real = archive._sha256
    monkeypatch.setattr(archive, "_sha256", lambda p: "bad" if "drive" in p.parts and p.name != "x" else real(p))
    store, runner, job = run_done(tmp_path, drive_cfg(tmp_path))
    assert job.state["status"] == "done" and job.state["archive"]["status"] == "error"
    assert (tmp_path / "work" / job.id / "out" / "final.mp4").is_file() and not job.archived
    assert json.loads((tmp_path / "work" / job.id / "state.json").read_text(encoding="utf-8"))["archive"]["status"] == "error"


def test_delete_local_false_keeps_local_copy(tmp_path):
    store, runner, job = run_done(tmp_path, drive_cfg(tmp_path, delete_local=False))
    assert job.archived and (tmp_path / "work" / job.id / "state.json").is_file()
    assert (tmp_path / "drive" / "보관" / job.id / "state.json").is_file()


# ------------------------------------------------------------------ 불러오기
def test_store_loads_archived_job_online_and_offline(tmp_path):
    store, runner, job = run_done(tmp_path, drive_cfg(tmp_path))
    jid, dest = job.id, job.dir
    s2 = P.JobStore(tmp_path / "work")
    j2 = s2.get(jid)
    assert j2 and j2.archived and j2.dir == dest and not j2.state["offline"]
    assert j2.state["title"] == job.state["title"] and j2.state["steps"]
    # 드라이브가 꺼진 것처럼 이름을 바꾼다 → 색인 요약으로 목록에 보인다
    os.rename(tmp_path / "drive", tmp_path / "drive_off")
    s3 = P.JobStore(tmp_path / "work")
    j3 = s3.get(jid)
    assert j3 and j3.archived and j3.state["offline"] is True and j3.state["log"] == []
    assert j3.state["archive"]["status"] == "done" and j3.state["status"] == "done"
    assert [j.id for j in s3.all()] == [jid]


# ------------------------------------------------------------------ 서버
def client_for(tmp_path):
    app = create_app(work_root=tmp_path / "work", deps=FakeDeps())
    return app


def test_routes_409_for_archived_jobs(tmp_path):
    store, runner, job = run_done(tmp_path, drive_cfg(tmp_path))
    app = client_for(tmp_path)
    with TestClient(app) as c:
        jid = job.id
        st = c.get(f"/api/jobs/{jid}").json()
        assert st["archive"]["status"] == "done" and st["offline"] is False
        assert c.get("/api/jobs").json()[0]["archive"]["status"] == "done"
        assert c.get(f"/media/{jid}/out/final.mp4").status_code == 200
        calls = [("post", f"/api/jobs/{jid}/continue", {}), ("post", f"/api/jobs/{jid}/rerun", {"from": "render"}),
                 ("put", f"/api/jobs/{jid}/script", {"script": {"sentences": []}}), ("post", f"/api/jobs/{jid}/script/refine", None),
                 ("post", f"/api/jobs/{jid}/voice/redo", {"index": 0}), ("put", f"/api/jobs/{jid}/scenes", {"plan": {}}),
                 ("post", f"/api/jobs/{jid}/assets/regenerate", {"file": "x"}),
                 ("post", f"/api/jobs/{jid}/assets/blur", {"file": "x", "boxes": []}),
                 ("post", f"/api/jobs/{jid}/render", None), ("put", f"/api/jobs/{jid}/topic", {"topic": "x"}),
                 ("post", f"/api/jobs/{jid}/archive", None)]
        for m, url, body in calls:
            r = getattr(c, m)(url, **({} if body is None else {"json": body}))
            assert r.status_code == 409, (url, r.status_code, r.text)
        assert "구글 드라이브에 보관된 작업이라 고칠 수 없습니다" in c.post(f"/api/jobs/{jid}/render").json()["detail"]


def test_storage_endpoint(tmp_path):
    with TestClient(client_for(tmp_path)) as c:
        s = c.get("/api/storage").json()
        assert s["enabled"] is False and s["found"] is False       # pytest 기본값
        archive.set_config_override(drive_cfg(tmp_path))
        s = c.get("/api/storage").json()
        assert s["enabled"] and s["found"] and s["root"] == str(tmp_path / "drive")
        assert s["path"] == str(tmp_path / "drive" / "보관") and s["free_bytes"] > 0


def test_manual_archive_endpoint(tmp_path):
    store, runner, job = run_done(tmp_path)                           # 기본(꺼짐) → 로컬에 남음
    assert "archive" not in job.state
    with TestClient(client_for(tmp_path)) as c:
        jid = job.id
        assert c.post(f"/api/jobs/{jid}/archive").status_code == 503      # 드라이브 없음
        archive.set_config_override(drive_cfg(tmp_path, enabled=False))
        assert c.post(f"/api/jobs/{jid}/archive").json()["status"] == "running"
        assert c.app.state.runner.wait_idle(60)
        st = c.get(f"/api/jobs/{jid}").json()
        assert st["status"] == "done" and st["archive"]["status"] == "done"
        assert not (tmp_path / "work" / jid).exists()
        assert c.get(f"/media/{jid}/out/final.mp4").status_code == 200
        assert c.post(f"/api/jobs/{jid}/archive").status_code == 409


def test_manual_archive_requires_done(tmp_path):
    with TestClient(client_for(tmp_path)) as c:
        archive.set_config_override(drive_cfg(tmp_path))
        jid = c.post("/api/jobs", json={"gallery": "baseball_new13", "no": 2101}).json()["id"]
        assert c.app.state.runner.wait_idle(60)                       # read 단계에서 확인 대기
        assert c.post(f"/api/jobs/{jid}/archive").status_code == 409


def test_config_is_off_by_default_and_local_file_turns_it_on(tmp_path, monkeypatch):
    """저장소의 storage.json 은 꺼짐. 이 PC 에서만 켜는 storage.local.json(gitignore)이 있으면 그 값을 덮어 쓴다."""
    import json
    import sys
    from recap_shorts import archive as A
    base, local = tmp_path / "storage.json", tmp_path / "storage.local.json"
    base.write_text(json.dumps({"archive": {"enabled": False, "root": "auto"}}), encoding="utf-8")
    monkeypatch.setattr(A, "CONFIG_PATH", base)
    monkeypatch.setattr(A, "LOCAL_CONFIG_PATH", local)
    monkeypatch.delitem(sys.modules, "pytest")          # 시험 중 강제 꺼짐을 잠깐 풀고 파일 읽기만 본다
    assert A.load_config()["enabled"] is False
    local.write_text(json.dumps({"archive": {"enabled": True}}), encoding="utf-8")
    cfg = A.load_config()
    assert cfg["enabled"] is True and cfg["root"] == "auto" and cfg["delete_local"] is True
    local.write_text("{깨진", encoding="utf-8")
    assert A.load_config()["enabled"] is False           # 못 읽으면 옮기지 않는다
