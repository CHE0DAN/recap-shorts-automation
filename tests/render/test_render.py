import json
import os
import shutil
import subprocess
import wave
import struct
import math

import pytest

from recap_shorts.render.render import render

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "render")


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def short_timeline(tmp_path, bgm=None):
    with open(os.path.join(FIX, "sample_timeline.json"), encoding="utf-8") as f:
        tl = json.load(f)
    tl["duration"] = 3.0
    tl["shots"] = [s for s in tl["shots"] if s["start"] < 3.0]
    tl["shots"][-1]["end"] = 3.0
    tl["captions"] = [c for c in tl["captions"] if c["start"] < 3.0]
    tl["captions"][-1]["end"] = 3.0
    shutil.copytree(os.path.join(FIX, "images"), tmp_path / "images")
    shutil.copy(os.path.join(FIX, "voice.wav"), tmp_path / "voice.wav")
    if bgm:
        tl["audio"]["bgm"] = bgm
    p = tmp_path / "tl.json"
    p.write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_short_render(tmp_path):
    out = str(tmp_path / "o.mp4")
    res = render(short_timeline(tmp_path), out, quiet=True)
    info = probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["r_frame_rate"] == "30/1" and v["pix_fmt"] == "yuv420p"
    assert float(info["format"]["duration"]) == pytest.approx(3.0, abs=0.1)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert res["frames"] == 90
    assert res["upload_sound"] is None and not (tmp_path / "upload_sound.txt").exists()   # 배경음악 요청이 없으면 안내 파일도 없다


def test_render_with_bgm(tmp_path):
    """bgm_mode "bake" = 예전 방식(영상에 섞음). 기본(upload_note)은 tests/render/test_bgm_mode.py."""
    bgm = tmp_path / "bgm.wav"
    with wave.open(str(bgm), "wb") as w:  # 1초짜리 -> 반복되어 영상 길이에 맞아야 함
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / 24000))) for i in range(24000)))
    out = str(tmp_path / "o.mp4")
    res = render(short_timeline(tmp_path, bgm="bgm.wav"), out, quiet=True, bgm_mode="bake")
    assert res["bgm_gain_db"] is not None and res["upload_sound"] is None
    assert not (tmp_path / "upload_sound.txt").exists()
    info = probe(out)
    assert float(info["format"]["duration"]) == pytest.approx(3.0, abs=0.1)
