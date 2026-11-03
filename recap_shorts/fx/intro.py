"""인트로 카드 블록 만들기 (docs/fx_config.md 의 intro 절).

타임라인에 `intro` 를 쓴다 — 렌더(render/intro.py)가 0 ~ t_cut 동안 그림 상자에 흰 카드를 그린다:
  {"style":"card","label":..., "lines":[줄1,줄2], "t_pop":.., "t_cut":.., + 설정의 모양 숫자 전부}
시각은 모두 영상 시계. 목소리가 voice_offset_s 만큼 늦게 나오므로 말 시각에 그만큼을 더한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def count_syllables(text: str) -> int:
    """음절 수 근사: 한글 글자 1개 = 1, 영문·숫자는 글자 2개 = 1(최소 1)."""
    hangul = len(re.findall(r"[가-힣]", text))
    other = len(re.findall(r"[A-Za-z0-9]", text))
    return hangul + other // 2 + (1 if other % 2 and not hangul else 0)


def split_title(text: str) -> list[str]:
    """어절 사이 중 글자 수 기준 가운데에 가장 가까운 곳에서 두 줄로 나눈다. 어절이 하나면 한 줄."""
    words = text.split()
    if len(words) < 2:
        return [" ".join(words), ""] if words else ["", ""]
    total = len(" ".join(words))
    best, best_d = 1, 1e9
    for k in range(1, len(words)):
        left = len(" ".join(words[:k]))
        d = abs(left - total / 2)
        if d < best_d - 1e-9:
            best, best_d = k, d
    return [" ".join(words[:best]), " ".join(words[best:])]


def label_from_job(job_dir: Path, default: str) -> str:
    """카드 머리줄 = 실제 출처. topic.json 의 source_text 첫 줄('디시인사이드 실시간 베스트 갤러리(원본: …) 게시글')에서."""
    try:
        topic = json.loads((Path(job_dir) / "topic.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    m = re.search(r"\]\s*(\S+)\s+(.+?)\s*갤러리", str(topic.get("source_text", ""))[:200])
    if m:
        return f"{m.group(1)} · {m.group(2).strip()}"
    return default


def build_intro(timeline: dict, timings: dict, cfg: dict, *, job_dir: Path | None = None,
                voice_offset_s: float = 0.0) -> dict | None:
    """설정 intro 가 켜져 있고 훅이 있으면 intro 블록, 아니면 None."""
    ic = cfg.get("intro") or {}
    hook = timeline.get("hook")
    if not ic.get("enabled") or not hook:
        return None
    hs = next((s for s in timings["sentences"] if s.get("role") == "hook"), None)
    text = (hook.get("text") or (hs or {}).get("text") or "").strip()
    if not text:
        return None
    fps = int(timeline.get("fps", 30))
    t_cut = float(hook["end"])
    # 훅이 제목과 같은 글이면 맨 위 제목 띠와 같은 곳에서 줄을 나눈다
    tl_lines = [str(x).strip() for x in timeline.get("title_lines") or [] if str(x).strip()]
    squash = lambda s: re.sub(r"[\s.!?…,~]", "", s)
    lines = tl_lines[:2] + [""] * (2 - len(tl_lines[:2])) if tl_lines and squash(" ".join(tl_lines)) == squash(text) else split_title(text)
    n1, n2 = count_syllables(lines[0]), count_syllables(lines[1])
    ratio = n1 / (n1 + n2) if (n1 + n2) else 0.5
    if hs:
        sp0, sp1 = float(hs["start"]) + voice_offset_s, float(hs["end"]) + voice_offset_s
    else:
        sp0, sp1 = voice_offset_s, t_cut
    t_pop = sp0 + ratio * (sp1 - sp0) - float(ic.get("pop_lead_s", 0.15))
    lo = float(ic.get("pop_min_s", 0.6))
    hi = max(lo, t_cut - float(ic.get("pop_before_cut_min_s", 0.5)))
    t_pop = min(hi, max(lo, t_pop))
    t_pop = round(round(t_pop * fps) / fps, 3)       # 프레임 칸에 맞춤
    # label_fixed 가 있으면 모든 영상에 같은 머리줄('🤣 | 유머 • 정보 게시판 >' 꼴),
    # 없으면 실제 출처(디시 갤러리 이름)
    label = timeline.get("intro_label") or ic.get("label_fixed") or (
        label_from_job(job_dir, ic.get("label_default", "")) if job_dir else ic.get("label_default", ""))
    keep = {k: v for k, v in ic.items() if not k.startswith("_") and k not in ("enabled", "label_default", "label_fixed")}
    return {**keep, "style": ic.get("style", "card"), "label": label, "lines": lines,
            "t_pop": t_pop, "t_cut": round(t_cut, 3)}
