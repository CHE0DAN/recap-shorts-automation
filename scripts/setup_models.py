"""로컬 모델 파일 받기: 받아쓰기(SenseVoice) 기본, --supertonic, --all.

    .venv\\Scripts\\python scripts\\setup_models.py            # 받아쓰기 모델만
    .venv\\Scripts\\python scripts\\setup_models.py --supertonic
    .venv\\Scripts\\python scripts\\setup_models.py --all
    .venv\\Scripts\\python scripts\\setup_models.py --from <폴더>   # 받지 않고 그 폴더에서 복사

폴더는 저장소 안 models/ 아래에 생긴다(.gitignore). 이미 있으면 아무것도 하지 않는다.
받아쓰기 모델이 없어도 영상은 만들어지고, 발음 확인·어절 컷만 건너뛴다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from recap_shorts import modelfiles  # noqa: E402


def main() -> int:
    # setup.ps1 이 출력을 파이프로 받으면 한국어 Windows 에서는 cp949 로 쓴다.
    # 인코딩은 그대로 두어 한국어가 읽히게 하고, cp949 에 없는 글자만 ? 로 바꿔 죽지 않게 한다.
    for f in (sys.stdout, sys.stderr):
        if hasattr(f, "reconfigure"):
            f.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="python scripts/setup_models.py")
    ap.add_argument("--supertonic", action="store_true", help="로컬 목소리(Supertonic) 모델도")
    ap.add_argument("--all", action="store_true", help="모든 모델")
    ap.add_argument("--from", dest="src", type=Path, default=None,
                    help="이 폴더에서 복사(폴더 안에 모델 폴더가 있거나, 모델 폴더 자체)")
    a = ap.parse_args()
    ids = [m["id"] for m in modelfiles.MODELS] if a.all else ["sensevoice"]
    if a.supertonic and "supertonic" not in ids:
        ids.append("supertonic")
    print(f"모델 폴더: {modelfiles.MODELS_DIR}")
    print("각 모델 폴더의 LICENSE 를 따릅니다.")
    try:
        for mid in ids:
            modelfiles.install(mid, src_dir=a.src, progress=lambda s: print("  " + s, flush=True))
    except modelfiles.ModelError as e:
        print(f"실패: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
