"""배경음악은 영상 파일에 굽지 않는다(config/fx.json bgm_mode, 기본 upload_note).
음악은 업로드할 때 유튜브 앱 '사운드 추가'로 넣는다(편집기에서 섞어 구운 음악은 수익 창출 심사에서 문제가 될 수 있다).

ffmpeg 를 실제로 돌리지 않고, build_mix 가 만드는 명령(입력·필터)을 가로채서 본다. 마지막에 짧은 실제 렌더 1번으로 파일 쓰기를 확인한다.
(bake 로 실제 렌더하는 시험은 test_render.py 의 test_render_with_bgm)"""
import json
import math
import os
import struct
import types
import wave

import pytest

from recap_shorts.render import audio
from recap_shorts.render.render import render
from tests.render.test_render import probe, short_timeline

# 이 명령/필터 문자열은 이 변경 전의 build_mix 가 만든 값을 그대로 옮겨 적은 것이다("bake 는 예전 그대로"의 기준).
GOLD_NOVOICE_BGM = ("[0:a]anull[v];[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=-17.0dB,atrim=0:5.0,"
                    "asetpts=N/SR/TB,afade=t=out:st=4.5:d=0.5[b];"
                    "[v][b]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
GOLD_VOICE_BGM_SFX = (
    "[0:a]loudnorm=I=-15.0:TP=-1.5:LRA=11:measured_I=-20.0:measured_TP=-3:measured_LRA=5:measured_thresh=-30:offset=0.1:"
    "linear=true,aresample=48000,aformat=channel_layouts=stereo,adelay=200|200,apad=whole_dur=5.0,atrim=0:5.0,"
    "asetpts=N/SR/TB[v];"
    "[1:a]aresample=48000,aformat=channel_layouts=stereo,volume=-17.0dB,atrim=0:5.0,asetpts=N/SR/TB,"
    "afade=t=out:st=4.5:d=0.5[b];"
    "[2:a]aresample=48000,aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=c0,volume=-9.50dB,adelay=1000|1000[x0];"
    "[v][b][x0]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.95:level=disabled[a]")


@pytest.fixture
def ff(monkeypatch):
    """ffmpeg·측정을 가짜로 바꾸고, build_mix 가 부른 ffmpeg 명령들을 calls 에 모은다."""
    calls, measured = [], []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    def fake_measure(path):
        measured.append(path)
        return {"input_i": "-20.0", "input_tp": "-3", "input_lra": "5", "input_thresh": "-30", "target_offset": "0.1"}

    monkeypatch.setattr(audio, "ffmpeg_bin", lambda name="ffmpeg": name)
    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    monkeypatch.setattr(audio, "measure_loudness", fake_measure)
    monkeypatch.setattr(audio, "file_peak_db", lambda p: -2.0)
    return types.SimpleNamespace(calls=calls, measured=measured,
                                 filt=lambda: calls[-1][calls[-1].index("-filter_complex") + 1])


@pytest.mark.parametrize("kw", [{}, {"bgm_mode": "upload_note"}, {"bgm_mode": ""}, {"bgm_mode": "nonsense"}])
def test_upload_note_never_mixes_bgm(ff, kw):
    """upload_note(기본·모르는 값 포함): bgm 이 와도 ffmpeg 입력에도 필터에도 들어가지 않는다."""
    info = audio.build_mix(None, "bgm.wav", 5.0, "out.wav", **kw)
    cmd = ff.calls[-1]
    assert "bgm.wav" not in cmd and "-stream_loop" not in cmd
    assert ff.filt() == "[0:a]anull[v];[v]anull[a]"
    assert info["bgm_gain_db"] is None and info["bgm_skipped"] is True and info["bgm_mode"] == "upload_note"
    assert ff.measured == []                       # 배경음악 음량을 재지도 않는다


def test_upload_note_keeps_voice_and_sfx_but_drops_bgm(ff):
    sfx = [{"file": "s.wav", "t": 1.0, "db": -10}]
    info = audio.build_mix("v.wav", "bgm.wav", 5.0, "out.wav", sfx=sfx, voice_offset_s=0.2)
    cmd, f = ff.calls[-1], ff.filt()
    assert "bgm.wav" not in cmd and cmd.count("-i") == 2           # 목소리 + 효과음 1개
    assert "amix=inputs=2:" in f and "[b]" not in f and "afade" not in f
    assert info["sfx_count"] == 1 and ff.measured == ["v.wav"]     # 목소리 음량만 잰다


def test_bake_mixes_bgm_exactly_as_before(ff):
    info = audio.build_mix(None, "bgm.wav", 5.0, "out.wav", bgm_mode="bake")
    cmd = ff.calls[-1]
    assert cmd[cmd.index("-stream_loop"):cmd.index("-stream_loop") + 4] == ["-stream_loop", "-1", "-i", "bgm.wav"]
    assert ff.filt() == GOLD_NOVOICE_BGM
    assert info["bgm_gain_db"] == -17.0 and info["bgm_skipped"] is False and info["bgm_mode"] == "bake"

    sfx = [{"file": "s.wav", "t": 1.0, "db": -10}]
    info = audio.build_mix("v.wav", "bgm.wav", 5.0, "out.wav", sfx=sfx, voice_offset_s=0.2, bgm_mode="bake")
    assert ff.filt() == GOLD_VOICE_BGM_SFX and info["sfx_count"] == 1


def test_no_bgm_is_the_same_in_both_modes(ff):
    for mode in ("upload_note", "bake"):
        audio.build_mix("v.wav", None, 5.0, "out.wav", bgm_mode=mode)
        assert "-stream_loop" not in ff.calls[-1]
    assert ff.calls[-1] == ff.calls[-2]


def test_bgm_mode_config(monkeypatch, tmp_path):
    from recap_shorts.fx import config as fxc
    assert audio.normalize_bgm_mode("bake") == "bake" and audio.normalize_bgm_mode(" Bake ") == "bake"
    assert audio.normalize_bgm_mode(None) == audio.normalize_bgm_mode("mix") == "upload_note"
    assert audio.configured_bgm_mode() == "upload_note"            # 저장소 기본 설정
    assert json.loads(fxc.CONFIG_PATH.read_text(encoding="utf-8"))["bgm_mode"] == "upload_note"
    p = tmp_path / "fx.json"
    p.write_text(json.dumps({"bgm_mode": "bake"}), encoding="utf-8")
    monkeypatch.setattr(fxc, "CONFIG_PATH", p)
    assert audio.configured_bgm_mode() == "bake"
    p.write_text("{}", encoding="utf-8")
    assert audio.configured_bgm_mode() == "upload_note"


def test_upload_sound_text_and_file(tmp_path):
    a = {"bgm": "music/Lofi Night.wav", "bgm_db": -19, "bgm_title": "Lofi Night", "bgm_start_s": 42.5}
    path = audio.write_upload_sound(str(tmp_path), a)
    assert path == str(tmp_path / "upload_sound.txt")
    txt = (tmp_path / "upload_sound.txt").read_text(encoding="utf-8")
    assert "Lofi Night.wav" in txt and "제목: Lofi Night" in txt
    assert "0:42.5" in txt and "42.5초" in txt                    # 곡에서 시작할 위치
    assert "19dB 작게" in txt and "bgm_db -19" in txt              # 크기 힌트
    assert "사운드 추가" in txt and "유튜브 앱" in txt and "들어 있지 않습니다" in txt


def test_upload_sound_start_and_title_are_optional(tmp_path):
    audio.write_upload_sound(str(tmp_path), {"bgm": "C:\\m\\bgm.wav"})                 # bgm_db 도 없음 -> 기본 -22
    txt = (tmp_path / "upload_sound.txt").read_text(encoding="utf-8")
    assert "요청한 곡: bgm.wav\n" in txt and "제목" not in txt                        # 윈도우 경로에서 파일 이름만
    assert "정해 두지 않음" in txt and "22dB 작게" in txt
    audio.write_upload_sound(str(tmp_path), {"bgm": "b.wav", "bgm_start_s": 0})
    assert "처음부터" in (tmp_path / "upload_sound.txt").read_text(encoding="utf-8")


def test_no_bgm_request_writes_nothing(tmp_path):
    for a in ({}, {"bgm": None}, {"bgm": ""}, {"voice": "v.wav", "bgm": None, "bgm_db": -22}):
        assert audio.write_upload_sound(str(tmp_path), a) is None
    assert os.listdir(tmp_path) == []


def _bgm_wav(path):
    with wave.open(str(path), "wb") as w:   # 1초짜리 -> 반복되어 영상 길이에 맞아야 함(bake 일 때)
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / 24000))) for i in range(24000)))


def test_render_upload_note_writes_txt_next_to_video(tmp_path):
    """실제 렌더(3초) 1번: 기본 설정이면 음악은 영상에 안 섞이고 out_mp4 옆에 upload_sound.txt 가 생긴다."""
    _bgm_wav(tmp_path / "bgm.wav")
    out_dir = tmp_path / "out"
    res = render(short_timeline(tmp_path, bgm="bgm.wav"), str(out_dir / "o.mp4"), quiet=True)
    assert res["bgm_gain_db"] is None and res["bgm_skipped"] is True
    assert res["upload_sound"] == str(out_dir / "upload_sound.txt")
    assert "bgm.wav" in (out_dir / "upload_sound.txt").read_text(encoding="utf-8")
    info = probe(str(out_dir / "o.mp4"))
    assert float(info["format"]["duration"]) == pytest.approx(3.0, abs=0.1)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
