"""규격표(docs/02_program_design.md 2절)의 띠 위치와 글꼴.

높이 비율은 상수이고, 픽셀은 1080x1920 기준으로 계산한다.
"""
from __future__ import annotations

import os
from functools import lru_cache

from PIL import ImageFont

W, H = 1080, 1920
FPS = 30

# 띠 경계(화면 높이 비율) — 보고서 4.1
TITLE_TOP_PCT, TITLE_BOTTOM_PCT = 0.0, 24.2
IMAGE_TOP_PCT, IMAGE_BOTTOM_PCT = 24.2, 66.4
CAPTION_TOP_PCT, CAPTION_BOTTOM_PCT = 66.4, 75.8
CAPTION_MAX_PX = 1535  # 3줄까지 허용하는 아래 한계(80%)
BLANK_TOP_PCT = 75.8  # 75.8~100% 비움(앱 UI 자리)


def _px(pct: float) -> int:
    return int(round(H * pct / 100.0))


TITLE_Y0, TITLE_Y1 = _px(TITLE_TOP_PCT), _px(TITLE_BOTTOM_PCT)  # 0, 465
IMAGE_Y0, IMAGE_Y1 = _px(IMAGE_TOP_PCT), _px(IMAGE_TOP_PCT) + 810  # 465, 1275
CAPTION_Y0, CAPTION_Y1 = IMAGE_Y1, _px(CAPTION_BOTTOM_PCT)  # 1275, 1455
BLANK_Y0 = CAPTION_Y1
IMAGE_W, IMAGE_H = 1080, 810  # 4:3
IMAGE_RATIO = IMAGE_W / IMAGE_H

SIDE_MARGIN = 60  # 제목·자막 좌우 여백
TEXT_MAX_W = W - 2 * SIDE_MARGIN

TITLE_COLOR_1 = (255, 255, 255)
TITLE_COLOR_2 = (255, 212, 0)  # #FFD400
CAPTION_COLOR = (255, 255, 255)
EMPHASIS_COLOR = (255, 194, 26)  # #FFC21A
OUTLINE_COLOR = (0, 0, 0)
CAPTION_STROKE = 6
CAPTION_SIZE_MAX, CAPTION_SIZE_MIN = 66, 46
CAPTION_LINE_H = 1.25
TITLE_SIZE_MAX, TITLE_SIZE_MIN = 120, 40

HOOK_H = 110
HOOK_MARGIN_X = 40
HOOK_TOP_OFFSET = 24  # 이미지 상자 위에서 안쪽으로
HOOK_SIZE_MAX, HOOK_SIZE_MIN = 62, 30
HOOK_PAD_X = 28
HOOK_Y0 = IMAGE_Y0 + HOOK_TOP_OFFSET
HOOK_Y1 = HOOK_Y0 + HOOK_H

# 영상 폰트: 맑은 고딕 → Pretendard(OFL, assets/fonts 에 동봉). 자막·훅은 ExtraBold(800),
# 고정 제목은 Black(900). 없으면 시스템 글꼴로 물러남.
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "fonts")
FONT_CANDIDATES = [
    os.path.join(_ASSETS, "Pretendard-ExtraBold.otf"),
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\NotoSansKR-VF.ttf",
]
TITLE_FONT_CANDIDATES = [os.path.join(_ASSETS, "Pretendard-Black.otf")] + FONT_CANDIDATES


class FontNotFoundError(RuntimeError):
    pass


def find_font(title: bool = False) -> str:
    for p in (TITLE_FONT_CANDIDATES if title else FONT_CANDIDATES):
        if os.path.exists(p):
            return p
    raise FontNotFoundError(
        "한글 굵은 글꼴을 찾지 못했습니다. 다음 중 하나가 필요합니다: " + ", ".join(FONT_CANDIDATES)
    )


@lru_cache(maxsize=256)
def load_font(size: int, title: bool = False) -> ImageFont.FreeTypeFont:
    path = find_font(title)
    font = ImageFont.truetype(path, int(size))
    if "NotoSansKR" in path:  # 가변 글꼴이면 굵게
        try:
            font.set_variation_by_name("Bold")
        except Exception:
            try:
                font.set_variation_by_axes([700])
            except Exception:
                pass
    return font
