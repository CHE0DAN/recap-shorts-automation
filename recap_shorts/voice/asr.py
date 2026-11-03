"""SenseVoice(sherpa-onnx) 받아쓰기로 합성 결과 확인: 원문과 글자 일치율(발음 깨짐 감지용).

모델 폴더는 저장소 안 models/(scripts/setup_models.py 로 받음). 환경변수 RECAP_SENSEVOICE_DIR 로 바꿀 수 있다.
모델이 없으면 available()=False 이고, 부르는 쪽이 발음 확인·어절 컷 다듬기를 건너뛴다.
"""
from __future__ import annotations

import difflib
import importlib.util
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from recap_shorts import modelfiles
from recap_shorts.script.text import normalize_spoken

LOW_MATCH = 0.80          # 이보다 낮으면 flags

_LOCK = threading.Lock()
_REC: dict[str, object] = {}


def default_dir() -> Path:
    return modelfiles.model_dir("sensevoice")


def _dir() -> Path:
    return default_dir()


def _recognizer(language: str = "ko"):
    """(모델 폴더, 언어)마다 인식기를 하나씩 캐시. 기본 "ko" 는 예전과 똑같이 동작한다."""
    d = _dir()
    key = str(d) if language == "ko" else f"{d}|{language}"
    with _LOCK:
        if key not in _REC:
            import sherpa_onnx as so
            _REC[key] = so.OfflineRecognizer.from_sense_voice(
                model=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"), num_threads=2,
                use_itn=True, language=language, debug=False)
        return _REC[key]


def transcribe(wav: str | Path, language: str = "ko") -> str:
    x, sr = sf.read(str(wav), dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    rec = _recognizer(language)
    s = rec.create_stream()
    s.accept_waveform(sr, np.ascontiguousarray(x))
    rec.decode_stream(s)
    return s.result.text.strip()


def transcribe_timed(x, sr: int) -> dict:
    """소리 배열(float32, 모노) -> {"text", "tokens", "ts"}. ts[i] 는 tokens[i] 가 들리는 시각(초, 배열 시작 기준, 약 0.06초 간격).
    그림 컷을 어절 사이에 놓으려고 어절 경계 시각을 얻는 데 쓴다(recap_shorts/wordcuts.py)."""
    x = np.asarray(x, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    rec = _recognizer()
    s = rec.create_stream()
    s.accept_waveform(int(sr), np.ascontiguousarray(x))
    rec.decode_stream(s)
    r = s.result
    return {"text": r.text.strip(), "tokens": list(r.tokens), "ts": [round(float(t), 3) for t in r.timestamps]}


def available() -> bool:
    """받아쓰기 모델(sherpa-onnx + SenseVoice 폴더)이 이 컴퓨터에 있는가."""
    return importlib.util.find_spec("sherpa_onnx") is not None and (default_dir() / "model.int8.onnx").is_file()


def match_ratio(expected: str, heard: str) -> float:
    a, b = normalize_spoken(expected), normalize_spoken(heard)
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def check_items(items: list[dict], threshold: float = LOW_MATCH) -> tuple[list[dict], list[str]]:
    """문장 wav 마다 받아쓰기 -> [{index, heard, match}], 낮은 문장 flags."""
    res, flags = [], []
    for i, it in enumerate(items):
        heard = transcribe(it["wav"])
        m_text = match_ratio(it["text"], heard)                    # 원문 기준 (숫자는 한자어로 읽은 꼴로 비교)
        m_spoken = match_ratio(it.get("spoken", it["text"]), heard)  # TTS 에 실제 넣은 글 기준
        m = max(m_text, m_spoken)
        res.append({"index": i, "heard": heard, "match": round(m, 3), "match_text": round(m_text, 3),
                    "match_spoken": round(m_spoken, 3)})
        if m < threshold:
            flags.append(f"문장 {i}: 받아쓰기 일치율 {m:.2f} (발음 확인) 원문 '{it['text']}' / 들린 말 '{heard}'")
    return res, flags
