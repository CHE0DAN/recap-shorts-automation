"""Gemini 이미지 생성(Nano Banana 2 = gemini-3.1-flash-image) — 로컬 이미지 서버의 한도가 찼을 때 대신 쓴다.

POST .../models/{model}:generateContent, generationConfig.responseModalities=["IMAGE"], imageConfig {aspectRatio, imageSize}.
답의 inline_data(base64 PNG/JPEG)를 PNG 로 저장한다. 키는 recap_shorts.voice.gemini.api_key() (출력·저장 안 함).
가격(2026-10-16 가격표, Standard): 1K 한 장 0.067달러 (Pro gemini-3-pro-image 는 0.134달러). 유료 키라 장마다 돈이 든다.
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import requests

from recap_shorts import errors

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.1-flash-image"   # 실제로 쓰는 모델은 settings.model("image")(환경변수 → 설정 화면 → 이것)
ASPECTS = {"landscape": "4:3", "portrait": "3:4", "square": "1:1"}


def generate(prompt: str, out_png: str | Path, aspect: str = "landscape", *, model: str | None = None,
             size: str = "1K", timeout: float = 240.0) -> dict:
    """{"ok","file","seconds","error","size","model"} — 실패는 예외 대신 ok=False."""
    from PIL import Image

    from recap_shorts import settings
    from recap_shorts.voice.gemini import api_key
    model = model or settings.model("image")
    out = Path(out_png)
    res: dict = {"ok": False, "file": str(out), "seconds": 0.0, "error": None, "model": model}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": ASPECTS.get(aspect, aspect), "imageSize": size}}}
    t0 = time.time()
    data = None
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE}/{model}:generateContent", json=body, timeout=timeout,
                              headers={"x-goog-api-key": api_key(), "Content-Type": "application/json"})
        except requests.RequestException as e:
            res.update(error=f"Gemini 이미지 연결 실패({type(e).__name__})", kind=errors.NET, http=None)
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            data = r.json()
            res.pop("kind", None)
            res.pop("http", None)
            res["error"] = None
            break
        try:
            msg = str(r.json().get("error", {}).get("message", ""))[:200]
        except Exception:  # noqa: BLE001
            msg = r.text[:200]
        kind = errors.kind_for_http(r.status_code, msg)
        res.update(error=f"Gemini 이미지 HTTP {r.status_code}: {msg}", kind=kind, http=r.status_code)
        if r.status_code not in (429, 500, 502, 503, 504) or kind == errors.BAD_KEY:   # 키가 틀리면 다시 해도 같다
            break
        time.sleep(5 * (attempt + 1))
    res["seconds"] = round(time.time() - t0, 1)
    if data is None:
        return res
    parts = [p for c in data.get("candidates") or [] for p in (c.get("content") or {}).get("parts") or []]
    blob = next((p.get("inline_data") or p.get("inlineData") for p in parts if (p.get("inline_data") or p.get("inlineData"))), None)
    if not blob:
        fin = (data.get("candidates") or [{}])[0].get("finishReason")
        res["error"] = f"Gemini 이미지 응답에 그림이 없음(finishReason={fin})"
        res.pop("kind", None)
        return res
    try:
        with Image.open(io.BytesIO(base64.b64decode(blob["data"]))) as im:
            im.load()
            out.parent.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").save(out, "PNG")
            res["size"] = list(im.size)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"Gemini 이미지 저장 실패: {type(e).__name__}"
        return res
    res["ok"] = True
    from recap_shorts import usage
    um = data.get("usageMetadata") or {}
    usage.log("image", model=model, seconds=res["seconds"], size=res["size"], aspect=aspect, image_size=size,
              prompt_tokens=um.get("promptTokenCount"), output_tokens=um.get("candidatesTokenCount"))
    return res
