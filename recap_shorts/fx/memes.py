"""짤(밈) 고르기: 어느 문장에 어떤 짤을 얼마 동안 어디에 띄울지 정한다 → 오버레이·전체화면 샷 이벤트.

짤 라이브러리 = 폴더의 manifest.json (스키마는 docs/fx_config.md). 기본은 config 의 memes.library, 설정 화면에서 짤 폴더를
고르면 그 폴더들(분석 꾸러미 포함, docs/library_analysis.md). 없거나 비어 있으면 건너뛰고 note 만 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def scan_images(d: str | Path) -> list[dict]:
    """manifest 없는 짤 폴더(두 단계 하위 폴더까지, 분석기 analyze_meme.list_images 와 같게): 파일 이름을 짤의 이름·뜻으로 쓴다('물음표_으쓱_개구리.png').
    분석(fx/analyze_meme.py)을 하지 않은 폴더라 분위기(beats)는 비워 둔다 — 짤은 뜻으로 고른다(pick_by "fit")."""
    dd = Path(d)
    files = [p for p in sorted(dd.glob("*")) + sorted(dd.glob("*/*")) + sorted(dd.glob("*/*/*"))
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.name.lower() != "contact_sheet.png"]
    out = []
    for p in files:
        rel = p.relative_to(dd)
        name = re.sub(r"[_\-]+", " ", re.sub(r"[\s_\-]*\(?\d+\)?$", "", p.stem)).strip() or p.stem
        out.append({"id": rel.with_suffix("").as_posix(), "file": str(p), "name": name, "meaning": name, "family": "",
                    "beats": [], "transparent": False, "has_text": False})
    return out


def load_folder(d: str | Path) -> tuple[list[dict], str]:
    """폴더 하나: manifest.json 이 있으면 그것, 없으면 파일 이름으로(scan_images)."""
    dd = Path(d)
    if (dd / "manifest.json").is_file():
        return load_library(dd)
    if not dd.is_dir():
        return [], f"짤 폴더 없음({dd}) — 짤은 건너뜀"
    items = scan_images(dd)
    return (items, "") if items else ([], "짤 폴더에 그림이 없음 — 짤은 건너뜀")


def load_libraries(dirs: list[str | Path]) -> tuple[list[dict], list[str]]:
    """여러 폴더를 합친다. id 가 겹치면 뒤 폴더의 것에 'd<번호>_' 를 붙인다."""
    items, notes, seen = [], [], set()
    for n, d in enumerate(dirs):
        got, note = load_folder(d)
        if note:
            notes.append(note)
        for it in got:
            if it["id"] in seen:
                it = {**it, "id": f"d{n}_{it['id']}"}
            seen.add(it["id"])
            items.append(it)
    return items, notes


def load_library(lib_dir: str | Path) -> tuple[list[dict], str]:
    """(항목 목록, 안내문). 파일이 실제로 있는 항목만, file 은 절대경로로 바꿔 돌려준다."""
    d = Path(lib_dir)
    mf = d / "manifest.json"
    if not mf.is_file():
        return [], f"짤 라이브러리 없음({mf}) — 짤은 건너뜀"
    try:
        doc = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [], f"짤 manifest 를 읽지 못함({type(e).__name__}) — 짤은 건너뜀"
    raw = doc.get("items", []) if isinstance(doc, dict) else doc
    items = []
    for it in raw or []:
        f = d / str(it.get("file", ""))
        if not it.get("id") or not f.is_file():
            continue
        items.append({**it, "file": str(f), "beats": [b for b in it.get("beats", [])], "transparent": bool(it.get("transparent"))})
    if not items:
        return [], "짤 라이브러리가 비어 있음 — 짤은 건너뜀"
    return items, ""


def _h(*parts) -> float:
    """결정적 0~1 값(같은 입력 → 같은 값). 무작위 대신 쓴다."""
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def max_for_length(cfg: dict, duration: float | None) -> int:
    """영상 길이별 최대 개수. cfg["max_by_length"] = [[상한초, 개수], ...] (예: [[40,4],[50,5]]), 넘으면 max_cap."""
    base = int(cfg.get("max_per_video", 4))
    table = cfg.get("max_by_length")
    if duration is None or not table:
        return base
    for upto, n in table:
        if duration <= float(upto) + 1e-9:
            return min(int(n), int(cfg.get("max_cap", 6)))
    return int(cfg.get("max_cap", 6))


def effective_max(library: list[dict], cfg: dict, duration: float | None) -> int:
    """길이별 상한과 계열별 상한(max_per_family)을 함께 본 실제 최대 개수 — 라이브러리가 모두 페페(상한 1)면 1."""
    alias = dict(cfg.get("family_alias") or {})
    caps = dict(cfg.get("max_per_family") or {})
    fams = {alias.get(it.get("family") or "", it.get("family") or "") for it in library}
    total = 0
    for f in fams:
        cap = caps.get(f, caps.get("*"))
        if cap is None:
            return max_for_length(cfg, duration)
        total += int(cap)
    return min(max_for_length(cfg, duration), total)


def _span_fn(sentences: list[dict], cfg: dict, duration: float | None):
    """문장 → (짤 시작, 끝). 자리 "end"(기본) = 그 문장이 끝나는 쪽(다음 문장 시작 또는 영상 끝)에 반응으로 붙인다 —
    사실을 말하는 화면을 덮지 않고, 마지막 문장이면 영상이 짤로 끝난다(측정 45%). "start" = 문장 시작(예전 방식)."""
    position = cfg.get("position", "end")
    lead = float(cfg.get("lead_s", 0.0))
    ln_cfg = min(max(float(cfg.get("full_shot_len_s", 1.2)), float(cfg.get("full_shot_min_s", 1.0))),
                 float(cfg.get("full_shot_max_s", 2.5)))
    next_start = {a["index"]: float(b["start"]) for a, b in zip(sentences, sentences[1:])}

    def span(s) -> tuple[float, float]:
        if position != "end":
            return round(float(s["start"]) + lead, 3), float(s["end"])
        stop = next_start.get(s["index"], duration if duration is not None else float(s["end"]))
        st0 = max(float(s["start"]) + float(cfg.get("min_before_s", 0.6)), stop - ln_cfg)
        return round(st0, 3), round(stop, 3)
    return span


def eligible_indices(sentences: list[dict], cfg: dict, duration: float | None = None) -> list[int]:
    """짤을 붙일 수 있는 문장 index — 훅(on_hook 이 꺼져 있으면)·first_after_s 전·0.5초보다 짧은 자리는 빼고,
    end_with_meme 가 꺼져 있으면 마지막 문장도 뺀다(영상이 짤로 끝나지 않게). pick_by "fit" 에서 LLM 에 보여 줄 후보."""
    span = _span_fn(sentences, cfg, duration)
    first_after = float(cfg.get("first_after_s", 0.0))
    last = next((s for s in reversed(sentences) if s.get("role") != "hook"), None)
    out = []
    for s in sentences:
        if s.get("role") == "hook" and not cfg.get("on_hook", False):
            continue
        if last is not None and s["index"] == last["index"] and not cfg.get("end_with_meme"):
            continue
        a, b = span(s)
        if b - a >= 0.5 and a >= first_after - 1e-9:
            out.append(s["index"])
    return out


def pick_memes(sentences: list[dict], library: list[dict], cfg: dict, *, seed: int | str = 0,
               duration: float | None = None, fits: list[dict] | None = None) -> dict:
    """sentences: [{index, role, text, start, end, beat}]. 반환 {"events":[...], "notes":[...]} (시간순).
    fits 가 주어지면(설정 pick_by "fit", meme_fit.fit_memes 결과 [{sentence, meme_id}]) 박자 대신 그 짝만 쓴다."""
    notes: list[str] = []
    if not library:
        return {"events": [], "notes": notes}
    allowed = set(cfg.get("allowed_beats", []))
    prio = list(cfg.get("beat_priority", []))
    gap = float(cfg.get("min_gap_s", 4.0))
    maxn = max_for_length(cfg, duration)
    first_after = float(cfg.get("first_after_s", 0.0))
    on_hook = bool(cfg.get("on_hook", False))
    st = cfg.get("sticker", {})
    span = _span_fn(sentences, cfg, duration)
    order = {f["sentence"]: (n, f["meme_id"]) for n, f in enumerate(fits or [])} if fits is not None else None
    if order is not None and not order:
        notes.append("어울리는 짤 없음 — 짤 없이 감")

    cands = []
    for s in sentences:
        if order is not None:
            if s["index"] not in order:
                continue
        elif s.get("beat") not in allowed:
            continue
        if s.get("role") == "hook" and not on_hook:
            continue
        start, _stop = span(s)
        if _stop - start < 0.5 or start < first_after - 1e-9:
            continue
        if order is not None:
            pr = order[s["index"]][0]
        else:
            pr = prio.index(s["beat"]) if s["beat"] in prio else len(prio)
        cands.append((pr, start, s))
    cands.sort(key=lambda c: (c[0], c[1]))

    used: set[str] = set()
    chosen: list[dict] = []
    # 계열별 상한: 같은 계열 짤은 영상당 정해진 수까지(기본 페페 계열, apu 포함, 1개)
    alias = dict(cfg.get("family_alias") or {})
    fam_cap = dict(cfg.get("max_per_family") or {})
    fam_n: dict[str, int] = {}

    def fam_of(it) -> str:
        f = it.get("family") or ""
        return alias.get(f, f)

    def fam_ok(it) -> bool:
        cap = fam_cap.get(fam_of(it), fam_cap.get("*"))
        return cap is None or fam_n.get(fam_of(it), 0) < int(cap)

    def take(it) -> None:
        fam_n[fam_of(it)] = fam_n.get(fam_of(it), 0) + 1
    last = next((s for s in reversed(sentences) if s.get("role") != "hook"), None)
    if cfg.get("end_with_meme") and last is not None and maxn > 0:
        est, est_stop = span(last)
        pool = [it for it in library if "conclusion" in it["beats"] and fam_ok(it)]
        if est < first_after - 1e-9 or est_stop - est < 0.5:
            notes.append("끝 짤: 마지막 문장이 너무 이르거나 짧아 건너뜀")
        elif not pool:
            notes.append("끝 짤: conclusion 짤이 라이브러리에 없어 건너뜀")
        else:
            it = sorted(pool, key=lambda i: (1 if i.get("has_text") else 0,
                                             0 if (i["transparent"] or not cfg.get("prefer_transparent", True)) else 1,
                                             _h(seed, "end", i["id"])))[0]
            used.add(it["id"])
            take(it)
            chosen.append({"sentence": last["index"], "beat": "conclusion", "start": est, "sent_end": est_stop,
                           "meme_id": it["id"], "file": it["file"], "family": it.get("family"),
                           "transparent": it["transparent"], "name": it.get("name"), "is_end": True})
    for _pr, start, s in cands:
        if len(chosen) >= maxn:
            break
        if any(abs(start - c["start"]) < gap for c in chosen) or s["index"] in {c["sentence"] for c in chosen}:
            continue
        if order is not None:
            pool = [it for it in library if it["id"] == order[s["index"]][1] and it["id"] not in used and fam_ok(it)]
        else:
            pool = [it for it in library if s.get("beat") in it["beats"] and it["id"] not in used and fam_ok(it)]
        if not pool:
            notes.append(f"문장 {s['index']}({s.get('beat')}): 맞는 짤이 없어 건너뜀")
            continue
        near = [c for c in chosen if abs(c["start"] - start) <= gap * 2]
        fam_near = {c.get("family") for c in near}

        def rank(it):   # 글씨 박힌 짤(예: 'FACT' 팻말)은 다른 게 없을 때만 — 글씨 짤이 연달아 두 번 나오면 거슬린다
            return (1 if it.get("has_text") else 0,
                    -float(it.get("r_share") or 0.0),   # 자주 쓴 그림 먼저(manifest r_share)
                    0 if (it["transparent"] or not cfg.get("prefer_transparent", True)) else 1,
                    1 if (cfg.get("avoid_same_family_twice_in_a_row", True) and it.get("family") in fam_near) else 0,
                    _h(seed, s["index"], it["id"]))
        it = sorted(pool, key=rank)[0]
        used.add(it["id"])
        take(it)
        # fit 으로 고른 짤은 짤의 박자로 효과음을 고른다 — 문장 박자가 smug 면 'sus' 소리가 물음표 페페에 붙을 수 있다
        beat = (it.get("beats") or [s.get("beat")])[0] if order is not None else s.get("beat")
        chosen.append({"sentence": s["index"], "beat": beat, "start": start, "sent_end": span(s)[1],
                       "meme_id": it["id"], "file": it["file"], "family": it.get("family"),
                       "transparent": it["transparent"], "name": it.get("name")})
    chosen.sort(key=lambda c: c["start"])

    ratio = float(cfg.get("full_shot_ratio", 0.0))
    anchors = st.get("anchors") or ["box_br"]
    n_sticker = 0
    for n, c in enumerate(chosen):
        full = math.floor((n + 1) * ratio + 1e-9) > math.floor(n * ratio + 1e-9)
        if full:
            c["mode"] = "shot"
            ln = min(max(float(cfg.get("full_shot_len_s", 1.2)), float(cfg.get("full_shot_min_s", 1.0))),
                     float(cfg.get("full_shot_max_s", 2.5)))
            c["end"] = round(min(c["sent_end"], c["start"] + ln), 3)
        else:
            c["mode"] = "sticker"
            c["end"] = round(min(c["sent_end"], c["start"] + float(st.get("max_len_s", 1.8))), 3)
            c["anchor"] = anchors[n_sticker % len(anchors)]
            n_sticker += 1
        del c["sent_end"]
    return {"events": chosen, "notes": notes}


def to_overlay(ev: dict, cfg: dict) -> dict:
    st = cfg.get("sticker", {})
    anim = (st.get("anim_by_beat") or {}).get(ev["beat"], st.get("anim", "pop"))
    return {"kind": "sticker", "file": ev["file"], "start": ev["start"], "end": ev["end"], "anchor": ev["anchor"],
            "size_frac": float(st.get("size_frac", 0.38)), "anim": anim, "beat": ev["beat"], "meme_id": ev["meme_id"],
            **({"meme_src": ev["meme_src"]} if ev.get("meme_src") else {}),
            "pop_s": float(st.get("pop_s", 0.18)), "overshoot": float(st.get("overshoot", 1.12)),
            "fade_s": float(st.get("fade_s", 0.12)), "shake_px": float(st.get("shake_px", 10)),
            "outline_px": int(st.get("outline_px", 6)), "margin_px": int(st.get("margin_px", 24))}


def to_shot(ev: dict, cfg: dict) -> dict:
    st = cfg.get("sticker", {})
    return {"file": ev["file"], "kind": "meme", "start": ev["start"], "end": ev["end"], "motion": "static",
            "focus": [0.5, 0.5], "source_id": ev["meme_id"], "meme_id": ev["meme_id"], "beat": ev["beat"],
            **({"meme_src": ev["meme_src"]} if ev.get("meme_src") else {}),
            "bg": list(cfg.get("full_shot_bg", [20, 20, 20])), "anim": cfg.get("full_shot_anim", "pop"),
            "fit": cfg.get("full_shot_fit", "auto"), "wide_aspect": float(cfg.get("wide_aspect", 1.25)),
            "fit_focus_y": float(cfg.get("full_shot_focus_y", 0.5)),
            **({"margin": int(cfg["full_shot_margin"])} if cfg.get("full_shot_margin") is not None else {}),
            "pop_s": float(st.get("pop_s", 0.18)), "overshoot": float(st.get("overshoot", 1.12))}


def insert_shot(shots: list[dict], new: dict, sliver: float = 0.12) -> list[dict]:
    """전체화면 짤 샷을 샷 목록에 끼운다. 겹치는 샷은 잘라 내고, 0.12초보다 짧은 조각은 짤이 흡수한다."""
    new = dict(new)
    for s in shots:
        if s["end"] <= new["start"] or s["start"] >= new["end"]:
            continue
        if 0 < new["start"] - s["start"] < sliver:
            new["start"] = s["start"]
        if 0 < s["end"] - new["end"] < sliver:
            new["end"] = s["end"]
    out: list[dict] = []
    for s in shots:
        if s["end"] <= new["start"] + 1e-9 or s["start"] >= new["end"] - 1e-9:
            out.append(s)
            continue
        if s["start"] < new["start"] - 1e-9:
            out.append({**s, "end": round(new["start"], 3)})
        if s["end"] > new["end"] + 1e-9:
            right = {**s, "start": round(new["end"], 3)}
            if right.get("motion") != "static":
                right["motion"] = "static"
            out.append(right)
    out.append(new)
    out.sort(key=lambda s: s["start"])
    return out
