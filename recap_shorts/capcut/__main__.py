"""python -m recap_shorts.capcut <job 폴더> [--drafts-dir 폴더] [--no-register] — job 을 CapCut 초안으로 넘긴다."""
from __future__ import annotations

import argparse
import json
import sys

from .export import export_job


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.capcut")
    ap.add_argument("job_dir", help="work/<job> (timeline.json 이 있는 폴더)")
    ap.add_argument("--drafts-dir", default=None, help="초안을 만들 폴더(기본: CapCut 초안 위치를 찾고, 없으면 work/_capcut)")
    ap.add_argument("--no-register", action="store_true", help="CapCut 프로젝트 목록(root_meta_info.json)에 올리지 않음")
    ap.add_argument("--name", default=None, help="초안 이름(기본: 제목 + 날짜)")
    a = ap.parse_args()
    r = export_job(a.job_dir, drafts_dir=a.drafts_dir, register=False if a.no_register else None, draft_name=a.name)
    print(f"초안: {r['draft_dir']}")
    print(f"목록에 올림: {'예' if r['registered'] else '아니오'} · 구조 검사: {'통과' if r['check']['ok'] else '문제 있음'} · "
          f"{r['seconds']}초 · 미디어 {r['media_bytes'] / 1e6:.1f} MB")
    for x in r["report"]:
        print(f"  [{x['mode']:7s}] {x['element']} {x['count']} — {x['note']}")
    for w in r["warnings"]:
        print("주의:", w, file=sys.stderr)
    if not r["check"]["ok"]:
        print(json.dumps(r["check"], ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
