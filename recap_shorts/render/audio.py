"""ffmpeg 로 내레이션(+효과음, bgm_mode 가 "bake" 일 때만 배경음악) 섞기.

배경음악은 기본으로 영상 파일에 굽지 않는다(bgm_mode "upload_note", config/fx.json). 편집기에서 음악을 섞어 구운 쇼츠는
수익 창출 심사에서 문제가 될 수 있어, 음악은 업로드할 때 유튜브 앱의 '사운드 추가'로 넣는다. 타임라인에 audio.bgm 이
있어도 소리는 섞지 않고, 렌더러가 어떤 곡을 어떻게 넣을지 적은 out/upload_sound.txt 를 쓴다(write_upload_sound).
"bake" 는 예전 방식(영상에 섞음) 그대로다.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Optional

BGM_MODES = ("upload_note", "bake")
DEFAULT_BGM_MODE = "upload_note"
UPLOAD_SOUND_NAME = "upload_sound.txt"   # description.txt 옆(out/)에 쓴다

VOICE_LUFS = -15.0  # 전체 음량 -15 LUFS 근처(배경음악은 -22dB 아래라 합쳐도 거의 같다)
FADE_OUT_SEC = 0.5
VOICE_PEAK_DB = -1.5  # 효과음 db 의 기준: 목소리 피크 목표(dBTP). 효과음 db=-10 이면 피크가 -11.5 dBFS


def normalize_bgm_mode(v) -> str:
    """"bake" 만 영상에 굽는다. 비었거나 모르는 값이면 안전한 쪽(upload_note)."""
    return "bake" if str(v or "").strip().lower() == "bake" else DEFAULT_BGM_MODE


def configured_bgm_mode() -> str:
    """config/fx.json 의 bgm_mode. 설정을 못 읽어도 upload_note."""
    try:
        from recap_shorts.fx.config import load_config   # 늦게 불러온다(fx 패키지는 무거움)
        return normalize_bgm_mode(load_config().get("bgm_mode"))
    except Exception:  # noqa: BLE001
        return DEFAULT_BGM_MODE


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    p = shutil.which(name)
    if not p:
        raise RuntimeError(f"{name} 을(를) PATH 에서 찾지 못했습니다.")
    return p


def measure_loudness(path: str) -> dict:
    """loudnorm 1패스 측정값(input_i, input_tp, input_lra, input_thresh, target_offset)."""
    r = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-nostats", "-i", path, "-af",
         f"loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"\{[^{}]*\}", r.stderr, flags=re.S)
    if not m:
        raise RuntimeError("loudnorm 측정 실패: " + r.stderr[-400:])
    return json.loads(m[-1])


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def voice_filter(voice: str) -> str:
    """내레이션 -16 LUFS 로 맞추는 필터(2패스, 선형). 거의 무음이면 그대로."""
    m = measure_loudness(voice)
    i = _num(m.get("input_i"))
    if i is None or i < -60:
        return "anull"
    return (f"loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=11:measured_I={m['input_i']}:"
            f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")


def bgm_gain_db(bgm: str, bgm_db: float = -22.0) -> float:
    """배경음악 측정 음량이 (내레이션 −16 LUFS + bgm_db) 가 되게 하는 gain(dB)."""
    i = _num(measure_loudness(bgm).get("input_i"))
    if i is None:
        return bgm_db
    return (VOICE_LUFS + bgm_db) - i


@lru_cache(maxsize=256)
def file_peak_db(path: str) -> float:
    """파일의 최대 피크(dBFS). 읽지 못하면 0.0."""
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", r.stderr)
    try:
        v = float(m.group(1)) if m else 0.0
    except ValueError:
        v = 0.0
    return v if math.isfinite(v) else 0.0


def sfx_gain_db(path: str, db: float) -> float:
    """효과음 파일 피크가 (목소리 피크 목표 + db) 가 되게 하는 gain(dB)."""
    return VOICE_PEAK_DB + float(db) - file_peak_db(path)


def _delay(sec: float) -> str:
    ms = int(round(float(sec or 0) * 1000))
    return f"adelay={ms}|{ms}," if ms > 0 else ""


def _trim(e: dict) -> str:
    """이벤트에 len_s 가 있으면 그 길이로 자르고 끝을 부드럽게 줄인다(끝 효과음 0.4초)."""
    ln = float(e.get("len_s") or 0)
    if ln <= 0:
        return ""
    fd = min(0.15, ln / 2)
    return f"atrim=0:{ln:.3f},asetpts=N/SR/TB,afade=t=out:st={max(0.0, ln - fd):.3f}:d={fd:.3f},"


def bgm_request(a: dict) -> Optional[dict]:
    """타임라인 audio 가 요청한 배경음악 {file, title, start_s, db}. 요청이 없으면 None.
    title(곡 제목)·start_s(곡에서 시작할 위치, 초)는 있을 때만 쓴다(audio.bgm_title, audio.bgm_start_s)."""
    f = (a or {}).get("bgm")
    if not f:
        return None
    start = _num(a.get("bgm_start_s"))
    db = _num(a.get("bgm_db"))
    return {"file": str(f), "title": str(a.get("bgm_title") or "").strip() or None,
            "start_s": start if start is not None and start >= 0 else None,
            "db": db if db is not None else -22.0}


def _clock(sec: float) -> str:
    m, s = divmod(float(sec), 60.0)
    return f"{int(m)}:{s:04.1f}" if s != int(s) else f"{int(m)}:{int(s):02d}"


def upload_sound_text(req: dict) -> str:
    """out/upload_sound.txt 내용: 어떤 곡을, 곡의 어디부터, 어느 크기로, 업로드할 때 어떻게 넣는지."""
    name = os.path.basename(req["file"].replace("\\", "/"))
    lines = ["[업로드할 때 넣을 배경음악]",
             "이 영상 파일에는 배경음악이 들어 있지 않습니다(설정 bgm_mode = upload_note).",
             "편집기에서 음악을 섞어 만든 쇼츠는 수익 창출이 거절된 사례가 있어, 음악은 올릴 때 유튜브 앱에서 넣습니다.",
             "",
             f"- 요청한 곡: {name}" + (f" (제목: {req['title']})" if req.get("title") else "")]
    if req.get("start_s") is not None:
        st = req["start_s"]
        lines.append("- 곡에서 시작할 위치: " + ("처음부터" if st <= 0 else f"{_clock(st)} ({st:g}초)부터"))
    else:
        lines.append("- 곡에서 시작할 위치: 정해 두지 않음(마음에 드는 부분으로)")
    db = req["db"]
    lines += [f"- 크기(힌트): 목소리보다 {abs(db):g}dB {'작게' if db < 0 else '크게'}(타임라인 bgm_db {db:g}). "
              "목소리가 묻히지 않을 만큼 낮게 두세요.",
              "",
              "넣는 법: 유튜브 앱에서 이 영상을 쇼츠로 올리는 편집 화면의 '사운드 추가'에서 곡을 고르고, "
              "위 시작 위치와 크기에 맞춥니다. 이 파일을 앱에 직접 올리는 것이 아니라 앱의 곡 목록에서 고르는 것이라, "
              "같은 곡이 없으면 비슷한 분위기의 곡을 고르세요."]
    return "\n".join(lines) + "\n"


def write_upload_sound(out_dir: str, a: dict) -> Optional[str]:
    """배경음악 요청이 있으면 out_dir/upload_sound.txt 를 쓰고 경로를 돌려준다. 요청이 없으면 아무것도 쓰지 않는다(None)."""
    req = bgm_request(a)
    if not req:
        return None
    path = os.path.join(out_dir, UPLOAD_SOUND_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write(upload_sound_text(req))
    return path


def build_mix(voice: Optional[str], bgm: Optional[str], duration: float, out_wav: str,
              bgm_db: float = -22.0, sfx_on_cuts: bool = False, sfx: Optional[list] = None,
              voice_offset_s: float = 0.0, bgm_mode: str = DEFAULT_BGM_MODE) -> dict:
    """영상 길이에 맞춘 소리(48kHz 스테레오 wav)를 만든다. 반환: 적용값 기록.

    sfx = [{"file": 절대경로, "t": 시작 초(영상 시계), "db": 목소리 피크 대비 dB}, ...] (선택).
    voice_offset_s > 0 이면 목소리만 그만큼 늦춘다(그림·자막이 말보다 먼저 바뀌는 효과). 효과음 t 는 영상 시계 그대로다.
    bgm_mode: "upload_note"(기본) 이면 bgm 이 주어져도 섞지 않는다(ffmpeg 입력에도 넣지 않음). "bake" 일 때만 섞는다.
    """
    mode = normalize_bgm_mode(bgm_mode)
    info = {"bgm_gain_db": None, "sfx_count": 0, "bgm_mode": mode, "bgm_skipped": False}
    if bgm and mode != "bake":
        info["bgm_skipped"] = True
        bgm = None
    sfx = [e for e in (sfx or []) if e.get("file") and 0 <= float(e.get("t", 0)) < duration]
    if sfx_on_cuts:
        print("[audio] sfx_on_cuts 는 아직 구현되지 않았습니다(무시).")
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error"]
    parts = []
    n = 0
    if voice:
        cmd += ["-i", voice]
        parts.append(f"[{n}:a]{voice_filter(voice)},aresample=48000,"
                     f"aformat=channel_layouts=stereo,{_delay(voice_offset_s)}apad=whole_dur={duration},"
                     f"atrim=0:{duration},asetpts=N/SR/TB[v]")
        n += 1
    else:
        cmd += ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo"]
        parts.append(f"[{n}:a]anull[v]")
        n += 1
    labels = ["[v]"]
    if bgm:
        g = bgm_gain_db(bgm, bgm_db)
        info["bgm_gain_db"] = round(g, 2)
        cmd += ["-stream_loop", "-1", "-i", bgm]
        st = max(0.0, duration - FADE_OUT_SEC)
        parts.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={g}dB,"
                     f"atrim=0:{duration},asetpts=N/SR/TB,"
                     f"afade=t=out:st={st}:d={FADE_OUT_SEC}[b]")
        labels.append("[b]")
        n += 1
    for k, e in enumerate(sfx):
        g = sfx_gain_db(e["file"], float(e.get("db", -12)))
        ms = int(round(float(e["t"]) * 1000))
        cmd += ["-i", e["file"]]
        parts.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=c0,"  # 모노 -> 양쪽 같은 크기(-3dB 없이)
                     f"{_trim(e)}volume={g:.2f}dB,adelay={ms}|{ms}[x{k}]")
        labels.append(f"[x{k}]")
        n += 1
    info["sfx_count"] = len(sfx)
    if sfx:  # 효과음이 있을 때만: 합쳐서 0.95 로 막는다(자동 레벨 보정은 끔 — 목소리 음량이 변하지 않게)
        parts.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,"
                     "alimiter=limit=0.95:level=disabled[a]")
    elif bgm:
        parts.append("[v][b]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        parts.append("[v]anull[a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[a]", "-t", str(duration),
            "-ar", "48000", "-c:a", "pcm_s16le", out_wav]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("오디오 믹스 실패: " + r.stderr[-800:])
    return info
