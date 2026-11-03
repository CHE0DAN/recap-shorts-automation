"""Qwen3-TTS VoiceDesign 합성 CLI. qwen 가상환경(tools/qwen_tts/.venv)에서 실행한다.

    tools/qwen_tts/.venv/Scripts/python tools/qwen_tts/synth_cli.py <입력.json>

입력 JSON: {"text": 전체 내레이션, "instruct": 목소리 설명, "language": "Korean", "seed": 정수, "out": wav 경로,
           (선택) "max_new_tokens": 정수, "temperature": 실수}
출력(stdout 한 줄 JSON): {"out", "duration", "sample_rate", "load_sec", "synth_sec", "gpu", "gpu_name",
                         "gpu_mem_peak_mb", "seed", "model"}
모델 캐시는 tools/qwen_tts/models (환경변수 HF_HOME 이 이미 있으면 그것을 따름).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(HERE / "models"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("사용법: synth_cli.py <입력.json>", file=sys.stderr)
        return 2
    real_stdout = sys.stdout
    sys.stdout = sys.stderr          # 라이브러리가 stdout 에 찍는 말이 결과 JSON 을 오염시키지 않게
    req = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    use_gpu = torch.cuda.is_available()
    t0 = time.time()
    kw = {"device_map": "cuda:0", "dtype": torch.bfloat16} if use_gpu else {"device_map": "cpu", "dtype": torch.float32}
    try:
        model = Qwen3TTSModel.from_pretrained(MODEL_ID, attn_implementation="sdpa", **kw)
    except Exception:
        model = Qwen3TTSModel.from_pretrained(MODEL_ID, **kw)
    load_sec = time.time() - t0

    seed = int(req.get("seed", 0))
    torch.manual_seed(seed)
    if use_gpu:
        torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats()
    gen = {}
    if req.get("max_new_tokens"):
        gen["max_new_tokens"] = int(req["max_new_tokens"])
    if req.get("temperature"):
        gen["temperature"] = float(req["temperature"])
    t1 = time.time()
    wavs, sr = model.generate_voice_design(text=req["text"], instruct=req.get("instruct", ""),
                                           language=req.get("language", "Korean"), **gen)
    if use_gpu:
        torch.cuda.synchronize()
    synth_sec = time.time() - t1
    x = np.asarray(wavs[0], dtype=np.float32)
    out = Path(req["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), x, sr, subtype="PCM_16")
    res = {"out": str(out), "duration": round(len(x) / sr, 3), "sample_rate": int(sr), "load_sec": round(load_sec, 2),
           "synth_sec": round(synth_sec, 2), "gpu": bool(use_gpu),
           "gpu_name": torch.cuda.get_device_name(0) if use_gpu else None,
           "gpu_mem_peak_mb": round(torch.cuda.max_memory_allocated() / 2**20) if use_gpu else 0,
           "seed": seed, "model": MODEL_ID}
    real_stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    real_stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
