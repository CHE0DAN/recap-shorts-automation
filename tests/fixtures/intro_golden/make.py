"""인트로 기준 자료 다시 만들기 — 인트로를 일부러 바꿨을 때만 돌린다.

tests/fixtures/intro_golden/ 의 timeline.json·timings.json 으로 config/fx.json 의 intro 블록과
인트로 화면 3장을 다시 그려 저장한다. 시험(tests/test_intro_locked.py)이 지금 코드의 결과를
이 기준과 화소 단위로 비교하므로, 기준을 새로 만들면 코드·설정이 함께 바뀐 것이어야 한다.

    .venv/Scripts/python tests/fixtures/intro_golden/make.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
FRAMES = (15, 55, 90)          # 0.5초(판이 커진 상태), 1.83초(튄 직후), 3.0초(컷 직전) — 30fps


def config_intro() -> dict:
    cfg = json.loads((ROOT / "config" / "fx.json").read_text(encoding="utf-8"))
    return {k: v for k, v in cfg["intro"].items() if not k.startswith("_")}


def main() -> None:
    from recap_shorts.fx.intro import build_intro
    from recap_shorts.render.compose import Composer

    cfg = json.loads((ROOT / "config" / "fx.json").read_text(encoding="utf-8"))
    tl = json.loads((HERE / "timeline.json").read_text(encoding="utf-8"))
    tm = json.loads((HERE / "timings.json").read_text(encoding="utf-8"))
    (HERE / "config_intro.json").write_text(json.dumps(config_intro(), ensure_ascii=False, indent=1), encoding="utf-8")
    src = dict(tl)
    src.pop("intro", None)
    tl["intro"] = build_intro(src, tm, cfg, job_dir=None, voice_offset_s=float(tl["audio"].get("voice_offset_s") or 0.0))
    (HERE / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    comp = Composer(tl, str(HERE))
    for i in FRAMES:
        comp.frame_image(i).save(HERE / f"frame_{i:03d}.png")
    print("ok", [f"frame_{i:03d}.png" for i in FRAMES])


if __name__ == "__main__":
    main()
