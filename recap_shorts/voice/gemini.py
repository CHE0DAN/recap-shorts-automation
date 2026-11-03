"""Gemini 3.8 Flash TTS 엔진 (클라우드, 유료 키·하루 한도 있음).

- 요청 형식은 GeminiTTS 와 같다(Interactions API,
  목소리 이름 + 자연어 말투 `speech_metadata.style`, 출력 24kHz 16bit WAV, SynthID 워터마크 포함).
- 하루 한도(그 키는 하루 100회, 미국 태평양 시간 자정에 초기화)를 같은 키를 쓰는 다른 작업과 나눠 쓴다. 그래서 **내레이션 전체를
  요청 1번으로 합성**하고, Qwen 엔진과 같은 방법(쉼에서 자르고 받아쓰기로 경계 확인)으로 문장별로 나눈다.
- 키: recap_shorts.settings(환경변수 RECAP_GEMINI_API_KEY → config/settings.local.json). 없으면 앱 화면의 '설정'에서 넣으라고 한다.
  키 값은 출력·저장하지 않는다.
"""
from __future__ import annotations

import base64
import io
import time
import wave
from pathlib import Path

import requests

from recap_shorts import errors
from .qwen import _cut_items
from .spoken import to_spoken

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Charon"   # 기본 목소리
DEFAULT_STYLE = ("또렷하고 리듬감 있는 한국어 유튜브 쇼츠 이슈 해설, 친근한 반말 구어체, 조금 빠른 템포, "
                 "발음은 또박또박, 과장된 연기 없이")


def api_key() -> str:
    from recap_shorts import settings
    k = settings.get_key("gemini_api_key")
    if not k:
        raise errors.mark(RuntimeError("Gemini API 키가 없습니다 — 화면 오른쪽 위 '설정'에서 넣으세요"), errors.NO_KEY)
    return k


def request_body(text: str, voice: str, style: str, model: str) -> dict:
    return {"model": model,
            "input": [{"type": "user_input", "content": [{
                "type": "text", "text": text, "annotations": [{"type": "speech_metadata", "style": style}]}]}],
            "response_format": {"type": "audio", "mime_type": "audio/wav"},
            "generation_config": {"speech_config": [{"voice": voice}]}}


def extract_wav(resp: dict) -> bytes:
    audio = [c for st in resp.get("steps", []) if st.get("type") == "model_output"
             for c in st.get("content", []) if c.get("type") == "audio"]
    if not audio:
        raise RuntimeError(f"Gemini TTS 응답에 오디오가 없습니다: {str(resp)[:300]}")
    raw = base64.b64decode(audio[-1]["data"])
    if raw[:4] == b"RIFF":
        return raw
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(raw)
    return buf.getvalue()


def chosen_model() -> str:
    """설정 화면에서 고른 목소리 모델(환경변수 RECAP_TTS_MODEL → 설정 파일 → DEFAULT_MODEL)."""
    from recap_shorts import settings
    return settings.model("tts")


def chosen_voice() -> str:
    """설정 화면에서 고른 Gemini 목소리 이름(없으면 DEFAULT_VOICE)."""
    from recap_shorts import settings
    return settings.gemini_voice()


def call(text: str, out_wav: Path, voice: str | None = None, style: str = DEFAULT_STYLE, model: str | None = None,
         max_attempts: int = 3) -> dict:
    model, voice = model or chosen_model(), voice or chosen_voice()
    key = api_key()
    last, kind, code = "", errors.NET, None
    for k in range(max_attempts):
        t0 = time.time()
        try:
            r = requests.post(URL, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=request_body(text, voice, style, model), timeout=300)
        except requests.RequestException as e:
            last = f"{type(e).__name__}"
            if k + 1 >= max_attempts:
                raise errors.mark(RuntimeError(f"Gemini TTS 연결 실패: {last}"), errors.NET) from None
            time.sleep(5 * (k + 1))
            continue
        if r.status_code == 200:
            data = r.json()
            out_wav.parent.mkdir(parents=True, exist_ok=True)
            wav = extract_wav(data)
            out_wav.write_bytes(wav)
            from recap_shorts import usage
            um = data.get("usage") or data.get("usageMetadata") or {}
            usage.log("gemini_tts", model=model, chars=len(text), audio_sec=round(max(0, len(wav) - 44) / 48000, 2),
                      usage={k: v for k, v in um.items() if isinstance(v, (int, float))} if isinstance(um, dict) else None)
            return {"seconds": round(time.time() - t0, 1), "attempt": k + 1}
        try:
            msg = str(r.json().get("error", {}).get("message", ""))[:300]
        except Exception:  # noqa: BLE001
            msg = r.text[:300]
        last = f"HTTP {r.status_code}: {msg}"
        kind, code = errors.kind_for_http(r.status_code, msg), r.status_code
        if r.status_code == 429 and ("day" in msg.lower() or "daily" in msg.lower()):
            raise errors.mark(RuntimeError("Gemini TTS 하루 한도를 다 썼습니다(미국 태평양 시간 자정 = 한국 오후 4시에 초기화). "
                                           + last), kind, code)
        if r.status_code not in (429, 500, 502, 503, 504) or kind == errors.BAD_KEY:
            raise errors.mark(RuntimeError("Gemini TTS 요청 실패: " + last), kind, code)
        time.sleep(5 * (k + 1))
    raise errors.mark(RuntimeError("Gemini TTS 재시도 실패: " + last), kind, code)   # 마지막 응답(429·5xx) 기준


def synth_sentences(sentences: list[str], out_dir: str | Path, voice: str | None = None, style: str | None = None,
                    model: str | None = None) -> dict:
    """전체 내레이션 1회 합성 → 쉼에서 문장별로 자름(받아쓰기로 경계 다듬기). 반환 꼴은 qwen.synth_sentences 와 같다."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    voice, style, model = voice or chosen_voice(), style or DEFAULT_STYLE, model or chosen_model()
    spoken = [to_spoken(t) for t in sentences]
    # 문장 끝 부호가 없으면 다음 문장과 붙어 읽혀 경계가 단어 중간에 생긴다(Qwen 시험에서 확인) → 합성 입력에만 마침표
    full_text = "\n".join(t if t.rstrip()[-1:] in ".!?…,~" else t.rstrip() + "." for t in spoken)
    full = out / "full.wav"
    info = call(full_text, full, voice, style, model)
    from . import asr as asr_mod
    refine = asr_mod.available()          # 받아쓰기 모델이 없으면 음절 수 비율로만 자른다(영상은 그대로 만들어짐)
    items, cuts = _cut_items(full, sentences, spoken, out / "cut", refine=refine)
    return {"items": items, "meta": {"model": model, "voice": voice, "style": style, "requests": info["attempt"],
                                     "synth_sec": info["seconds"], "cuts": [round(c, 3) for c in cuts],
                                     "refined": refine}}
