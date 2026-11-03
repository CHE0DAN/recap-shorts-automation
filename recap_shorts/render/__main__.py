"""python -m recap_shorts.render <timeline.json> <out.mp4>"""
import argparse
import json

from .render import render


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.render")
    ap.add_argument("timeline")
    ap.add_argument("out")
    ap.add_argument("--snap-cuts", action="store_true", help="자막 카드 경계를 컷 시각(0.15초 안)에 맞춤")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()
    res = render(args.timeline, args.out, quiet=args.quiet, snap_cuts=args.snap_cuts)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
