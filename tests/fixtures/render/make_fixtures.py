"""시험 자료 생성기: 직접 그린 이미지 8장 + 가짜 내레이션 wav + sample_timeline.json.

실행: .venv\Scripts\python.exe tests\fixtures\render\make_fixtures.py
"""
import json
import math
import os
import struct
import sys
import wave

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from recap_shorts.render.captions import make_cards, syllables  # noqa: E402

SIZES = [(1600, 1200), (1600, 1200), (1920, 1080), (1200, 1600), (1600, 1200), (2000, 1000), (1600, 1200), (1080, 1080)]
PALETTES = [((20, 60, 160), (240, 120, 40)), ((10, 120, 80), (240, 230, 90)), ((140, 20, 90), (30, 180, 230)),
            ((60, 60, 70), (230, 90, 90)), ((200, 80, 20), (40, 40, 160)), ((20, 100, 140), (230, 200, 230)),
            ((90, 40, 150), (120, 230, 120)), ((160, 140, 20), (20, 60, 90))]


def make_images():
    os.makedirs(os.path.join(HERE, "images"), exist_ok=True)
    font_path = r"C:\Windows\Fonts\arialbd.ttf"
    for n, ((w, h), (c0, c1)) in enumerate(zip(SIZES, PALETTES), 1):
        img = Image.new("RGB", (w, h))
        px = img.load()
        for y in range(h):
            for x in range(w):
                t = (x / w + y / h) / 2
                px[x, y] = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype(font_path, int(min(w, h) * 0.55))
        d.text((w / 2, h / 2), str(n), font=f, fill=(255, 255, 255), anchor="mm", stroke_width=8, stroke_fill=(0, 0, 0))
        # 가장자리 눈금: 자르기 위치 확인용
        d.rectangle((0, 0, w - 1, h - 1), outline=(255, 255, 255), width=6)
        d.ellipse((w * 0.1 - 30, h * 0.15 - 30, w * 0.1 + 30, h * 0.15 + 30), fill=(255, 0, 0))
        img.save(os.path.join(HERE, "images", f"img{n}.png"))


def make_voice(path, seconds=36.0, sr=24000):
    """말소리처럼 켜졌다 꺼지는 사인파(0.1초 뒤 시작)."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(int(seconds * sr)):
            t = i / sr
            if t < 0.1:
                v = 0.0
            else:
                env = max(0.0, math.sin(2 * math.pi * 3.2 * t)) ** 0.5
                v = 0.35 * env * math.sin(2 * math.pi * 180 * t) + 0.1 * env * math.sin(2 * math.pi * 540 * t)
            frames += struct.pack("<h", int(v * 32767))
        w.writeframes(bytes(frames))


SENTENCES = [
    ("야구 갤러리가 발칵 뒤집힌 사연이라는데", None),
    ("어제 경기 끝나고 올라온 글이 시작이었대", "어제"),
    ("선발투수가 갑자기 마운드에서 웃었다는 거야", "웃었다는"),
    ("관중석에서는 다들 무슨 일인가 싶었다더라", "관중석"),
    ("알고 보니 포수가 장난으로 공을 두 개 줬대", "두 개"),
    ("심판도 한참 어이없어 하더니 결국 웃음이 터졌고", "심판도"),
    ("댓글에는 이게 프로 맞냐는 반응이 줄줄이 달렸고", "프로"),
    ("감독은 인터뷰에서 그냥 분위기 풀려고 한 거라고 했다는데", "분위기"),
    ("팬들은 오히려 이런 게 야구의 맛이라며 좋아했고", "야구의 맛"),
    ("그래서 다음 경기 보러 가는 사람이 더 늘었다는데", "더 늘었다는데"),
    ("이 정도면 장난이 아니라 마케팅 아닌가 싶다", "마케팅"),
]


def make_timeline():
    total_end = 35.0
    hook_end = 2.67
    syl = [syllables(t) for t, _ in SENTENCES]
    first = (0.1, hook_end)
    rest_start, rest_end = hook_end, total_end - 0.2
    rest_syl = sum(syl[1:])
    sents, t = [], rest_start
    sents.append({"text": SENTENCES[0][0], "start": first[0], "end": first[1], "emphasis": None})
    for (text, emph), s in zip(SENTENCES[1:], syl[1:]):
        d = (rest_end - rest_start) * s / rest_syl
        sents.append({"text": text, "start": round(t, 3), "end": round(t + d, 3), "emphasis": emph})
        t += d
    cards = make_cards(sents[1:])
    shots, st, i = [], 0.0, 0
    # 훅 동안 첫 이미지 천천히 확대
    shots.append({"file": "images/img1.png", "start": 0.0, "end": hook_end, "motion": "zoom_in",
                  "focus": [0.5, 0.5], "source_id": "fixture1"})
    st = hook_end
    durs = [1.4, 1.3, 1.5, 1.2, 1.6, 1.33]
    focus = [[0.5, 0.5], [0.3, 0.4], [0.5, 0.5], [0.5, 0.2], [0.7, 0.5], [0.5, 0.5], [0.2, 0.3], [0.5, 0.5]]
    while st < total_end - 1e-6:
        d = durs[i % len(durs)]
        en = min(total_end, st + d)
        if total_end - en < 0.8:
            en = total_end
        n = (i + 1) % 8 + 1
        shots.append({"file": f"images/img{n}.png", "start": round(st, 3), "end": round(en, 3),
                      "motion": "enter" if i % 3 == 1 else "static",
                      "focus": focus[n - 1], "source_id": f"fixture{n}"})
        st = en
        i += 1
    tl = {
        "fps": 30, "size": [1080, 1920], "duration": total_end,
        "title_lines": ["테스트 제목 1줄", "노란 2줄"],
        "hook": {"text": "야구 갤러리가 발칵 뒤집힌 사연", "start": 0.0, "end": hook_end},
        "shots": shots, "captions": cards,
        "options": {"snap_captions_to_cuts": True},
        "audio": {"voice": "voice.wav", "bgm": None, "bgm_db": -22, "sfx_on_cuts": False},
    }
    with open(os.path.join(HERE, "sample_timeline.json"), "w", encoding="utf-8") as f:
        json.dump(tl, f, ensure_ascii=False, indent=1)
    return tl


if __name__ == "__main__":
    make_images()
    make_voice(os.path.join(HERE, "voice.wav"))
    tl = make_timeline()
    print(len(tl["shots"]), "shots,", len(tl["captions"]), "captions")
