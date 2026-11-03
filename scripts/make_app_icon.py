"""앱 아이콘 생성 (PIL만): assets/app/icon.png(256) + icon.ico(16~256)"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets" / "app"
S = 1024  # 큰 캔버스에 그린 뒤 줄인다 (안티앨리어싱)


def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=220, fill="#FFD400")
    cx, cy, r = 540, 512, 270  # 재생 삼각형: 살짝 오른쪽으로 치우침(시각 중심 보정)
    d.polygon([(cx - r * 0.75, cy - r), (cx - r * 0.75, cy + r), (cx + r * 1.05, cy)], fill="#000000")
    return im


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.ico", sizes=[(s, s) for s in sizes])
    print("저장:", OUT)


if __name__ == "__main__":
    main()
