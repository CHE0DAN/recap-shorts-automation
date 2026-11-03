"""timeline.json -> mp4. 프레임은 ffmpeg 로 파이프."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

from . import audio
from . import layout as L
from .compose import Composer


def _res(base: str, f):
    if not f:
        return None
    return f if os.path.isabs(f) else os.path.join(base, f)


def render(timeline_path: str, out_mp4: str, quiet: bool = False, snap_cuts: bool = False, progress=None,
           bgm_mode: str | None = None) -> dict:
    """bgm_mode: None 이면 config/fx.json 의 bgm_mode(기본 "upload_note": 배경음악을 영상에 섞지 않고 out/upload_sound.txt 만 쓴다).
    "bake" 일 때만 timeline.audio.bgm 을 영상에 섞는다."""
    t0 = time.time()
    timeline_path = os.path.abspath(timeline_path)
    base = os.path.dirname(timeline_path)
    with open(timeline_path, encoding="utf-8") as f:
        tl = json.load(f)
    fps = int(tl.get("fps", L.FPS))
    size = tl.get("size", [L.W, L.H])
    if list(size) != [L.W, L.H]:
        raise ValueError(f"size 는 [1080, 1920] 만 지원합니다: {size}")
    duration = float(tl["duration"])
    n_frames = int(round(duration * fps))
    out_mp4 = os.path.abspath(out_mp4)
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)

    if snap_cuts:
        tl.setdefault("options", {})["snap_captions_to_cuts"] = True
    comp = Composer(tl, base)
    a = tl.get("audio") or {}
    mode = audio.configured_bgm_mode() if bgm_mode is None else audio.normalize_bgm_mode(bgm_mode)
    with tempfile.TemporaryDirectory(prefix="render_audio_") as tmp:
        mix = os.path.join(tmp, "mix.wav")
        t_a = time.time()
        ainfo = audio.build_mix(_res(base, a.get("voice")), _res(base, a.get("bgm")), duration, mix,
                                bgm_db=float(a.get("bgm_db", -22)),
                                sfx_on_cuts=bool(a.get("sfx_on_cuts", False)),
                                voice_offset_s=float(a.get("voice_offset_s", 0.0)), bgm_mode=mode,
                                sfx=[{**e, "file": _res(base, e["file"])} for e in (a.get("sfx") or [])])
        audio_sec = time.time() - t_a

        cmd = [audio.ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{L.W}x{L.H}", "-r", str(fps), "-i", "-",
               "-i", mix,
               "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-t", f"{duration}",
               "-movflags", "+faststart", out_mp4]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        t_v = time.time()
        next_report = 0.1
        try:
            for i in range(n_frames):
                proc.stdin.write(comp.frame_bytes(i))
                if progress and (i + 1) % 15 == 0:
                    progress((i + 1) / n_frames)  # 앱 진행 표시용(0.5초마다)
                if not quiet and (i + 1) / n_frames >= next_report:
                    el = time.time() - t_v
                    print(f"[render] {i + 1}/{n_frames} 프레임 ({(i + 1) / n_frames:.0%}) "
                          f"{(i + 1) / max(el, 1e-6):.1f} fps", file=sys.stderr, flush=True)
                    next_report += 0.1
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode("utf-8", "replace")
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError("ffmpeg 인코딩 실패: " + err[-800:])
    # 배경음악을 요청했지만 영상에 섞지 않았다면(upload_note) 올릴 때 넣는 법을 영상 옆에 적어 둔다. 요청이 없으면 아무것도 쓰지 않는다
    upload_sound = audio.write_upload_sound(os.path.dirname(out_mp4), a) if mode != "bake" else None
    total = time.time() - t0
    result = {"out": out_mp4, "frames": n_frames, "duration": duration,
              "seconds_total": round(total, 2), "seconds_video": round(time.time() - t_v, 2),
              "seconds_audio": round(audio_sec, 2), **ainfo, "upload_sound": upload_sound}
    if not quiet:
        print(f"[render] 완료: {out_mp4} - 렌더 {total:.1f}초 (영상 {duration:.1f}초 분량)",
              file=sys.stderr, flush=True)
    return result
