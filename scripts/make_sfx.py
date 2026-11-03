"""효과음 합성: numpy 로 직접 만든 저작권 걱정 없는 소리 묶음 -> assets/sfx/*.wav + manifest.json.

  python scripts/make_sfx.py [--out assets/sfx]

48 kHz 모노 16bit, 피크 정규화(-1 dBFS). 시드가 고정이라 다시 만들어도 같은 파일이 나온다.
종류: whoosh swoosh pop ding boom click typing riser buzz boing shutter coin slidewhistle (여러 변형).
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

SR = 48000
PEAK = 10 ** (-1 / 20)


def t_axis(dur: float) -> np.ndarray:
    return np.arange(int(SR * dur)) / SR


def env_ad(n: int, attack: float, decay_tau: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.exp(-t / decay_tau) * np.minimum(1.0, t / max(attack, 1e-4))


def sweep_noise(rng, dur: float, f0: float, f1: float, rel_bw: float = 0.6, block: int = 1024) -> np.ndarray:
    """흰 소음을 주파수 영역에서 중심이 f0->f1 로 움직이는 대역통과로 거른다(50% 겹침 합성)."""
    n = int(SR * dur)
    x = rng.standard_normal(n + block)
    win = np.hanning(block)
    out = np.zeros(n + 2 * block)
    freqs = np.fft.rfftfreq(block, 1 / SR)
    hop = block // 2
    for s in range(0, n, hop):
        c = f0 * (f1 / f0) ** (s / max(n, 1))
        bw = c * rel_bw
        g = np.exp(-0.5 * ((freqs - c) / bw) ** 2)
        seg = np.fft.irfft(np.fft.rfft(x[s:s + block] * win) * g, block)
        out[s:s + block] += seg * win
    return out[:n]


def lowpass(x: np.ndarray, fc: float) -> np.ndarray:
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X * (1 / (1 + (f / fc) ** 4)), len(x))


def highpass(x: np.ndarray, fc: float) -> np.ndarray:
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X * ((f / fc) ** 4 / (1 + (f / fc) ** 4)), len(x))


def tone_sweep(dur: float, f0: float, f1: float, curve: float = 1.0) -> np.ndarray:
    t = t_axis(dur)
    p = (t / dur) ** curve
    f = f0 + (f1 - f0) * p
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def add_at(buf: np.ndarray, sig: np.ndarray, at: float, gain: float = 1.0) -> None:
    i = int(at * SR)
    j = min(len(buf), i + len(sig))
    if j > i:
        buf[i:j] += sig[: j - i] * gain


# ---------- 소리들 ----------

def whoosh(seed=1, dur=0.65, f0=250, f1=3500):
    rng = np.random.default_rng(seed)
    x = sweep_noise(rng, dur, f0, f1, 0.9)
    t = np.linspace(0, 1, len(x))
    return x * np.sin(np.pi * t) ** 2


def swoosh(seed=2, dur=0.28, f0=1500, f1=6000):
    rng = np.random.default_rng(seed)
    x = sweep_noise(rng, dur, f0, f1, 0.7)
    t = np.linspace(0, 1, len(x))
    return x * np.sin(np.pi * t ** 0.7) ** 2


def pop(seed=3, f0=900, f1=220, dur=0.16):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-t / 0.02)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_ad(n, 0.001, 0.035)
    click_ = np.random.default_rng(seed).standard_normal(n) * np.exp(-t / 0.002) * 0.25
    return x + click_


def ding(seed=4, f=1318.5, dur=1.1, ratios=(1.0, 2.76, 5.4, 8.9), amps=(1.0, 0.45, 0.22, 0.1)):
    t = t_axis(dur)
    x = np.zeros_like(t)
    for r, a in zip(ratios, amps):
        x += a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / (0.5 / (0.6 + r * 0.4)))
    return x * np.minimum(1.0, t / 0.002)


def boom(seed=5, dur=1.0):
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    f = 38 + 90 * np.exp(-t / 0.12)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.28)
    n = lowpass(rng.standard_normal(len(t)), 900) * np.exp(-t / 0.07) * 1.2
    return np.tanh(1.6 * (x + n)) * np.minimum(1.0, t / 0.002)


def click(seed=6, dur=0.05, fc=2500):
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    t = np.arange(n) / SR
    return highpass(rng.standard_normal(n), fc) * np.exp(-t / 0.006)


def typing(seed=7, n_keys=6):
    rng = np.random.default_rng(seed)
    buf = np.zeros(int(SR * 1.2))
    at = 0.02
    for _ in range(n_keys):
        c = click(seed=int(rng.integers(0, 10_000)), fc=float(rng.uniform(1800, 3200)))
        add_at(buf, c, at, float(rng.uniform(0.6, 1.0)))
        at += float(rng.uniform(0.07, 0.15))
    return buf[: int(SR * (at + 0.08))]


def riser(seed=8, dur=1.3):
    rng = np.random.default_rng(seed)
    x = sweep_noise(rng, dur, 200, 7000, 0.8)
    tone = tone_sweep(dur, 220, 1800, 2.0) * 0.35
    t = np.linspace(0, 1, len(x))
    return (x + tone[: len(x)]) * t ** 2.2


def buzz(seed=9, dur=0.5):
    t = t_axis(dur)
    out = np.zeros_like(t)
    for a, b in ((0.0, 0.2), (0.26, 0.46)):
        m = ((t >= a) & (t < b)).astype(float)
        saw = 2 * ((t * 140) % 1.0) - 1
        sq = np.sign(np.sin(2 * np.pi * 140 * t))
        att = np.clip((t - a) / 0.004, 0, 1)
        rel = np.clip((b - t) / 0.01, 0, 1)
        out += m * (0.6 * saw + 0.4 * sq) * att * rel
    return lowpass(out, 2200)


def boing(seed=10, dur=0.7):
    t = t_axis(dur)
    f = 180 + 520 * np.exp(-t / 0.18) * (1 + 0.35 * np.sin(2 * np.pi * 9 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) + 0.35 * np.sin(2 * ph)
    return x * np.exp(-t / 0.3) * np.minimum(1.0, t / 0.003)


def shutter(seed=11):
    buf = np.zeros(int(SR * 0.22))
    add_at(buf, click(seed, 0.04, 3200), 0.0, 1.0)
    add_at(buf, click(seed + 1, 0.05, 1800), 0.07, 0.8)
    t = t_axis(0.12)
    add_at(buf, np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.02), 0.0, 0.5)
    return buf


def coin(seed=12, dur=0.7):
    buf = np.zeros(int(SR * dur))
    for at, f, d in ((0.0, 987.8, 0.08), (0.07, 1318.5, 0.6)):
        t = t_axis(d)
        x = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)) * np.exp(-t / (d / 3))
        add_at(buf, x * np.minimum(1.0, t / 0.002), at)
    return buf


def slidewhistle(seed=13, dur=1.5, f0=2200.0, f1=380.0):
    """길게 내려가는 미끄럼 휘슬(끝 효과음). 지수로 내려가는 음높이 + 약한 떨림."""
    t = t_axis(dur)
    p = t / dur
    f = f0 * (f1 / f0) ** (p ** 0.8) * (1 + 0.012 * np.sin(2 * np.pi * 6 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) + 0.18 * np.sin(2 * ph)
    env = np.minimum(1.0, t / 0.02) * np.clip((dur - t) / 0.25, 0, 1) ** 1.5
    return x * env


# (id, type, 만드는 함수)
SPECS = [
    ("whoosh_01", "whoosh", lambda: whoosh(1)), ("whoosh_02", "whoosh", lambda: whoosh(21, 0.5, 400, 5000)),
    ("swoosh_01", "swoosh", lambda: swoosh(2)), ("swoosh_02", "swoosh", lambda: swoosh(22, 0.22, 2200, 7500)),
    ("pop_01", "pop", lambda: pop(3)), ("pop_02", "pop", lambda: pop(23, 1200, 300, 0.12)),
    ("pop_03", "pop", lambda: pop(33, 700, 160, 0.2)),
    ("ding_01", "ding", lambda: ding(4)), ("ding_02", "ding", lambda: ding(24, 1760, 0.9)),
    ("boom_01", "boom", lambda: boom(5)), ("boom_02", "boom", lambda: boom(25, 1.3)),
    ("click_01", "click", lambda: click(6)), ("click_02", "click", lambda: click(26, 0.04, 3500)),
    ("typing_01", "typing", lambda: typing(7)),
    ("riser_01", "riser", lambda: riser(8)),
    ("buzz_01", "buzz", lambda: buzz(9)),
    ("boing_01", "boing", lambda: boing(10)),
    ("shutter_01", "shutter", lambda: shutter(11)),
    ("coin_01", "coin", lambda: coin(12)),
    ("slidewhistle_01", "slidewhistle", lambda: slidewhistle(13)),
    ("slidewhistle_02", "slidewhistle", lambda: slidewhistle(33, 1.2, 1800.0, 300.0)),
]


def to_wav(path: Path, x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    x = x - x.mean()
    f = min(len(x), int(SR * 0.005))  # 끝 5ms 페이드(딱 소리 방지)
    x[-f:] *= np.linspace(1, 0, f)
    x = x / (np.abs(x).max() + 1e-12) * PEAK
    pcm = np.round(x * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return len(pcm) / SR


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "assets" / "sfx"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = []
    for sid, typ, fn in SPECS:
        dur = to_wav(out / f"{sid}.wav", fn())
        items.append({"id": sid, "file": f"{sid}.wav", "type": typ, "duration": round(dur, 3), "peak_db": -1.0,
                      "made_by": "scripts/make_sfx.py"})
    (out / "manifest.json").write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print(f"{len(items)}개 효과음 -> {out}")


if __name__ == "__main__":
    main()
