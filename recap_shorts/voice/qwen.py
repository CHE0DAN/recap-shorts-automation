"""Qwen3-TTS VoiceDesign 1.7B 엔진 (별도 가상환경 tools/qwen_tts/.venv 의 synth_cli.py 를 subprocess 로 부름).

목소리 일관성: VoiceDesign 은 호출마다 목소리가 달라질 수 있어, 내레이션 전체를 한 번에 합성한 뒤 문장별로 자른다.
자르기 = 문장 사이 쉼(무음) 중, 음절 수 비율로 예상한 경계에 가장 가까운 쉼. 자른 조각마다 SenseVoice 로 받아써서
원문과 일치율을 보고, 낮으면 seed 를 바꿔 다시 합성(최대 3회).
설정(환경변수): RECAP_QWEN_PYTHON(qwen 가상환경 python 경로), RECAP_QWEN_TIMEOUT(초, 기본 1800).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from recap_shorts.script.text import count_syllables

from . import tts
from .spoken import to_spoken

_REPO = Path(__file__).resolve().parents[2]
CLI = _REPO / "tools" / "qwen_tts" / "synth_cli.py"
DEFAULT_PYTHON = _REPO / "tools" / "qwen_tts" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
# 발음을 또박또박 하라는 설명을 더한 판이 여러 판 시험에서 받아쓰기 일치가 가장 높았다
DEFAULT_INSTRUCT = ("30대 한국 남성 내레이터, 이슈를 빠르게 요약하는 유튜브 쇼츠 해설 목소리. "
                    "발음은 또박또박 정확하게, 받침과 문장 끝 음절까지 분명하게, 단어를 뭉개거나 흘리지 않게. "
                    "리듬감 있는 반말 구어체, 과장된 연기나 고함 없이 자연스럽게.")
DEFAULT_SEED = 1
MAX_TRIES = 3
MIN_MATCH = 0.80          # 조각별 받아쓰기 일치율이 이보다 낮으면 경계/발음 의심 -> 재합성
VALLEY_MARGIN = 0.05      # 쉼 속 경계를 말 중간 골짜기로 옮기려면 두 조각 일치율 합이 이만큼 좋아져야 함(받아쓰기 흔들림 ±0.02 남짓)


class QwenUnavailable(RuntimeError):
    pass


def python_exe() -> Path:
    return Path(os.environ.get("RECAP_QWEN_PYTHON") or DEFAULT_PYTHON)


# ---------------------------------------------------------------- 쉼 찾기·자르기 (GPU·네트워크 없이 시험 가능)

def _frame_db(x: np.ndarray, sr: int, hop: float = 0.01) -> np.ndarray:
    n = max(1, int(sr * hop))
    m = len(x) // n
    if m == 0:
        return np.full(1, -120.0)
    fr = x[: m * n].reshape(m, n).astype(np.float64)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-7))


def find_pauses(x: np.ndarray, sr: int, min_len: float = 0.10, rel_db: float = 35.0,
                hop: float = 0.01) -> tuple[list[tuple[float, float]], float, float]:
    """무음 구간 찾기. 반환: ([(시작초, 끝초)...], 첫 말 시작초, 마지막 말 끝초). 앞뒤 무음은 제외.
    기준: 큰 소리(상위 10% 프레임)보다 rel_db 이상 작은 프레임."""
    db = _frame_db(x, sr, hop)
    loud = float(np.percentile(db, 90))
    quiet = db < max(loud - rel_db, -70.0)
    voiced = np.where(~quiet)[0]
    if len(voiced) == 0:
        return [], 0.0, len(x) / sr
    first, last = int(voiced[0]), int(voiced[-1])
    gaps, i = [], first
    while i <= last:
        if quiet[i]:
            j = i
            while j <= last and quiet[j]:
                j += 1
            if (j - i) * hop >= min_len:
                gaps.append((i * hop, j * hop))
            i = j
        else:
            i += 1
    return gaps, first * hop, (last + 1) * hop


def expected_boundaries(weights: list[float], start: float, end: float) -> list[float]:
    """문장 가중치(음절 수 등) 비율로 예상한 문장 사이 경계(초). 길이 len(weights)-1."""
    tot = float(sum(weights)) or 1.0
    out, acc = [], 0.0
    for w in weights[:-1]:
        acc += w
        out.append(start + (end - start) * acc / tot)
    return out


def choose_cuts(x: np.ndarray, sr: int, weights: list[float]) -> list[float]:
    """문장 수 N 개로 자를 경계 N-1 개(초)를 고른다. 쉼 중 예상 경계에 가까운 것(긴 쉼 선호)을 순서를 지키며 DP 로 선택.
    쉼이 모자라면 예상 위치 근처 가장 조용한 지점을 대신 쓴다(벌점 0.5)."""
    n = len(weights)
    if n <= 1:
        return []
    gaps, start, end = find_pauses(x, sr)
    exp = expected_boundaries([float(w) for w in weights], start, end)
    cands = [((a + b) / 2, -0.5 * min(b - a, 0.5)) for a, b in gaps]      # (위치, 고정 비용)
    db = _frame_db(x, sr)
    for e in exp:                                                          # 대체 후보: 예상 지점 ±0.5초의 가장 조용한 곳
        lo, hi = max(0, int((e - 0.5) / 0.01)), min(len(db), int((e + 0.5) / 0.01) + 1)
        if hi > lo:
            cands.append(((lo + int(np.argmin(db[lo:hi]))) * 0.01 + 0.005, 0.5))
    cands.sort()
    m = len(cands)
    inf = float("inf")
    cost = [[inf] * m for _ in range(len(exp))]
    back = [[-1] * m for _ in range(len(exp))]
    for k in range(len(exp)):
        for j in range(m):
            c = abs(cands[j][0] - exp[k]) + cands[j][1]
            if k == 0:
                cost[0][j] = c
            else:
                for p in range(j):
                    if cands[p][0] < cands[j][0] - 0.02 and cost[k - 1][p] + c < cost[k][j]:
                        cost[k][j], back[k][j] = cost[k - 1][p] + c, p
    j = min(range(m), key=lambda q: cost[-1][q]) if m else -1
    if j < 0 or cost[-1][j] == inf:
        return exp                                                         # 선택 불가: 예상 경계 그대로
    cuts = []
    for k in range(len(exp) - 1, -1, -1):
        cuts.append(cands[j][0])
        j = back[k][j]
    return cuts[::-1]


def refine_cuts(x: np.ndarray, sr: int, cuts: list[float], score, radius: float = 1.0, passes: int = 2,
                min_piece: float = 0.4) -> list[float]:
    """받아쓰기 점수로 경계 다듬기. 각 경계를 주변(±radius초)의 쉼 후보로 옮겨 보며, 그 경계 양옆 두 조각의
    score(문장번호, 시작초, 끝초) 합이 가장 큰 곳을 고른다(좋아질 때만 이동). 처음 고른 경계가 문장 중간 쉼표에 걸린 경우를 바로잡는다."""
    cuts = list(cuts)
    if not cuts:
        return cuts
    dur = len(x) / sr
    gaps, _, _ = find_pauses(x, sr, min_len=0.05, rel_db=30.0)

    def in_pause(c: float) -> bool:
        return any(a <= c <= b for a, b in gaps)
    pool = [(a + b) / 2 for a, b in gaps]
    db = _frame_db(x, sr)                                   # 쉼이 없는 곳(말이 이어짐)을 위해 에너지 골짜기도 후보로
    for i in range(6, len(db) - 6):
        if db[i] == db[i - 6:i + 7].min() and db[i] < float(np.percentile(db, 90)) - 15.0:
            pool.append(i * 0.01 + 0.005)
    pool = sorted(set(round(c, 3) for c in pool))
    cache: dict = {}

    def sc(i: int, a: float, b: float) -> float:
        key = (i, round(a, 3), round(b, 3))
        if key not in cache:
            cache[key] = float(score(i, a, b))
        return cache[key]

    for _ in range(passes):
        moved = False
        for k in range(len(cuts)):
            left = cuts[k - 1] if k > 0 else 0.0
            right = cuts[k + 1] if k + 1 < len(cuts) else dur
            lo, hi = left + min_piece, right - min_piece
            opts = sorted((c for c in pool if abs(c - cuts[k]) <= radius and lo <= c <= hi and c != cuts[k]),
                          key=lambda c: abs(c - cuts[k]))
            cur = sc(k, left, cuts[k]) + sc(k + 1, cuts[k], right)
            best, best_v = cuts[k], cur
            paused = in_pause(cuts[k])
            for c in opts:
                v = sc(k, left, c) + sc(k + 1, c, right)
                # 쉼 안의 경계를 말 중간(에너지 골짜기)으로 옮기는 것은 받아쓰기 흔들림보다 크게 좋아질 때만 —
                # 받아쓰기는 경계와 상관없는 낱말을 다르게 알아듣는 것만으로도 점수가 흔들려, 작은 차로 옮기면 경계가 낱말 속으로 들어가 말끝이 잘린다
                need = VALLEY_MARGIN if paused and not in_pause(c) else 0.005
                if v > best_v + need:
                    best, best_v = c, v
            if best != cuts[k]:
                cuts[k], moved = best, True
        if not moved:
            break
    return cuts


def split_wav(x: np.ndarray, sr: int, cuts: list[float]) -> list[np.ndarray]:
    edges = [0] + [int(c * sr) for c in cuts] + [len(x)]
    return [tts.trim_silence(x[a:b], sr) for a, b in zip(edges[:-1], edges[1:])]


# ---------------------------------------------------------------- CLI 호출

def run_cli(text: str, instruct: str, seed: int, out_wav: Path, language: str = "Korean",
            work: Path | None = None) -> dict:
    py = python_exe()
    if not py.exists() or not CLI.exists():
        raise QwenUnavailable(f"qwen 환경 없음: {py} (tools/qwen_tts 설치 필요, requirements-qwen.txt 참고)")
    work = work or out_wav.parent
    work.mkdir(parents=True, exist_ok=True)
    req = work / f"req_seed{seed}.json"
    req.write_text(json.dumps({"text": text, "instruct": instruct, "language": language, "seed": seed,
                               "out": str(out_wav)}, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([str(py), str(CLI), str(req)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=int(os.environ.get("RECAP_QWEN_TIMEOUT", "1800")),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise QwenUnavailable(f"synth_cli 실패({r.returncode}): {r.stderr[-800:]}")
    lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        raise QwenUnavailable(f"synth_cli 결과 JSON 없음: {r.stdout[-300:]} {r.stderr[-300:]}")
    return json.loads(lines[-1])


def _cut_items(full_wav: Path, texts: list[str], spoken: list[str], out_dir: Path,
               refine: bool = False) -> tuple[list[dict], list[float]]:
    """문장 길이(음절 수 + 1) 비율로 자를 곳을 정하고, refine 이면 받아쓰기 일치율로 경계를 다듬는다."""
    x, sr = sf.read(str(full_wav), dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = [count_syllables(s) + 1 for s in spoken]
    cuts = choose_cuts(x, sr, weights)
    if refine and cuts:
        from . import asr
        tmp = out_dir / "_probe.wav"

        def score(i: int, a: float, b: float) -> float:
            seg = tts.trim_silence(x[int(a * sr):int(b * sr)], sr)
            sf.write(str(tmp), seg, sr, subtype="PCM_16")
            heard = asr.transcribe(tmp)
            return max(asr.match_ratio(texts[i], heard), asr.match_ratio(spoken[i], heard))

        cuts = refine_cuts(x, sr, cuts, score)
        tmp.unlink(missing_ok=True)
    pieces = split_wav(x, sr, cuts)
    items = []
    for i, (t, s, p) in enumerate(zip(texts, spoken, pieces)):
        w = out_dir / f"s{i:02d}.wav"
        sf.write(str(w), p, sr, subtype="PCM_16")
        items.append({"text": t, "spoken": s, "wav": str(w), "duration": len(p) / sr})
    return items, cuts


def synth_sentences(sentences: list[str], out_dir: str | Path, instruct: str | None = None, seed: int | None = None,
                    max_tries: int = MAX_TRIES, min_match: float = MIN_MATCH, check: bool = True,
                    language: str = "Korean") -> dict:
    """전체 내레이션을 한 번에 합성 -> 문장별로 자름 -> 받아쓰기로 확인(불일치면 seed+1 로 재합성, 최대 max_tries).
    반환: {items:[{text,spoken,wav,duration}], meta:{engine,instruct,seed,tries,attempts:[...],...}}
    items 는 tts.synth_sentences 와 같은 꼴이라 fit_rate·assemble 에 그대로 넘긴다."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    instruct = DEFAULT_INSTRUCT if instruct is None else instruct
    seed = DEFAULT_SEED if seed is None else int(seed)
    spoken = [to_spoken(t) for t in sentences]
    if check:
        from . import asr
        check = asr.available()      # 받아쓰기 모델이 없으면 경계 다듬기·발음 확인을 건너뛴다(영상은 만들어짐)
    # 문장 끝에 부호가 없으면(예: 훅 "… 직업 근황") 다음 문장과 쉼 없이 붙어 읽혀 경계가 단어 중간에 생긴다.
    # 합성 입력에만 마침표를 붙여 쉼을 만든다. 자막·받아쓰기 비교는 원문 그대로.
    full_text = " ".join(t if t.rstrip()[-1:] in ".!?…,~" else t.rstrip() + "." for t in spoken)
    attempts, best = [], None
    for k in range(max_tries):
        s = seed + k
        t0 = time.time()
        full = out / f"full_seed{s}.wav"
        info = run_cli(full_text, instruct, s, full, language, work=out)
        items, cuts = _cut_items(full, sentences, spoken, out / f"cut_seed{s}", refine=check)
        matches: list[float] = []
        if check:
            from . import asr
            for it in items:
                heard = asr.transcribe(it["wav"])
                matches.append(round(max(asr.match_ratio(it["text"], heard), asr.match_ratio(it["spoken"], heard)), 3))
        worst = min(matches) if matches else 1.0
        mean = sum(matches) / len(matches) if matches else 1.0
        attempts.append({"seed": s, "full_duration": info["duration"], "load_sec": info["load_sec"],
                         "synth_sec": info["synth_sec"], "gpu_mem_peak_mb": info["gpu_mem_peak_mb"],
                         "gpu": info["gpu"], "gpu_name": info.get("gpu_name"), "sample_rate": info["sample_rate"],
                         "cuts": [round(c, 3) for c in cuts], "matches": matches, "min_match": round(worst, 3), "mean_match": round(mean, 3),
                         "wall_sec": round(time.time() - t0, 1)})
        if best is None or (worst, mean) > (best[0], best[1]):
            best = (worst, mean, items, s, info)
        if not check or worst >= min_match:
            break
    worst, mean, items, used_seed, info = best
    meta = {"engine": "qwen", "model": info.get("model"), "instruct": instruct, "seed": used_seed, "seed_start": seed,
            "tries": len(attempts), "retries": len(attempts) - 1, "min_match_ok": worst >= min_match,
            "attempts": attempts, "sample_rate": info["sample_rate"]}
    return {"items": items, "meta": meta}
