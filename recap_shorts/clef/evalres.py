"""평가 결과(eval_results.json)를 읽어 질문별 usable 여부를 알려 준다.

형식: {"questions": {"match.A": {"usable": true, "accuracy": .., "wobble": .., ...}, ...}, ...}
파일이 없거나 키가 없으면 usable=False (평가를 통과하지 못한 질문은 쓰지 않는다).
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).with_name("eval_results.json")
ACC_MIN, WOBBLE_MAX = 0.8, 0.15
_override: dict | None = None
_cache: tuple[float, dict] | None = None


def set_results(d: dict | None) -> None:
    """시험용: 파일 대신 이 결과를 쓴다(None 이면 해제)."""
    global _override
    _override = d


def load() -> dict:
    global _cache
    if _override is not None:
        return _override
    try:
        mt = PATH.stat().st_mtime
        if _cache is None or _cache[0] != mt:
            _cache = (mt, json.loads(PATH.read_text(encoding="utf-8")))
        return _cache[1]
    except (OSError, ValueError):
        return {}


def is_usable(key: str) -> bool:
    q = (load().get("questions") or {}).get(key)
    return bool(isinstance(q, dict) and q.get("usable"))


def usable_variants(prefix: str, variants: list[str]) -> list[str]:
    """prefix 질문(예 'match')의 문장 변형(A,B) 중 usable 인 것들."""
    return [v for v in variants if is_usable(f"{prefix}.{v}")]


def threshold(key: str, default: float = 0.5) -> float:
    """질문 key 의 예/아니오 기준값(평가에서 정한 값). 없으면 default."""
    v = ((load().get("questions") or {}).get(key) or {}).get("threshold")
    return float(v) if isinstance(v, (int, float)) else default
