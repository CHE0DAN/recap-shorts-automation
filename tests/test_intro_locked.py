"""인트로 화면 잠금 — 인트로 카드는 영상마다 같은 모양이어야 한다.

기준 타임라인으로 그린 인트로 화면 3장을 tests/fixtures/intro_golden/ 에 두고,
지금 설정·코드의 결과와 비교한다. 이 테스트가 깨지면 인트로가 바뀐 것이다.
인트로를 일부러 바꿨다면 tests/fixtures/intro_golden/make.py 로 기준을 다시 만든다.
"""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from recap_shorts.fx import intro as FI
from recap_shorts.render import intro as RI
from recap_shorts.render.compose import Composer

GOLD = Path(__file__).resolve().parent / "fixtures" / "intro_golden"
ROOT = GOLD.parents[2]
FRAMES = (15, 55, 90)


def _load(name):
    return json.loads((GOLD / name).read_text(encoding="utf-8"))


def _config():
    return json.loads((ROOT / "config" / "fx.json").read_text(encoding="utf-8"))


def test_config_intro_block_unchanged():
    """config/fx.json 의 intro 값(설명 '_' 키 제외)이 기준과 같다."""
    now = {k: v for k, v in _config()["intro"].items() if not k.startswith("_")}
    assert now == _load("config_intro.json")


def test_build_intro_unchanged():
    """같은 훅·목소리 타이밍이면 인트로 블록(줄바꿈·튀는 시각·컷 시각·크기)이 기준과 같다."""
    tl = _load("timeline.json")
    want = tl["intro"]
    src = copy.deepcopy(tl)
    src.pop("intro")
    got = FI.build_intro(src, _load("timings.json"), _config(), job_dir=None,
                         voice_offset_s=float(tl["audio"].get("voice_offset_s") or 0.0))
    assert got == want


def test_intro_frames_unchanged():
    """기준 타임라인으로 그린 인트로 화면이 기준 그림과 화소 단위로 같다(글꼴 차이 정도만 허용)."""
    if RI.emoji_image("🤣", 30) is None:
        pytest.skip("컬러 이모지 글꼴이 없는 PC — 기준 그림은 윈도우에서 만듦")
    tl = _load("timeline.json")
    comp = Composer(tl, str(GOLD))
    for i in FRAMES:
        got = np.asarray(comp.frame_image(i).convert("RGB"), dtype=np.int16)
        want = np.asarray(Image.open(GOLD / f"frame_{i:03d}.png").convert("RGB"), dtype=np.int16)
        assert got.shape == want.shape
        diff = np.abs(got - want)
        assert diff.mean() < 0.05 and (diff > 40).mean() < 0.0005, f"인트로 화면이 기준과 다름: 프레임 {i}"
