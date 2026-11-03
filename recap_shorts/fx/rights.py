"""효과음 저작권 점검(경고만, 영상에서 빼지는 않는다).

기록: config/sfx_rights.json — 효과음 id → {level high|medium|low, source, note}. assets_local(커밋 안 함)의 manifest 와
따로 커밋되는 파일이라 manifest 가 없는 PC 에서도 검수 화면 경고가 나온다. **원본 파일 이름만 보고 매긴 판단**이고
소리 지문(Content ID 등)으로 대조한 것이 아니다.

쓰는 곳
 - 검수 단계(pipeline.step_review): 영상에 들어간 효과음 중 medium 이상을 review.json 의 sfx_rights 로 남기고,
   검수 화면(web Review.tsx '확인할 것')이 보여 준다. 승인을 막지 않는다.
 - 고르기 회피(place_sfx): config/fx.json 의 sfx.avoid_rights_risk 가 "high" 면 high 를, "medium" 이면 medium 이상을
   후보에서 뺀다. null(기본)이면 고르기는 예전과 똑같다.
 - 목록 보기: python -m recap_shorts.fx rights [--job 작업폴더] [--json]

기록의 pack(폴더 이름, 지금은 user_meme) 밖의 소리는 점검 대상이 아니다 — 합성음 폴더(assets/sfx)에 boing_01·ding_01 같은
같은 id 가 따로 있기 때문. pack 안인데 기록에 없는 id 는 unknown_level(medium)로 본다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ROOT, load_config, resolve_path

RIGHTS_PATH = ROOT / "config" / "sfx_rights.json"
RANK = {"low": 0, "medium": 1, "high": 2}
LABEL = {"high": "위험 높음", "medium": "주의", "low": "낮음"}
AVOID_VALUES = ("high", "medium")   # sfx.avoid_rights_risk 로 쓸 수 있는 값(null 이면 끔)


def load_rights(path: str | Path | None = None) -> dict:
    """{"pack", "unknown_level", "unknown_note", "items": {id: {level, source, note}}}. 파일이 없거나 깨졌으면 {}(= 점검 안 함)."""
    p = Path(path) if path else RIGHTS_PATH
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        return {}
    items = {}
    for k, v in doc["items"].items():
        if isinstance(v, dict) and v.get("level") in RANK:
            items[str(k)] = {"level": v["level"], "source": str(v.get("source") or ""), "note": str(v.get("note") or "")}
    unk = doc.get("unknown_level")
    return {"pack": doc.get("pack") or None,
            "unknown_level": unk if unk in RANK else "medium",
            "unknown_note": str(doc.get("unknown_note") or "저작권 점검 기록 없음"),
            "basis": str(doc.get("basis") or ""), "items": items}


def event_id(ev: dict) -> str:
    """효과음 이벤트/라이브러리 항목의 id. id 가 없으면(옛 타임라인) 파일 이름에서."""
    return str(ev.get("id") or Path(str(ev.get("file") or "")).stem)


def assess(item_id: str, file: str | None, rights: dict) -> dict | None:
    """{level, note, source, known}. 점검 대상이 아니면(기록 없음·다른 폴더의 소리) None."""
    if not rights:
        return None
    pack = rights.get("pack")
    if pack and file and Path(str(file)).parent.name != pack:
        return None
    e = rights["items"].get(item_id)
    if e:
        return {**e, "known": True}
    return {"level": rights["unknown_level"], "note": rights["unknown_note"], "source": "", "known": False}


def check_events(events: list[dict], rights: dict | None = None) -> list[dict]:
    """영상에 들어간 효과음 이벤트 중 medium 이상 → [{t, id, level, note, source}] (시각 순).
    같은 소리를 여러 번 썼으면 쓴 자리마다 한 줄씩."""
    rights = load_rights() if rights is None else rights
    out = []
    for ev in events or []:
        a = assess(event_id(ev), ev.get("file"), rights)
        if a and RANK[a["level"]] >= RANK["medium"]:
            out.append({"t": round(float(ev.get("t", 0.0)), 3), "id": event_id(ev), "level": a["level"],
                        "note": a["note"], "source": a["source"]})
    return sorted(out, key=lambda r: r["t"])


def warnings_for_timeline(tl: dict, rights: dict | None = None) -> list[dict]:
    return check_events(((tl or {}).get("audio") or {}).get("sfx") or [], rights)


def filter_library(library: list[dict], avoid: str | None, rights: dict | None = None) -> tuple[list[dict], list[str]]:
    """고르기 후보에서 avoid("high"|"medium") 이상의 위험 소리를 뺀다. avoid 가 null 이면 library 를 그대로 돌려준다.
    반환 (남은 library, 보고 문구들)."""
    if not avoid:
        return library, []
    if avoid not in AVOID_VALUES:
        return library, [f"sfx.avoid_rights_risk 값 '{avoid}' 을(를) 몰라 회피를 건너뜀(high | medium | null)"]
    rights = load_rights() if rights is None else rights
    if not rights:
        return library, ["효과음 저작권 기록(config/sfx_rights.json)을 읽지 못해 회피를 건너뜀"]
    cut = RANK[avoid]
    keep, dropped = [], []
    for it in library:
        a = assess(event_id(it), it.get("file"), rights)
        (dropped if a and RANK[a["level"]] >= cut else keep).append(it)
    note = []
    if dropped:
        note.append(f"저작권 위험 회피({avoid} 이상): 효과음 {len(dropped)}개를 후보에서 뺌 — "
                    + ", ".join(sorted(event_id(it) for it in dropped)))
    return keep, note


# ------------------------------------------------------------------ 목록 보기 (python -m recap_shorts.fx rights)
def _manifest_items(d: Path) -> list[dict]:
    try:
        doc = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [it for it in ((doc.get("items", []) if isinstance(doc, dict) else doc) or []) if isinstance(it, dict) and it.get("id")]


def pack_report(rights: dict, libraries: list[Path]) -> dict:
    """꾸러미 폴더들의 manifest 항목마다 위험도. 기록 pack 이름과 폴더 이름이 같은 폴더만 점검 대상."""
    rows, other = [], []
    for d in libraries:
        items = _manifest_items(d)
        if not (rights and rights.get("pack") == d.name):
            other.append({"dir": str(d), "count": len(items)})
            continue
        for it in items:
            a = assess(str(it["id"]), str(d / str(it.get("file", ""))), rights)
            rows.append({"id": str(it["id"]), "type": it.get("type"), "level": a["level"], "known": a["known"],
                         "source": a["source"] or Path(str(it.get("source_file") or "")).stem, "note": a["note"],
                         "dir": str(d)})
    seen = {r["id"] for r in rows}
    missing = sorted(i for i in (rights or {}).get("items", {}) if i not in seen) if rows else []
    rows.sort(key=lambda r: (-RANK[r["level"]], r["id"]))
    return {"rows": rows, "not_checked": other, "not_in_manifest": missing}


def _tty(text: str) -> str:
    """윈도우 cp949 콘솔에서 못 찍는 줄표(—)를 바꾼다."""
    return text.replace("—", "-")


def _print_pack(rep: dict, rights: dict, avoid: str | None) -> None:
    rows = rep["rows"]
    print("효과음 저작권 점검 - 원본 파일 이름만 보고 매긴 것이며 소리를 직접 대조한 것이 아닙니다(config/sfx_rights.json)")
    cnt = {lv: sum(1 for r in rows if r["level"] == lv) for lv in ("high", "medium", "low")}
    print(f"점검한 효과음 {len(rows)}개: high {cnt['high']} / medium {cnt['medium']} / low {cnt['low']}")
    print("고르기 회피 설정 sfx.avoid_rights_risk = " + (f"{avoid} (이 설정이면 고르기에서 빠지는 것 "
          f"{sum(1 for r in rows if avoid in RANK and RANK[r['level']] >= RANK[avoid])}개)" if avoid else "null (끔 - 고르기는 그대로)"))
    for lv in ("high", "medium", "low"):
        sub = [r for r in rows if r["level"] == lv]
        if not sub:
            continue
        print(f"\n[{lv}] {LABEL[lv]} - {len(sub)}개")
        for r in sub:
            tag = "" if r["known"] else "  (기록 없음 -> unknown)"
            print(f"  {r['id']:<14}{(r['source'] or '-'):<28}{_tty(r['note'])}{tag}")
    for o in rep["not_checked"]:
        print(f"\n(점검 대상 아님: {o['dir']} - {o['count']}개, 기록의 pack '{rights.get('pack')}' 폴더가 아님)")
    if rep["not_in_manifest"]:
        print("\n기록에는 있지만 manifest 에 없는 id: " + ", ".join(rep["not_in_manifest"]))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.fx rights",
                                 description="효과음 꾸러미의 저작권 위험도 표, 또는 한 작업이 실제로 쓴 위험 소리")
    ap.add_argument("--job", default=None, help="작업 폴더(work/<job>): 그 작업 timeline.json 에 들어간 medium 이상 효과음을 보여 준다")
    ap.add_argument("--library", action="append", default=None, help="꾸러미 폴더(여러 번 가능, 기본: config/fx.json sfx.libraries)")
    ap.add_argument("--rights", default=None, help="기록 파일(기본 config/sfx_rights.json)")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")   # 윈도우 cp949 콘솔에서 못 찍는 글자가 있어도 멈추지 않게
    except (AttributeError, ValueError):
        pass
    rights = load_rights(a.rights)
    if not rights:
        print("효과음 저작권 기록(config/sfx_rights.json)을 읽지 못했습니다.", file=sys.stderr)
        raise SystemExit(1)
    cfg = load_config()
    avoid = (cfg.get("sfx") or {}).get("avoid_rights_risk")
    if a.job:
        tl_path = Path(a.job) / "timeline.json"
        tl = json.loads(tl_path.read_text(encoding="utf-8"))
        warns = warnings_for_timeline(tl, rights)
        if a.json:
            print(json.dumps(warns, ensure_ascii=False, indent=1))
            return
        n = len(((tl.get("audio") or {}).get("sfx")) or [])
        print(f"{tl_path} - 효과음 {n}개 중 주의 이상 {len(warns)}개 (원본 파일 이름만 보고 매긴 점검)")
        for w in sorted(warns, key=lambda w: (-RANK[w["level"]], w["t"])):
            print(f"  {w['t']:7.2f}초  {w['id']:<12}{w['level']:<8}{_tty(w['note'])}")
        return
    libs = [resolve_path(d) for d in (a.library or (cfg.get("sfx") or {}).get("libraries") or [])]
    rep = pack_report(rights, libs)
    if a.json:
        print(json.dumps({**rep, "avoid_rights_risk": avoid}, ensure_ascii=False, indent=1))
        return
    if not rep["rows"] and not rep["not_checked"]:
        print("점검할 효과음 폴더가 없습니다(--library 로 지정하세요).")
        return
    _print_pack(rep, rights, avoid)
