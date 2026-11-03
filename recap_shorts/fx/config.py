"""config/fx.json 읽기 + 작업 옵션(job.options["fx"]) 덮어쓰기."""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "fx.json"

BEAT_LABELS = ["shock", "funny", "sad", "angry", "smug", "awkward", "reveal", "question", "conclusion", "neutral"]


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path | None = None, override: dict | None = None) -> dict:
    """기본 config/fx.json 위에 path 파일(있으면), 그 위에 override 를 덧씌운다."""
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.is_file() else {}
    if path and Path(path).resolve() != CONFIG_PATH.resolve():
        cfg = deep_merge(cfg, json.loads(Path(path).read_text(encoding="utf-8")))
    return deep_merge(cfg, override or {})


def resolve_path(p: str | Path, base: Path = ROOT) -> Path:
    p = Path(p)
    return p if p.is_absolute() else base / p


def enabled(cfg: dict, options: dict | None = None) -> bool:
    """작업 옵션 fx(True/False/dict)가 있으면 그것, 없으면 설정의 enabled."""
    opt = (options or {}).get("fx")
    if opt is None:
        return bool(cfg.get("enabled"))
    if isinstance(opt, dict):
        return bool(opt.get("enabled", True))
    return bool(opt)
