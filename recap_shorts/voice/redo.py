"""이미 만든 목소리에서 문장 하나만 다시 합성해 바꿔 끼운다 (Gemini 엔진).

    python -m recap_shorts.voice.redo <voice_dir> <문장 index> --variant "합성할 문장|말투" [--variant ...]

- 화면 자막·훅 띠에 나오는 원문은 그대로 두고, 합성에 넣는 문장(쉼표 추가 등)과 말투만 바꿔 여러 판을 만든다.
- 판마다 받아쓰기 일치율(원문 기준)과 길이를 재서 가장 높은 판을 고르고, 나머지 문장은 그대로 둔 채 속도 맞춤·이어 붙이기를 다시 한다.
- Gemini 의 미리 만들어진 목소리(예: Charon)는 호출이 달라도 같은 목소리라 문장 하나만 바꿔도 이어 들린다.
- 요청 수 = 판 수. 같은 키의 하루 한도(100회)를 함께 쓴다.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import soundfile as sf

from . import asr, gemini, tts


def redo(voice_dir: str | Path, index: int, variants: list[tuple[str, str]]) -> dict:
    vd = Path(voice_dir)
    t = json.loads((vd / "timings.json").read_text(encoding="utf-8"))
    sents = t["sentences"]
    target = sents[index]
    cut_dir = vd / "sentences" / "cut"
    redo_dir = vd / "redo" / f"s{index:02d}"
    redo_dir.mkdir(parents=True, exist_ok=True)
    has_asr = asr.available()
    # 받아쓰기 모델이 없으면 판을 견줄 수 없으니 첫 판만 합성한다(요청 1번). 고르는 것도 없이 그 판을 쓴다.
    todo = list(enumerate(variants)) if has_asr else list(enumerate(variants))[:1]
    trials = []
    for k, (spoken, style) in todo:
        raw = redo_dir / f"v{k}_raw.wav"
        if t.get("engine") == "supertonic":      # 로컬 목소리로 만든 것은 같은 목소리 번호로(말투 style 은 쓰지 않음)
            x, sr = tts.synth_one(spoken, sid=t.get("sid"))
            sf.write(str(raw), x, sr, subtype="PCM_16")
        else:
            gemini.call(spoken, raw, voice=t.get("voice", gemini.DEFAULT_VOICE),
                        style=style or t.get("style", gemini.DEFAULT_STYLE), model=t.get("model", gemini.DEFAULT_MODEL))
        x, sr = sf.read(str(raw), dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        x = tts.trim_silence(x, sr)
        w = redo_dir / f"v{k}.wav"
        sf.write(str(w), x, sr, subtype="PCM_16")
        heard, m = None, None
        if has_asr:
            heard = asr.transcribe(w)
            m = round(max(asr.match_ratio(target["text"], heard), asr.match_ratio(spoken, heard)), 3)
        trials.append({"variant": k, "spoken": spoken, "style": style, "heard": heard, "match": m,
                       "duration": round(len(x) / sr, 3), "wav": str(w)})
    if has_asr:
        best = max(trials, key=lambda r: (r["match"], -r["duration"]))
    else:
        best = trials[0]
    # 원래 자른 조각 목록을 다시 만들고 index 자리만 바꿔 끼움
    items = []
    for s in sents:
        i = s["index"]
        w = Path(best["wav"]) if i == index else cut_dir / f"s{i:02d}.wav"
        x, sr = sf.read(str(w), dtype="float32")
        items.append({"text": s["text"], "spoken": best["spoken"] if i == index else s.get("spoken", s["text"]),
                      "wav": str(w), "duration": len(x) / sr})
    shutil.copy(vd / "timings.json", vd / "timings_before_redo.json")
    r = tts.fit_rate(items, vd / "sentences_fit_redo")
    roles = [s.get("role", "body") for s in sents]
    keep = {k: t[k] for k in ("engine", "model", "voice", "style", "sid", "requests", "synth_sec", "cuts") if k in t}
    extra = {**keep, "tempo_factor": round(r["factor"], 4), "rate_before_fit": round(tts.speech_rate(items), 3),
             "warnings": r["warnings"], "flags": [], "redo": {"index": index, "trials": trials, "chosen": best["variant"],
                                                              "scored": has_asr}}
    if not has_asr:
        extra["warnings"] = r["warnings"] + ["받아쓰기 모델이 없어 판을 견주지 않고 첫 판을 그대로 썼습니다"
                                             " — .venv\\Scripts\\python scripts\\setup_models.py 로 받으세요"]
    timings = tts.assemble(r["items"], vd, roles=roles, extra=extra)
    if has_asr:
        res, flags = asr.check_items(r["items"])
        for s, x in zip(timings["sentences"], res):
            s["heard"], s["match"] = x["heard"], x["match"]
        timings["flags"] = flags
        timings["asr_mean_match"] = round(sum(x["match"] for x in res) / len(res), 3)
    else:
        timings["asr_mean_match"] = None
    (vd / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"trials": trials, "chosen": best, "timings": timings, "scored": has_asr}


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.voice.redo")
    ap.add_argument("voice_dir")
    ap.add_argument("index", type=int)
    ap.add_argument("--variant", action="append", required=True, help='"합성할 문장|말투(비우면 기존 말투)"')
    a = ap.parse_args()
    vs = [(v.split("|", 1)[0], v.split("|", 1)[1] if "|" in v else "") for v in a.variant]
    out = redo(a.voice_dir, a.index, vs)
    for tr in out["trials"]:
        if tr["match"] is None:
            print(f"판 {tr['variant']}: {tr['duration']}초 · 들린 말: 받아쓰기 모델 없음")
        else:
            print(f"판 {tr['variant']}: 일치 {tr['match']} · {tr['duration']}초 · 들린 말: {tr['heard']}")
    tm = out["timings"]
    mean = tm.get("asr_mean_match")
    print(f"고른 판 {out['chosen']['variant']} → 전체 {tm['duration']:.2f}초, 말 속도 {tm['rate']:.2f}/초, "
          f"받아쓰기 평균 {mean if mean is not None else '건너뜀'}")


if __name__ == "__main__":
    main()
