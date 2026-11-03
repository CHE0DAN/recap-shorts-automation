"""CapCut 초안 공용 계층(recap_shorts.capcut: draft_format / media / desktop / writer) 시험.

실제 CapCut 폴더(%LOCALAPPDATA%\\CapCut)는 읽지도 쓰지도 않는다 — 환경변수를 임시 폴더로 돌리고 capcut_running 을 막아 둔다.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from recap_shorts.capcut import desktop
from recap_shorts.capcut import draft_format as F
from recap_shorts.capcut import media
from recap_shorts.capcut.media import PHOTO_DURATION_US, MediaManager, probe_media
from recap_shorts.capcut.writer import CapCutConfig, folder_name, validate_draft, write_draft

_REAL_CAPCUT_RUNNING = desktop.capcut_running
needs_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe 가 PATH 에 없음")


@pytest.fixture(autouse=True)
def capcut_env(tmp_path, monkeypatch):
    """캡컷 폴더·홈·작업 폴더를 모두 임시 폴더로, 캡컷은 꺼진 것으로."""
    home = tmp_path / "_home"
    local = home / "AppData" / "Local"
    drafts = tmp_path / "_drafts"
    local.mkdir(parents=True)
    drafts.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("RECAP_CAPCUT_DRAFTS_DIR", str(drafts))
    monkeypatch.setenv("RECAP_WORK_ROOT", str(tmp_path / "_work"))
    for name in ("RECAP_CAPCUT_EXE", "RECAP_CAPCUT_PX_PER_SIZE", "RECAP_CAPCUT_APP_VERSION", "RECAP_CAPCUT_NEW_VERSION",
                 "RECAP_CAPCUT_OS", "RECAP_CAPCUT_COPY_MEDIA", "RECAP_CAPCUT_REGISTER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(desktop, "capcut_running", lambda: False)
    return SimpleNamespace(drafts=drafts, local=local, home=home)


# ---------------------------------------------------------------- 도우미
def make_png(path: Path, size=(8, 6)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path)
    return path


def make_wav(path: Path, frames: int = 2000, rate: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)
    return path


def styles_of(mat: dict) -> list[dict]:
    return json.loads(mat["content"])["styles"]


def build_draft(parent: Path, *, name: str = "테스트", overlap: bool = False, text: str = "가나다라마바사",
                runs=((2, 4, "#FF0000"),), font_path: str = "", extra_refs=(), duration_pad: int = 0,
                mutate_styles=None, has_cover: bool = False) -> dict:
    """사진 한 장짜리 영상 트랙 + 글자 트랙 하나인 최소 초안을 parent/name 에 쓴다."""
    parent = parent.resolve()
    stage = parent / name
    stage.mkdir(parents=True)
    mm = MediaManager(stage)
    item = mm.add(make_png(parent / "_src" / "a.png"), "image")
    vm = F.video_material(item.id, item.json_path, kind="photo", duration_us=item.duration_us,
                          width=item.width, height=item.height, name=item.name)
    materials = F.empty_materials()
    materials["videos"].append(vm)
    two = 2 * F.US
    segs = [F.segment(item.id, F.timerange(0, two), source=F.timerange(0, two), extra_refs=list(extra_refs))]
    end = two
    if overlap:   # 앞 세그먼트가 끝나기 전(1초)에 시작
        segs.append(F.segment(item.id, F.timerange(F.US, two), source=F.timerange(0, two)))
        end = F.US + two
    tm = F.text_material(text, size=8, color="#FFFFFF", stroke=("#000000", 0.08), font_path=font_path,
                         color_runs=list(runs) if runs else None)
    if mutate_styles:
        c = json.loads(tm["content"])
        mutate_styles(c["styles"])
        tm["content"] = json.dumps(c, ensure_ascii=False)
    materials["texts"].append(tm)
    tracks = [F.track("video", "그림", segs), F.track("text", "자막", [F.segment(tm["id"], F.timerange(0, two))])]
    draft_id = F.uid()
    content = F.draft_content(draft_id=draft_id, name=name, width=1080, height=1920, fps=30.0, duration_us=end + duration_pad,
                              tracks=tracks, materials=materials, draft_path=stage.as_posix(), os_name="windows",
                              app_version="6.7.0", new_version="140.0.0")
    write_draft(stage, content, name=name, draft_id=draft_id, fold_path=stage.as_posix(), root_path=parent.as_posix(),
                mm=mm, has_cover=has_cover)
    return {"dir": stage, "content": content, "draft_id": draft_id, "mm": mm, "item": item, "text": tm}


# ---------------------------------------------------------------- 독립성
def test_no_foreign_imports():
    """recap_shorts.capcut 공용 계층은 외부 앱 패키지(packages.*, services.*)를 쓰지 않는다."""
    for f in ("draft_format", "media", "desktop", "writer"):
        src = (Path(desktop.__file__).parent / f"{f}.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for n in names:
                assert n.split(".")[0] not in ("packages", "services"), f"{f}.py imports {n}"


# ---------------------------------------------------------------- draft_format: 글자
def test_text_material_single_style_matches_legacy_form():
    """color_runs 없이는 style 하나 그대로."""
    text = "안녕 세상"
    expected = {
        "fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 0.0, 0.0]}}},
        "range": [0, len(text)], "size": 8.5, "bold": True, "italic": False, "underline": False,
        "strokes": [{"content": {"solid": {"alpha": 1.0, "color": [0.0, 0.0, 0.0]}}, "width": 0.08}],
        "font": {"id": "", "path": "C:/f/x.ttf"},
        "shadows": [{"diffuse": 0.025, "alpha": 0.8, "distance": 5.0, "angle": -45.0,
                     "content": {"solid": {"color": [0.0, 0.0, 0.0]}}}],
    }
    kw = dict(size=8.5, color="#FF0000", bold=True, stroke=("#000000", 0.08), font_path="C:/f/x.ttf", shadow={"color": "#000000"})
    plain = F.text_material(text, **kw)
    assert json.loads(plain["content"]) == {"styles": [expected], "text": text}
    assert list(styles_of(plain)[0]) == list(expected)          # 키 순서도 그대로
    for empty in (None, []):
        other = F.text_material(text, color_runs=empty, **kw)
        assert other["content"] == plain["content"]
        assert {k: v for k, v in other.items() if k != "id"} == {k: v for k, v in plain.items() if k != "id"}


def test_text_material_color_runs_cover_text_contiguously():
    text = "가나다라마바사"
    base, red, green = "#FFFFFF", "#FF0000", "#00FF00"
    kw = dict(size=8, color=base, stroke=("#101010", 0.05), font_path="C:/f/x.ttf", shadow={"alpha": 0.5}, bold=True)
    m = F.text_material(text, color_runs=[(5, 6, green), (2, 4, red)], **kw)       # 순서가 섞여 있어도 정렬된다
    st = styles_of(m)
    assert [s["range"] for s in st] == [[0, 2], [2, 4], [4, 5], [5, 6], [6, 7]]
    got = [s["fill"]["content"]["solid"]["color"] for s in st]
    assert got == [F.rgb01(c) for c in (base, red, base, green, base)]
    # 색과 range 만 다르다
    single = styles_of(F.text_material(text, **kw))[0]
    for s in st:
        assert {k: v for k, v in s.items() if k not in ("range", "fill")} == {k: v for k, v in single.items() if k not in ("range", "fill")}
        assert s["fill"]["alpha"] == 1.0 and s["fill"]["content"]["render_type"] == "solid"
    assert json.loads(m["content"])["text"] == text
    assert m["text_color"] == base and m["check_flag"] == F.text_material(text, **kw)["check_flag"]


def test_text_material_color_runs_edges():
    base, red = "#FFFFFF", "#FF0000"
    rgb = F.rgb01
    # 처음부터 끝까지 한 색 -> style 하나
    st = styles_of(F.text_material("abc", size=5, color=base, color_runs=[(0, 3, red)]))
    assert [(s["range"], s["fill"]["content"]["solid"]["color"]) for s in st] == [([0, 3], rgb(red))]
    # 끝에 붙은 구간 / 범위를 넘는 끝 / 역순·빈 구간 무시 / 겹침은 앞 구간 뒤로 잘림
    st = styles_of(F.text_material("abcdef", size=5, color=base, color_runs=[(4, 99, red), (3, 3, red), (5, 2, red)]))
    assert [s["range"] for s in st] == [[0, 4], [4, 6]]
    st = styles_of(F.text_material("abcdef", size=5, color=base, color_runs=[(1, 4, red), (2, 5, "#00FF00")]))
    assert [s["range"] for s in st] == [[0, 1], [1, 4], [4, 5], [5, 6]]
    assert st[2]["fill"]["content"]["solid"]["color"] == rgb("#00FF00")
    # 쓸 수 있는 구간이 하나도 없으면 단일 style, 빈 글자도 깨지지 않는다
    assert [s["range"] for s in styles_of(F.text_material("abc", size=5, color=base, color_runs=[(7, 9, red)]))] == [[0, 3]]
    assert [s["range"] for s in styles_of(F.text_material("", size=5, color=base, color_runs=[(0, 2, red)]))] == [[0, 0]]


def test_text_material_ranges_use_python_len_units():
    text = "ab😀cd"       # 😀 는 파이썬 len 으로 1
    st = styles_of(F.text_material(text, size=5, color="#FFFFFF", color_runs=[(2, 3, "#FF0000")]))
    assert len(text) == 5 and [s["range"] for s in st] == [[0, 2], [2, 3], [3, 5]]


# ---------------------------------------------------------------- MediaManager
def test_media_copy_dedup_unique_names(tmp_path):
    draft = tmp_path / "draft"
    mm = MediaManager(draft)
    a1 = make_png(tmp_path / "x" / "a.png", (8, 6))
    a2 = make_png(tmp_path / "y" / "a.png", (4, 4))        # 이름이 같은 다른 파일
    i1, i1b, i2 = mm.add(a1, "image"), mm.add(a1, "image"), mm.add(a2, "image")
    assert i1 is i1b and len(mm.items("image")) == 2          # 같은 파일은 한 번만
    assert (draft / "assets/image/a.png").is_file() and (draft / "assets/image/a_2.png").is_file()
    assert i1.json_path == (draft / "assets/image/a.png").resolve().as_posix()
    assert i2.json_path.endswith("/assets/image/a_2.png") and i2.name == "a.png"
    assert (i1.width, i1.height, i1.duration_us) == (8, 6, PHOTO_DURATION_US)
    assert (i2.width, i2.height) == (4, 4)
    # 종류가 다르면 같은 이름이어도 별도 폴더
    assert mm.add(a1, "font").json_path.endswith("/assets/font/a.png")
    assert mm.total_bytes() == sum(p.stat().st_size for p in (draft / "assets").rglob("*") if p.is_file())
    assert [m["metetype"] for m in mm.imported_for_meta()] == ["photo", "photo"]       # 폰트는 meta 목록에 없다
    with pytest.raises(FileNotFoundError):
        mm.add(tmp_path / "없음.png", "image")


@needs_ffprobe
def test_media_audio_probe_and_meta(tmp_path):
    mm = MediaManager(tmp_path / "draft")
    w = mm.add(make_wav(tmp_path / "s" / "v.wav", frames=2000, rate=8000), "audio", name="내레이션")
    assert abs(w.duration_us - 250_000) < 5_000 and w.has_audio and w.name == "내레이션"
    assert (tmp_path / "draft/assets/audio/v.wav").is_file()
    meta = mm.imported_for_meta()
    assert meta[0]["metetype"] == "music" and meta[0]["duration_us"] == w.duration_us
    pr = probe_media(w.local)
    assert pr["has_audio"] and not pr["has_video"] and pr["width"] == 0


def test_media_no_copy_and_json_root(tmp_path):
    src = make_png(tmp_path / "s" / "p.png")
    mm = MediaManager(tmp_path / "d1", copy=False)
    inplace = mm.add(src, "image")
    assert inplace.local == src and inplace.json_path == src.resolve().as_posix() and mm.total_bytes() == 0
    assert not (tmp_path / "d1").exists()
    # 다른 PC 루트: 윈도 스타일은 그대로 슬래시로, 유닉스 스타일도 그대로
    win = MediaManager(tmp_path / "d2", json_root="C:/Users/me/draft").add(src, "image")
    assert win.json_path == "C:/Users/me/draft/assets/image/p.png" and (tmp_path / "d2/assets/image/p.png").is_file()
    win2 = MediaManager(tmp_path / "d3", json_root="C:\\Users\\me\\draft").add(src, "image")
    assert win2.json_path == "C:/Users/me/draft/assets/image/p.png"
    nix = MediaManager(tmp_path / "d4", json_root="/home/me/draft").add(src, "image")
    assert nix.json_path == "/home/me/draft/assets/image/p.png"


def test_media_safe_name():
    assert media._safe('a:b?c*.png') == "a_b_c_.png"
    long = media._safe("가" * 120 + ".wav")
    assert len(long) == 80 and long.endswith(".wav")
    assert media._safe(" . ") == "media"


def test_probe_media_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError) as e:
        probe_media(tmp_path / "x.wav")
    assert str(e.value) == "ffprobe 을(를) PATH 에서 찾지 못했습니다."


@needs_ffprobe
def test_probe_media_bad_file(tmp_path):
    bad = tmp_path / "x.wav"
    bad.write_text("이건 소리가 아님", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        probe_media(bad)


# ---------------------------------------------------------------- write_draft / validate_draft
def test_write_draft_files_and_validate_ok(tmp_path):
    r = build_draft(tmp_path / "out", has_cover=True)
    d, content = r["dir"], r["content"]
    for rel in ("draft_content.json", "draft_info.json", "draft_meta_info.json", "attachment_pc_common.json",
                "performance_opt_info.json", "Timelines/project.json", "Timelines/project.json.bak"):
        assert (d / rel).is_file(), rel
    assert json.loads((d / "draft_content.json").read_text(encoding="utf-8")) == content == \
        json.loads((d / "draft_info.json").read_text(encoding="utf-8"))
    tl = [p for p in (d / "Timelines").iterdir() if p.is_dir()]
    assert len(tl) == 1 and (tl[0] / "draft_info.json").is_file() and (tl[0] / "draft_info.json.bak").is_file()
    assert json.loads((tl[0] / "draft_info.json").read_text(encoding="utf-8"))["id"] == tl[0].name
    project = json.loads((d / "Timelines/project.json").read_text(encoding="utf-8"))
    assert project["main_timeline_id"] == tl[0].name and project["id"] == r["draft_id"]
    meta = json.loads((d / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_id"] == r["draft_id"] and meta["draft_cover"] == "draft_cover.jpg" and meta["tm_duration"] == content["duration"]
    assert meta["draft_materials"][0]["value"][0]["file_Path"] == r["item"].json_path
    assert meta["draft_materials"][0]["value"][0]["metetype"] == "photo"
    assert json.loads((d / "attachment_pc_common.json").read_text(encoding="utf-8")) == F.ATTACHMENT_PC_COMMON
    v = validate_draft(d)
    assert v["ok"], v["errors"]
    assert v["tracks"] == 2 and v["segments"] == 2 and v["files_checked"] == 1 and v["duration_us"] == 2 * F.US


def test_write_draft_without_cover_leaves_cover_empty(tmp_path):
    r = build_draft(tmp_path / "out", has_cover=False)
    meta = json.loads((r["dir"] / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_cover"] == ""


def test_validate_draft_catches_overlap(tmp_path):
    v = validate_draft(build_draft(tmp_path / "out", overlap=True)["dir"])
    assert not v["ok"] and any("overlap in track 그림" in e for e in v["errors"])


@pytest.mark.parametrize("mutate", [
    lambda st: st[-1].__setitem__("range", [st[-1]["range"][0], st[-1]["range"][1] - 1]),     # 끝이 len(text) 에 못 미침
    lambda st: st[1].__setitem__("range", [st[1]["range"][0] + 1, st[1]["range"][1]]),        # 앞 구간과 사이가 벌어짐
    lambda st: st[2].__setitem__("range", [st[2]["range"][0] - 1, st[2]["range"][1]]),        # 앞 구간과 겹침
    lambda st: st[0].__setitem__("range", [1, st[0]["range"][1]]),                            # 0 에서 시작하지 않음
    lambda st: st.__setitem__(slice(None), []),                                               # style 이 없음
], ids=["short-end", "gap", "overlap", "start-not-0", "empty"])
def test_validate_draft_catches_broken_text_range(tmp_path, mutate):
    r = build_draft(tmp_path / "out", mutate_styles=mutate)
    v = validate_draft(r["dir"])
    assert not v["ok"] and any(e.startswith("text range mismatch") for e in v["errors"]), v["errors"]


def test_validate_draft_accepts_single_and_multi_style_text(tmp_path):
    assert validate_draft(build_draft(tmp_path / "a", runs=None)["dir"])["ok"]
    assert validate_draft(build_draft(tmp_path / "b", runs=[(0, 1, "#FF0000"), (3, 7, "#00FF00")])["dir"])["ok"]


def test_validate_draft_other_errors(tmp_path):
    v = validate_draft(build_draft(tmp_path / "a", duration_pad=1000)["dir"])
    assert any(e.startswith("duration ") for e in v["errors"])
    v = validate_draft(build_draft(tmp_path / "b", extra_refs=["NOPE"])["dir"])
    assert any("dangling ref NOPE" in e for e in v["errors"])
    r = build_draft(tmp_path / "c")
    Path(r["item"].local).unlink()
    v = validate_draft(r["dir"])
    assert any(e.startswith("missing media file") for e in v["errors"])
    assert validate_draft(r["dir"], check_files=False)["ok"]
    (r["dir"] / "Timelines" / "project.json").unlink()
    assert "missing Timelines/project.json" in validate_draft(r["dir"], check_files=False)["errors"]


def test_validate_draft_checks_font_of_every_style(tmp_path):
    font = tmp_path / "f.ttf"
    font.write_bytes(b"x")
    assert validate_draft(build_draft(tmp_path / "a", font_path=str(font))["dir"])["ok"]
    gone = tmp_path / "없는폰트.ttf"
    v = validate_draft(build_draft(tmp_path / "b", font_path=str(gone))["dir"])
    assert [e for e in v["errors"] if e.startswith("missing font file")] == [f"missing font file {gone}"]     # 같은 경로는 한 번만
    # 둘째 style 에만 없는 폰트가 있어도 잡는다
    def only_second(st):
        st[1]["font"] = {"id": "", "path": str(gone)}
    v = validate_draft(build_draft(tmp_path / "c", font_path=str(font), mutate_styles=only_second)["dir"])
    assert any(e == f"missing font file {gone}" for e in v["errors"])


# ---------------------------------------------------------------- CapCutConfig / folder_name
def test_config_defaults_and_env(monkeypatch):
    c = CapCutConfig.from_env()
    assert c == CapCutConfig() and (c.px_per_size, c.app_version, c.new_version, c.os_name, c.copy_media, c.register) == \
        (5.5, "6.7.0", "140.0.0", "windows", True, True)
    for k, v in {"RECAP_CAPCUT_PX_PER_SIZE": "6.25", "RECAP_CAPCUT_APP_VERSION": "9.1.0", "RECAP_CAPCUT_NEW_VERSION": "150.0.0",
                 "RECAP_CAPCUT_OS": "mac", "RECAP_CAPCUT_COPY_MEDIA": "no", "RECAP_CAPCUT_REGISTER": "0"}.items():
        monkeypatch.setenv(k, v)
    c = CapCutConfig.from_env()
    assert (c.px_per_size, c.app_version, c.new_version, c.os_name, c.copy_media, c.register) == \
        (6.25, "9.1.0", "150.0.0", "mac", False, False)


@pytest.mark.parametrize("raw,want", [("1", True), ("true", True), ("YES", True), ("0", False), ("False", False), ("no", False),
                                       ("", True), ("몰라", True)])
def test_config_bool_values(monkeypatch, raw, want):
    monkeypatch.setenv("RECAP_CAPCUT_COPY_MEDIA", raw)
    assert CapCutConfig.from_env().copy_media is want


def test_config_bad_float_falls_back(monkeypatch):
    monkeypatch.setenv("RECAP_CAPCUT_PX_PER_SIZE", "크게")
    assert CapCutConfig.from_env().px_per_size == 5.5


def test_folder_name():
    assert re.fullmatch(r"abc_\d{4}-\d{6}", folder_name('  ..a/b:c*? "<>|'))
    assert re.fullmatch(r"recap_\d{4}-\d{6}", folder_name("")) and re.fullmatch(r"recap_\d{4}-\d{6}", folder_name("???"))
    long = folder_name("가" * 100)
    assert long.split("_")[0] == "가" * 40


# ---------------------------------------------------------------- desktop: 폴더 찾기·설정
def test_detect_drafts_dir_configured_missing_and_auto(capcut_env, monkeypatch, tmp_path):
    assert desktop.detect_drafts_dir() == capcut_env.drafts
    monkeypatch.setenv("RECAP_CAPCUT_DRAFTS_DIR", str(tmp_path / "없는폴더"))
    assert desktop.detect_drafts_dir() is None                          # 지정했는데 없으면 자동 탐지로 넘어가지 않는다
    monkeypatch.setenv("RECAP_CAPCUT_DRAFTS_DIR", "")
    assert desktop.detect_drafts_dir() is None                          # 자동 탐지 후보도 임시 홈 아래라 아직 없음
    auto = capcut_env.local / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    auto.mkdir(parents=True)
    assert desktop.detect_drafts_dir() == auto and desktop.is_capcut_root(auto)
    assert not desktop.is_capcut_root(tmp_path)
    (tmp_path / "root_meta_info.json").write_text("{}", encoding="utf-8")
    assert desktop.is_capcut_root(tmp_path)


def test_fallback_dir_and_status(capcut_env, tmp_path, monkeypatch):
    fb = desktop.fallback_dir()
    assert fb == tmp_path / "_work" / "_capcut" and fb.is_dir()
    st = desktop.status()
    assert st["fallback_dir"] == str(fb) and st["drafts_dir"] == str(capcut_env.drafts) and st["detected"] and st["configured"]
    monkeypatch.delenv("RECAP_WORK_ROOT")
    assert desktop.work_root() == desktop.REPO_ROOT / "work" and (desktop.REPO_ROOT / "recap_shorts").is_dir()


def test_find_exe_only_accepts_capcut_exe(tmp_path, monkeypatch):
    fake = tmp_path / "CapCut.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("RECAP_CAPCUT_EXE", str(fake))
    assert desktop.find_exe() == fake
    other = tmp_path / "evil.exe"
    other.write_bytes(b"MZ")
    monkeypatch.setenv("RECAP_CAPCUT_EXE", str(other))
    assert desktop.find_exe() != other                                  # 파일 이름이 CapCut.exe 가 아니면 무시


def test_capcut_running_probe(monkeypatch):
    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform="win32"))
    def fake_run(listing: bytes, code: int = 0):
        return lambda *a, **k: SimpleNamespace(stdout=listing, returncode=code)
    monkeypatch.setattr(desktop.subprocess, "run", fake_run(b"CapCut.exe    1234 Console    1   200,000 K\r\n"))
    assert _REAL_CAPCUT_RUNNING() is True
    monkeypatch.setattr(desktop.subprocess, "run", fake_run(b"INFO: No tasks are running which match the specified criteria.\r\n"))
    assert _REAL_CAPCUT_RUNNING() is False
    def boom(*a, **k):
        raise OSError("no tasklist")
    monkeypatch.setattr(desktop.subprocess, "run", boom)
    assert _REAL_CAPCUT_RUNNING() is False                              # 확인 실패는 실행 중 아님
    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform="linux"))
    assert _REAL_CAPCUT_RUNNING() is False


# ---------------------------------------------------------------- desktop: 등록
def _index(drafts: Path, *entries: dict, **extra) -> Path:
    idx = drafts / "root_meta_info.json"
    idx.write_text(json.dumps({"all_draft_store": list(entries), "draft_ids": len(entries), "root_path": str(drafts), **extra},
                              ensure_ascii=False), encoding="utf-8")
    return idx


def test_register_into_index_with_other_drafts(capcut_env):
    drafts = capcut_env.drafts
    old = [{"draft_id": "AAA", "draft_name": "옛날 초안 1", "draft_fold_path": str(drafts / "old1"), "tm_draft_modified": 1},
           {"draft_id": "BBB", "draft_name": "옛날 초안 2", "draft_fold_path": str(drafts / "old2"), "tm_draft_modified": 2}]
    idx = _index(drafts, *old, mystery={"keep": "이건 그대로"})
    before = idx.read_bytes()
    r = build_draft(drafts, name="새 초안")
    res = desktop.register(r["dir"], drafts)
    assert res["registered"] is True and res["draft_id"] == r["draft_id"] and res["index"] == str(idx.resolve())
    got = json.loads(idx.read_text(encoding="utf-8"))
    assert [e["draft_id"] for e in got["all_draft_store"]] == [r["draft_id"], "AAA", "BBB"]      # 새 항목이 맨 앞, 나머지는 그대로
    assert got["all_draft_store"][1:] == old and got["draft_ids"] == 3 and got["mystery"] == {"keep": "이건 그대로"}
    first = got["all_draft_store"][0]
    assert first["draft_name"] == "새 초안" and first["draft_fold_path"] == str(r["dir"].resolve())
    assert first["draft_json_file"].endswith("draft_content.json") and first["tm_duration"] == r["content"]["duration"]
    bak = Path(res["backup"])
    assert re.fullmatch(r"root_meta_info\.json\.\d{8}-\d{6}(-\d+)?\.bak", bak.name) and bak.read_bytes() == before
    # 같은 초안을 다시 올려도 중복되지 않고 맨 앞에 남는다
    res2 = desktop.register(r["dir"], drafts)
    again = json.loads(idx.read_text(encoding="utf-8"))["all_draft_store"]
    assert res2["registered"] and [e["draft_id"] for e in again] == [r["draft_id"], "AAA", "BBB"]
    assert Path(res2["backup"]) != bak and Path(res2["backup"]).is_file()


def test_register_creates_index_when_missing(capcut_env):
    r = build_draft(capcut_env.drafts, name="처음")
    res = desktop.register(r["dir"], capcut_env.drafts)
    assert res["registered"] and res["backup"] is None
    got = json.loads((capcut_env.drafts / "root_meta_info.json").read_text(encoding="utf-8"))
    assert [e["draft_id"] for e in got["all_draft_store"]] == [r["draft_id"]] and got["draft_ids"] == 1
    assert not list(capcut_env.drafts.glob("*.bak")) and not list(capcut_env.drafts.glob("*.tmp"))


def test_register_keeps_other_draft_list_key(capcut_env):
    """목록 키 이름이 다른 버전이면(…draft_store) 그 키에 넣는다."""
    idx = capcut_env.drafts / "root_meta_info.json"
    idx.write_text(json.dumps({"all_draft_store_v2": [{"draft_id": "AAA", "draft_fold_path": "x"}], "draft_ids": 1}), encoding="utf-8")
    r = build_draft(capcut_env.drafts, name="새")
    assert desktop.register(r["dir"], capcut_env.drafts)["registered"]
    got = json.loads(idx.read_text(encoding="utf-8"))
    assert [e["draft_id"] for e in got["all_draft_store_v2"]] == [r["draft_id"], "AAA"] and "all_draft_store" not in got


@pytest.mark.parametrize("raw,why", [
    (b"{not json", "JSON 형식이 깨져 있음"),
    (b"\xff\xfe\x00\x01", "JSON 형식이 깨져 있음"),
    (b"[1, 2]", "최상위가 객체가 아님"),
    (b'{"all_draft_store": {"a": 1}}', "초안 목록이 배열이 아님"),
], ids=["broken-json", "not-utf8", "not-object", "store-not-list"])
def test_register_leaves_unreadable_index_untouched(capcut_env, raw, why):
    idx = capcut_env.drafts / "root_meta_info.json"
    idx.write_bytes(raw)
    r = build_draft(capcut_env.drafts, name="새")
    res = desktop.register(r["dir"], capcut_env.drafts)
    assert res["registered"] is False and res["backup"] is None and res["draft_id"] == r["draft_id"]
    assert "root_meta_info.json" in res["reason"] and why in res["reason"] and "초안 폴더는 만들어져 있습니다" in res["reason"]
    assert idx.read_bytes() == raw                                          # 한 바이트도 안 바뀜
    assert not list(capcut_env.drafts.glob("*.bak")) and not list(capcut_env.drafts.glob("*.tmp"))


def test_register_skipped_while_capcut_runs(capcut_env, monkeypatch):
    monkeypatch.setattr(desktop, "capcut_running", lambda: True)
    idx = _index(capcut_env.drafts, {"draft_id": "AAA", "draft_fold_path": "x"})
    before = idx.read_bytes()
    r = build_draft(capcut_env.drafts, name="새")
    res = desktop.register(r["dir"], capcut_env.drafts)
    assert res["registered"] is False and "캡컷이 실행 중" in res["reason"] and res["backup"] is None
    assert idx.read_bytes() == before and not list(capcut_env.drafts.glob("*.bak"))
    idx.unlink()                                                            # 목록이 없을 때도 만들지 않는다
    assert desktop.register(r["dir"], capcut_env.drafts)["registered"] is False and not idx.exists()


def test_dated_backups_keep_only_newest(capcut_env):
    idx = _index(capcut_env.drafts)
    mine = [desktop._backup_index(idx) for _ in range(desktop.BACKUP_KEEP + 3)]
    left = [p for _, p in desktop._dated_backups(idx)]
    assert len(left) == desktop.BACKUP_KEEP and mine[-1] in left and mine[0] not in left
    legacy, named = idx.with_name("root_meta_info.json.bak"), idx.with_name("root_meta_info.json.내가붙인이름.bak")
    legacy.write_text("a", encoding="utf-8")
    named.write_text("b", encoding="utf-8")
    desktop._backup_index(idx)
    assert legacy.exists() and named.exists()                               # 우리 것이 아닌 백업은 건드리지 않는다


# ---------------------------------------------------------------- desktop: 목록·재연결·zip
def test_list_projects_marks_ours(capcut_env):
    drafts = capcut_env.drafts
    mine = build_draft(drafts, name="내것")["dir"]
    (mine / "recap_export.json").write_text(json.dumps({"job_id": "J1", "stats": {"segments": 7}}), encoding="utf-8")
    build_draft(drafts, name="남의것")
    broken = build_draft(drafts, name="깨짐")["dir"]
    (broken / "recap_export.json").write_text("{깨짐", encoding="utf-8")
    (drafts / "그냥폴더").mkdir()
    (drafts / ".hidden").mkdir()
    rows = {r["folder"]: r for r in desktop.list_projects()}
    assert set(rows) == {"내것", "남의것", "깨짐"}
    assert rows["내것"]["ours"] and rows["내것"]["job_id"] == "J1" and rows["내것"]["segments"] == 7
    assert not rows["남의것"]["ours"] and rows["남의것"]["segments"] is None
    assert not rows["깨짐"]["ours"]
    assert rows["내것"]["duration"] == pytest.approx(2.0) and rows["내것"]["cover"] is None
    assert len(desktop.list_projects(limit=2)) == 2
    assert desktop.list_projects(capcut_env.drafts / "없음") == []


def test_relink_after_moving_draft(tmp_path):
    a = build_draft(tmp_path / "A", name="초안")["dir"]
    b = tmp_path / "B" / "초안"
    shutil.copytree(a, b)
    res = desktop.relink(b)
    assert res["changed"] >= 4 and res["old"] == a.as_posix() and res["new"] == b.resolve().as_posix()
    c = json.loads((b / "draft_content.json").read_text(encoding="utf-8"))
    assert c["path"] == b.resolve().as_posix()
    assert c["materials"]["videos"][0]["path"].startswith(b.resolve().as_posix() + "/assets/")
    meta = json.loads((b / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_fold_path"] == b.resolve().as_posix() and meta["draft_root_path"] == b.resolve().parent.as_posix()
    assert validate_draft(b)["ok"]
    assert desktop.relink(b)["changed"] == 0                                # 이미 맞으면 아무것도 안 바꾼다
    assert (b / "draft_content.json.relink.bak").is_file()


def test_zip_draft(tmp_path):
    d = build_draft(tmp_path / "out", name="초안")["dir"]
    z = desktop.zip_draft(d, tmp_path / "z" / "초안.zip")
    names = set(zipfile.ZipFile(z).namelist())
    assert "초안/draft_content.json" in names and "초안/Timelines/project.json" in names
    assert any(n.startswith("초안/assets/image/") for n in names)
