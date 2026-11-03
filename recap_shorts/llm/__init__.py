"""LLM 어댑터 선택. RECAP_SCRIPT_LLM=gemini_api|agy (기본 gemini_api).
모델: 인자 → 환경변수 RECAP_SCRIPT_MODEL → (gemini_api 면) 설정 화면에서 고른 대본 모델 → 기본."""
from __future__ import annotations

import os


def make_script_llm(kind: str | None = None, model: str | None = None):
    kind = (kind or os.environ.get("RECAP_SCRIPT_LLM") or "gemini_api").strip().lower()
    if kind == "agy":
        from recap_shorts.script.llm import DEFAULT_MODEL, AgyLLM
        return AgyLLM(model or os.environ.get("RECAP_SCRIPT_MODEL") or DEFAULT_MODEL)
    if kind in ("gemini_api", "gemini"):
        from recap_shorts import settings

        from .gemini_api import GeminiApiLLM
        return GeminiApiLLM(model or settings.model("script"))
    raise ValueError(f"알 수 없는 대본 LLM: {kind} (gemini_api | agy)")
