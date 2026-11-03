"""3.3 자료 검사, 3.4 영상 점검, 3.5 목소리 확인. 모두 힌트이며 사람이 최종 결정한다."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import client as c
from . import evalres, questions as Q

log = logging.getLogger("recap.clef.inspect")
KEYS_BY_KIND = {"capture": ["face", "personal_text", "text_or_logo"],
                "ai": ["text_or_logo", "real_person_like", "face"]}
WIDTH, FPS, MAX_SECONDS = 360, 10, 58.0
WATCH_TIMEOUT = 60.0


def _mean_noul(got: dict, prefix: str, vs: list[str]) -> float:
    return sum(float(got[f"{prefix}_{v}"].value) for v in vs) / len(vs)


def inspect_image(path, kind: str = "capture") -> dict | None:
    """-> {face, personal_text, text_or_logo, real_person_like} 확률. 묻지 않았거나 평가 미통과인 칸은 None.
    kind: "capture"(SNS 캡처: 얼굴·아이디 중심) | "ai"(AI 그림: 글자·로고·실존 인물). 쓸 수 있는 질문이 없거나 키 없음이면 None."""
    if kind not in KEYS_BY_KIND:
        raise ValueError("kind must be 'capture' or 'ai'")
    if not c.configured():
        return None
    use = {k: evalres.usable_variants(f"inspect.{k}", Q.VARIANTS) for k in KEYS_BY_KIND[kind]}
    use = {k: vs for k, vs in use.items() if vs}
    if not use:
        return None
    qs = {f"{k}_{v}": Q.inspect_q(k, v) for k, vs in use.items() for v in vs}
    try:
        got = c.ask(qs, state=Q.INSPECT_STATE, images=[path])
    except c.ClefError as e:
        log.warning("inspect failed for %s: %s", Path(str(path)).name, e)
        return None
    out = {k: None for k in Q.INSPECT_KEYS}
    for k, vs in use.items():
        out[k] = round(_mean_noul(got, k, vs), 3)
    return out


def small_copy(video: Path, out: Path) -> Path:
    ff = shutil.which("ffmpeg")
    if not ff:
        raise c.ClefError("ffmpeg not found")
    cmd = [ff, "-y", "-v", "error", "-t", f"{MAX_SECONDS:g}", "-i", str(video), "-vf", f"scale={WIDTH}:-2,fps={FPS}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "64k", "-ac", "1", str(out)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not out.is_file():
        raise c.ClefError("ffmpeg could not make the small copy")
    return out


def watch_video(mp4, topic_line: str = "") -> dict | None:
    """-> {opens_finished, face, music, narration, caption_cut, topic_match|None, tokens, neurons}. 확률 힌트
    (같은 영상도 질문에 따라 0.26~0.42 흔들렸음 → 경고 표시용, 자동 판단 금지). 키 없음·실패면 None.
    이 질문들은 평가 재료(정답 있는 영상)가 없어 eval_results 로 걸러지지 않는다: hint_only=True."""
    mp4 = Path(mp4)
    if not c.configured() or not mp4.is_file():
        return None
    tmp = Path(tempfile.mkdtemp(prefix="clefwatch_"))
    try:
        clip = small_copy(mp4, tmp / "watch_copy.mp4")
        topic_line = (topic_line or "").strip()
        state = "A short vertical video with a title band and captions added by an editor." + (
            f" Its topic, in Korean: {topic_line}." if topic_line else "")
        usage: dict = {}
        got = c.ask(Q.watch_questions(bool(topic_line)), state=state, videos=[clip], model="clef-omni",
                    timeout=WATCH_TIMEOUT, usage=usage)
        out = {k: round(float(a.value), 3) for k, a in got.items()}
        out.setdefault("topic_match", None)
        return {**out, "tokens": usage.get("input_tokens"), "neurons": usage.get("neurons"), "hint_only": True}
    except c.ClefError as e:
        log.warning("video not watched: %s", e)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def voice_says(wav, sentence: str, state_extra: str = "") -> float | None:
    """3.5(시험용): 이 소리가 sentence 를 또렷이 말하나 → 예 확률(usable 변형 평균). 평가 미통과·키 없음·실패면 None."""
    vs = evalres.usable_variants("voice", Q.VARIANTS)
    if not vs or not c.configured():
        return None
    qs = {f"v_{v}": Q.voice_q(v, sentence) for v in vs}
    try:
        got = c.ask(qs, state=Q.VOICE_STATE + state_extra, audio=[wav])
    except c.ClefError as e:
        log.warning("voice check failed: %s", e)
        return None
    return round(_mean_noul(got, "v", vs), 3)
