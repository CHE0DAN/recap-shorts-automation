"""Gemini API(generateContent, REST) 텍스트·비전 클라이언트.

- 주소: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent, 헤더 x-goog-api-key.
- 키는 recap_shorts.voice.gemini.api_key() 에서만 읽고, 출력·로그·저장하지 않는다.
- 429/5xx 는 2회까지 다시 시도한다(5초, 10초 간격). 하루 한도(RESOURCE_EXHAUSTED + day) 메시지는 바로 올린다.
- 대본용 어댑터 GeminiApiLLM 은 script.llm.AgyLLM 과 같은 인터페이스(complete_json, calls)를 가진다.
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import requests

from recap_shorts import errors
from recap_shorts.script.llm import parse_json_loose

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TEXT_MODEL = "gemini-4-argon"
VISION_MODEL = "gemini-3.8-flash"
RETRIES = 2
JSON_RETRIES = 1        # 그림 읽기 답의 JSON 이 깨졌을 때 다시 묻는 횟수
MAX_IMAGE_SIDE = 2400
MAX_INLINE_BYTES = 6_000_000


class GeminiApiError(RuntimeError):
    """kind·http 를 붙여 둔다 — 화면 문구는 recap_shorts.errors.screen_text 가 만든다."""

    def __init__(self, message: str, *, kind: str | None = None, http: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.http = http


def _key() -> str:
    from recap_shorts.voice.gemini import api_key
    return api_key()


def _post(model: str, body: dict, timeout: float = 300.0, sleep=time.sleep) -> dict:
    url = f"{BASE}/{model}:generateContent"
    last = ""
    for attempt in range(RETRIES + 1):
        try:
            r = requests.post(url, headers={"x-goog-api-key": _key(), "Content-Type": "application/json"},
                              json=body, timeout=timeout)
        except requests.RequestException as e:
            last = f"{type(e).__name__}"
            if attempt < RETRIES:
                sleep(5 * (attempt + 1))
                continue
            raise GeminiApiError(f"Gemini API 연결 실패({model}): {last}", kind=errors.NET) from None
        if r.status_code == 200:
            data = r.json()
            um = data.get("usageMetadata") or {}
            from recap_shorts import usage
            usage.log("gemini_text", model=model, prompt_tokens=um.get("promptTokenCount"),
                      output_tokens=um.get("candidatesTokenCount"), thought_tokens=um.get("thoughtsTokenCount"),
                      total_tokens=um.get("totalTokenCount"),
                      images=sum(1 for c in body.get("contents", []) for p in c.get("parts", []) if "inline_data" in p))
            return data
        try:
            msg = str(r.json().get("error", {}).get("message", ""))[:300]
        except Exception:  # noqa: BLE001
            msg = r.text[:300]
        last = f"HTTP {r.status_code}: {msg}"
        kind = errors.kind_for_http(r.status_code, msg)
        if kind == errors.BAD_KEY:                     # 키가 틀리면 다시 시도해도 같다 — 바로 멈춘다
            raise GeminiApiError(f"Gemini API 실패({model}): {last}", kind=kind, http=r.status_code)
        if r.status_code not in (429, 500, 502, 503, 504) or attempt >= RETRIES:
            raise GeminiApiError(f"Gemini API 실패({model}): {last}", kind=kind, http=r.status_code)
        sleep(5 * (attempt + 1))
    raise GeminiApiError(f"Gemini API 실패({model}): {last}")


def _text_of(resp: dict) -> str:
    cands = resp.get("candidates") or []
    if not cands:
        fb = resp.get("promptFeedback") or {}
        raise GeminiApiError(f"Gemini 응답에 후보가 없음: {str(fb)[:200]}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought") and "text" in p)
    if not text.strip():
        raise GeminiApiError(f"Gemini 응답이 비어 있음(finishReason={cands[0].get('finishReason')})")
    return text


def generate_text(prompt: str, model: str = TEXT_MODEL, json: bool = True, *, temperature: float | None = None,
                  timeout: float = 300.0, thinking: str | None = None) -> dict | str:
    """json=True → 모델 답에서 JSON 객체를 꺼내 dict 로, False → 문자열.
    thinking = Gemini 3 의 thinkingLevel("low" 등). None 이면 모델 기본값(생각을 많이 해서 느릴 수 있음)."""
    cfg: dict = {}
    if json:
        cfg["responseMimeType"] = "application/json"
    if temperature is not None:
        cfg["temperature"] = temperature
    if thinking:
        cfg["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if cfg:
        body["generationConfig"] = cfg
    text = _text_of(_post(model, body, timeout))
    return parse_json_loose(text) if json else text.strip()


def _image_part(img) -> dict:
    """경로·바이트·PIL 이미지 → inline_data. 너무 크면 줄여 JPEG 로."""
    from PIL import Image
    if isinstance(img, (str, Path)):
        im = Image.open(img)
    elif isinstance(img, (bytes, bytearray)):
        im = Image.open(io.BytesIO(img))
    else:
        im = img
    im.load()
    im = im.convert("RGB")
    s = min(1.0, MAX_IMAGE_SIDE / max(im.size))
    if s < 1.0:
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    mime = "image/png"
    if buf.tell() > MAX_INLINE_BYTES:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        mime = "image/jpeg"
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(buf.getvalue()).decode("ascii")}}


def read_images(images: list, instruction: str, model: str = VISION_MODEL, *, json: bool = False,
                timeout: float = 300.0, thinking: str | None = None) -> dict | str:
    """이미지(들) + 지시문 → 모델 답. 이미지는 지시문 앞에 순서대로 붙는다.
    thinking = Gemini 3 의 thinkingLevel("low" 등, generate_text 와 같음). None 이면 모델 기본값.
    json=True 인데 답의 JSON 이 깨졌으면 한 번 더 묻는다 — 긴 글을 옮겨 적을 때 가끔 깨지고, 다시 물으면 대개 제대로 온다."""
    parts = [_image_part(i) for i in images] + [{"text": instruction}]
    cfg: dict = {"responseMimeType": "application/json"} if json else {}
    if thinking:
        cfg["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"role": "user", "parts": parts}]}
    if cfg:
        body["generationConfig"] = cfg
    for attempt in range(JSON_RETRIES + 1):
        text = _text_of(_post(model, body, timeout))
        if not json:
            return text.strip()
        try:
            return parse_json_loose(text)
        except ValueError:
            if attempt >= JSON_RETRIES:
                raise


class GeminiApiLLM:
    """script.generate_script 가 쓰는 어댑터(AgyLLM 과 같은 모양)."""
    name = "gemini_api"

    def __init__(self, model: str = TEXT_MODEL, *, timeout: float = 300.0, max_calls: int | None = None):
        self.model, self.timeout, self.max_calls = model, timeout, max_calls
        self.calls: list[dict] = []

    def complete_json(self, prompt: str) -> dict:
        if self.max_calls is not None and len(self.calls) >= self.max_calls:
            raise GeminiApiError(f"Gemini 호출 한도 {self.max_calls}회 도달")
        t0 = time.time()
        try:
            out = generate_text(prompt, self.model, json=True, timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            self.calls.append({"seconds": round(time.time() - t0, 1), "ok": False, "error": str(e)[:300],
                               "model": self.model, "prompt_chars": len(prompt)})
            raise
        self.calls.append({"seconds": round(time.time() - t0, 1), "ok": True, "model": self.model,
                           "prompt_chars": len(prompt)})
        return out
