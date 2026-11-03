"""모델 파일(recap_shorts/modelfiles.py) 시험: 작은 tar.bz2 를 그 자리에서 만들어 쓴다(네트워크 없음)."""
import io
import tarfile

import pytest

from recap_shorts import modelfiles as M


def make_tar(path, members: dict[str, bytes], top: str | None = None):
    """members: {이름: 내용}. top 을 주면 모든 이름 앞에 "<top>/" 를 붙인다(릴리스 tar.bz2 처럼)."""
    with tarfile.open(path, "w:bz2") as tf:
        for name, data in members.items():
            full = f"{top}/{name}" if top else name
            ti = tarfile.TarInfo(full)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """저장소 models/ 대신 임시 폴더를 쓰게 한다(사용자의 models/ 를 건드리지 않는다)."""
    monkeypatch.setattr(M, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(M, "DOWNLOAD_DIR", tmp_path / "models" / "_download")
    monkeypatch.setattr(M, "_JOBS", {})
    for k in ("A", "B"):
        monkeypatch.delenv(f"RECAP_{k}", raising=False)
    return tmp_path


def test_status_and_ok_when_missing(sandbox, monkeypatch):
    monkeypatch.delenv("RECAP_SENSEVOICE_DIR", raising=False)
    monkeypatch.delenv("RECAP_SUPERTONIC_DIR", raising=False)
    st = M.status()
    assert [s["id"] for s in st] == ["sensevoice", "supertonic"]
    assert all(not s["ok"] for s in st)
    assert st[0]["dir"] == "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"   # 저장소 밖이면 폴더 이름만
    assert st[0]["size_mb"] == 163 and st[1]["size_mb"] == 129


def test_display_dir_inside_repo_is_relative(sandbox, monkeypatch):
    monkeypatch.setattr(M, "REPO_ROOT", sandbox)
    assert M._display_dir("sensevoice") == "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"


def test_env_override_dir_and_display(sandbox, monkeypatch):
    d = sandbox / "outside" / "sv"
    d.mkdir(parents=True)
    (d / "model.int8.onnx").write_bytes(b"x")
    (d / "tokens.txt").write_bytes(b"t")
    monkeypatch.setenv("RECAP_SENSEVOICE_DIR", str(d))
    assert M.model_dir("sensevoice") == d and M.ok("sensevoice")
    assert M.status()[0]["dir"] == "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"   # 밖이면 폴더 이름만


def test_extract_rejects_traversal_and_links(sandbox, tmp_path):
    dest = tmp_path / "out"
    bad = tmp_path / "bad.tar.bz2"
    make_tar(bad, {"../x.txt": b"boom"})
    with pytest.raises(M.ModelError, match="상위 폴더"):
        M._extract(bad, dest)

    link = tmp_path / "link.tar.bz2"
    with tarfile.open(link, "w:bz2") as tf:
        ti = tarfile.TarInfo("inside/link")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "/etc/passwd"
        tf.addfile(ti)
    with pytest.raises(M.ModelError, match="링크"):
        M._extract(link, dest)

    abs_archive = tmp_path / "abs.tar.bz2"
    with tarfile.open(abs_archive, "w:bz2") as tf:
        tf.addfile(tarfile.TarInfo("/abs/file.txt"), io.BytesIO(b"x"))
    with pytest.raises(M.ModelError, match="절대 경로"):
        M._extract(abs_archive, dest)
    assert not (tmp_path / "x.txt").exists()


def test_install_from_local_folder_copies(sandbox):
    src = sandbox / "elsewhere"
    top = src / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    top.mkdir(parents=True)
    (top / "model.int8.onnx").write_bytes(b"model")
    (top / "tokens.txt").write_bytes(b"tokens")
    lines = []
    d = M.install("sensevoice", src_dir=src, progress=lines.append)
    assert d == sandbox / "models" / top.name and M.ok("sensevoice")
    assert any("복사" in x for x in lines)
    assert M.install("sensevoice", src_dir=src, progress=lines.append) == d      # 두 번째는 그냥 넘어감
    assert any("이미 있음" in x for x in lines)


def test_install_from_folder_missing_files(sandbox):
    src = sandbox / "elsewhere"
    (src / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17").mkdir(parents=True)
    with pytest.raises(M.ModelError, match="model.int8.onnx"):
        M.install("sensevoice", src_dir=src, progress=lambda s: None)


def test_install_extracts_good_archive(sandbox, monkeypatch):
    """받기 대신 미리 만든 tar.bz2 를 그 자리에 두고, 풀기·확인·압축 지우기까지 본다."""
    arch = M.DOWNLOAD_DIR / M.spec("supertonic")["url"].rsplit("/", 1)[-1]
    arch.parent.mkdir(parents=True)
    names = M.spec("supertonic")["files"]
    make_tar(arch, {n: b"data" for n in names}, top=M.spec("supertonic")["dir"])

    def fake_download(url, out, size, progress, on_bytes=None):
        out.write_bytes(arch.read_bytes())            # 받은 척
    monkeypatch.setattr(M, "_download", fake_download)
    d = M.install("supertonic", progress=lambda s: None)
    assert d == sandbox / "models" / M.spec("supertonic")["dir"]
    assert all((d / n).is_file() for n in names)
    assert not arch.exists(), "받은 압축은 지운다"


def test_download_rejects_size_mismatch(sandbox):
    part = sandbox / "small.part"
    src = sandbox / "payload.bin"
    src.write_bytes(b"x" * 32)
    with pytest.raises(M.ModelError, match="크기가 다릅니다"):
        M._download(src.as_uri(), part, 10_000_000, lambda s: None)
    assert not part.exists()


def test_unknown_model():
    with pytest.raises(M.ModelError):
        M.spec("nope")


# ---------------------------------------------------------------- 설정 화면의 받기 버튼(start)

def _wait_job(model_id: str, timeout: float = 10.0) -> dict:
    import time
    end = time.time() + timeout
    while time.time() < end:
        job = next(s["job"] for s in M.status() if s["id"] == model_id)
        if job and job["state"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError("받기가 끝나지 않음")


def test_start_downloads_in_background_with_progress(sandbox, monkeypatch):
    monkeypatch.delenv("RECAP_SUPERTONIC_DIR", raising=False)
    s = M.spec("supertonic")
    tar = sandbox / "release.tar.bz2"
    make_tar(tar, {n: b"data" for n in s["files"]}, top=s["dir"])
    seen = []

    def fake_download(url, out, size, progress, on_bytes=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(tar.read_bytes())
        for got in (size // 2, size):
            on_bytes(got, size)
            seen.append(next(x["job"]["state"] for x in M.status() if x["id"] == "supertonic"))
    monkeypatch.setattr(M, "_download", fake_download)
    M.start("supertonic")
    job = _wait_job("supertonic")
    assert job["state"] == "done" and job["got"] == s["size"]
    assert seen == ["downloading", "extracting"]       # 다 받으면 '압축 푸는 중'
    assert M.ok("supertonic")


def test_start_reports_network_error(sandbox, monkeypatch):
    import urllib.error
    monkeypatch.delenv("RECAP_SENSEVOICE_DIR", raising=False)

    def fail(*a, **k):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr(M, "_download", fail)
    M.start("sensevoice")
    job = _wait_job("sensevoice")
    assert job["state"] == "error" and "인터넷 연결" in job["message"]
    assert not M.ok("sensevoice")


def test_start_refuses_env_dir_and_skips_present(sandbox, monkeypatch, tmp_path):
    monkeypatch.setenv("RECAP_SUPERTONIC_DIR", str(tmp_path / "elsewhere"))
    with pytest.raises(M.ModelError, match="RECAP_SUPERTONIC_DIR"):
        M.start("supertonic")
    assert next(s for s in M.status() if s["id"] == "supertonic")["env"] is True
    monkeypatch.setattr(M, "ok", lambda mid: True)
    monkeypatch.setattr(M, "_download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("받으면 안 됨")))
    M.start("sensevoice")                               # 이미 있으면 아무것도 안 함
    assert M._JOBS == {}


def test_setup_cmd_matches_missing_models(monkeypatch):
    def have(*ids):
        monkeypatch.setattr(M, "ok", lambda mid: mid in ids)
    base = M.SETUP_CMD
    assert base == ".venv" + chr(92) + "Scripts" + chr(92) + "python scripts" + chr(92) + "setup_models.py"
    have()
    assert M.setup_cmd() == base + " --all"
    have("sensevoice")
    assert M.setup_cmd() == base + " --supertonic"
    have("supertonic")
    assert M.setup_cmd() == base
    have("sensevoice", "supertonic")
    assert M.setup_cmd() == base


def test_start_error_hides_pc_path(sandbox, monkeypatch):
    """받았는데 파일이 모자라도 화면 문구에 이 PC 의 절대 경로가 나오지 않는다."""
    monkeypatch.delenv("RECAP_SUPERTONIC_DIR", raising=False)
    monkeypatch.setattr(M, "REPO_ROOT", sandbox)
    s = M.spec("supertonic")
    tar = sandbox / "release.tar.bz2"
    make_tar(tar, {s["files"][0]: b"data"}, top=s["dir"])          # 파일 하나만 든 압축

    def fake_download(url, out, size, progress, on_bytes=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(tar.read_bytes())
    monkeypatch.setattr(M, "_download", fake_download)
    M.start("supertonic")
    job = _wait_job("supertonic")
    assert job["state"] == "error" and "갖춰지지 않았습니다" in job["message"]
    assert str(sandbox) not in job["message"] and ":\\" not in job["message"]
    assert job["message"].startswith(f"models/{s['dir']}")
