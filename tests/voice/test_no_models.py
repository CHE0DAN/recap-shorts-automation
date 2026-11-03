"""받아쓰기 모델이 없는 PC(새로 받은 저장소)에서 목소리 단계가 끝까지 가는지 — Gemini 호출은 가짜로."""
import base64
import io
import json
import wave

import numpy as np
import pytest
import soundfile as sf

from recap_shorts import settings
from recap_shorts.voice import gemini, pipeline as vp, qwen, redo

SR = 24000


def _wav_bytes(seconds: float, tone: bool = True) -> bytes:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    x = (0.3 * np.sin(2 * np.pi * 220 * t) if tone else np.zeros(n)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, x, SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class TTSResp:
    status_code = 200

    def __init__(self, seconds: float = 6.0):
        self.seconds = seconds

    def json(self):
        return {"steps": [{"type": "model_output", "content": [
            {"type": "audio", "data": base64.b64encode(_wav_bytes(self.seconds)).decode("ascii")}]}],
            "usage": {"total_tokens": 10}}

    @property
    def text(self):
        return ""


@pytest.fixture
def no_asr(monkeypatch):
    from recap_shorts.voice import asr
    monkeypatch.setattr(asr, "available", lambda: False)
    monkeypatch.setenv("RECAP_GEMINI_API_KEY", "test-gemini-key-0000000000")
    yield


def test_gemini_synth_without_asr_uses_syllable_cuts(monkeypatch, tmp_path, no_asr):
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return TTSResp(6.0)
    monkeypatch.setattr("requests.post", post)
    seen = {}
    real_cut = qwen._cut_items

    def spy(full_wav, texts, spoken, out_dir, refine=False, **kw):
        seen["refine"] = refine
        return real_cut(full_wav, texts, spoken, out_dir, refine=refine, **kw)
    monkeypatch.setattr(gemini, "_cut_items", spy)
    r = gemini.synth_sentences(["첫 번째 문장이다.", "두 번째 문장이다."], tmp_path)
    assert seen["refine"] is False                       # 받아쓰기 없으면 경계 다듬기를 건너뛴다
    assert r["meta"]["refined"] is False and len(r["items"]) == 2
    assert len(calls) == 1                               # 요청은 한 번(전체 내레이션)
    assert all(it["duration"] > 0 for it in r["items"])


def test_gemini_synth_with_asr_refines(monkeypatch, tmp_path, monkeypatch_asr=None):
    from recap_shorts.voice import asr
    monkeypatch.setattr(asr, "available", lambda: True)
    monkeypatch.setattr(asr, "transcribe", lambda *a, **k: "아무 말")
    monkeypatch.setattr(asr, "match_ratio", lambda a, b: 0.9)
    monkeypatch.setenv("RECAP_GEMINI_API_KEY", "test-gemini-key-0000000000")
    monkeypatch.setattr("requests.post", lambda *a, **k: TTSResp(6.0))
    seen = {}
    real_cut = qwen._cut_items

    def spy(full_wav, texts, spoken, out_dir, refine=False, **kw):
        seen["refine"] = refine
        return real_cut(full_wav, texts, spoken, out_dir, refine=refine, **kw)
    monkeypatch.setattr(gemini, "_cut_items", spy)
    r = gemini.synth_sentences(["첫 번째 문장이다.", "두 번째 문장이다."], tmp_path)
    assert seen["refine"] is True and r["meta"]["refined"] is True


def _script():
    return {"hook": "오늘의 이야기", "sentences": [{"text": "첫 문장입니다"}, {"text": "둘째 문장입니다"}],
            "closing": "끝"}


def test_make_voice_gemini_without_asr(monkeypatch, tmp_path, no_asr):
    monkeypatch.setattr("requests.post", lambda *a, **k: TTSResp(9.0))
    monkeypatch.setattr(vp.tts, "fit_rate", lambda items, out, **kw: {
        "items": items, "factor": 1.0, "rate_before": 6.5, "rate_after": 6.5, "warnings": []})
    tm = vp.make_voice(_script(), tmp_path / "voice", engine="gemini", check_asr=True)
    assert tm["asr_mean_match"] is None                  # 받아쓰기를 건너뛰었다
    assert any("받아쓰기 모델이 없어" in w for w in tm["warnings"])
    assert "setup_models.py" in " ".join(tm["warnings"])
    saved = json.loads((tmp_path / "voice" / "timings.json").read_text(encoding="utf-8"))
    assert saved["asr_mean_match"] is None and "heard" not in saved["sentences"][0]


def test_make_voice_asr_unavailable_but_not_requested(monkeypatch, tmp_path):
    """check_asr=False 면 예전처럼 아무 표시도 없다."""
    from recap_shorts.voice import asr
    monkeypatch.setattr(asr, "available", lambda: False)
    monkeypatch.setenv("RECAP_GEMINI_API_KEY", "test-gemini-key-0000000000")
    monkeypatch.setattr("requests.post", lambda *a, **k: TTSResp(9.0))
    monkeypatch.setattr(vp.tts, "fit_rate", lambda items, out, **kw: {
        "items": items, "factor": 1.0, "rate_before": 6.5, "rate_after": 6.5, "warnings": []})
    tm = vp.make_voice(_script(), tmp_path / "voice2", engine="gemini", check_asr=False)
    assert "asr_mean_match" not in tm and not any("받아쓰기 모델이 없어" in w for w in tm["warnings"])


def test_qwen_synth_without_asr_skips_check(monkeypatch, tmp_path):
    from recap_shorts.voice import asr
    monkeypatch.setattr(asr, "available", lambda: False)
    full = tmp_path / "full.wav"
    sf.write(str(full), np.concatenate([np.zeros(0, dtype=np.float32), _wav_array(3.0)]), SR, subtype="PCM_16")
    calls = []

    def fake_cli(text, instruct, seed, out_wav, language="Korean", work=None):
        calls.append(seed)
        sf.write(str(out_wav), _wav_array(3.0), SR, subtype="PCM_16")
        return {"duration": 3.0, "load_sec": 0.1, "synth_sec": 0.2, "gpu_mem_peak_mb": 0,
                "gpu": "cpu", "sample_rate": SR, "model": "fake"}
    monkeypatch.setattr(qwen, "run_cli", fake_cli)
    seen = {}
    real_cut = qwen._cut_items

    def spy(full_wav, texts, spoken, out_dir, refine=False, **kw):
        seen["refine"] = refine
        return real_cut(full_wav, texts, spoken, out_dir, refine=refine, **kw)
    monkeypatch.setattr(qwen, "_cut_items", spy)
    r = qwen.synth_sentences(["첫 문장입니다", "둘째 문장입니다"], tmp_path / "q")
    assert seen["refine"] is False and len(calls) == 1
    assert r["meta"]["min_match_ok"] is True             # 확인을 못 했으니 재합성도 안 한다


def _wav_array(seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_redo_without_asr_one_variant_no_score(monkeypatch, tmp_path, no_asr):
    vd = tmp_path / "voice"
    cut = vd / "sentences" / "cut"
    cut.mkdir(parents=True)
    sents = []
    for i in range(3):
        p = cut / f"s{i:02d}.wav"
        sf.write(str(p), _wav_array(1.5), SR, subtype="PCM_16")
        sents.append({"index": i, "role": "body", "text": f"문장 {i}", "spoken": f"문장 {i}", "start": 0.0,
                      "end": 1.5, "syllables": 3})
    (vd / "timings.json").write_text(json.dumps({"voice": "voice.wav", "sample_rate": SR, "duration": 5.0,
                                                 "speech_start": 0.0, "speech_end": 4.5, "syllables": 9, "rate": 2.0,
                                                 "sentences": sents, "engine": "gemini", "asr_mean_match": 0.9},
                                                ensure_ascii=False), encoding="utf-8")
    calls = []

    def fake_call(text, out_wav, voice=None, style=None, model=None, max_attempts=3):
        calls.append(text)
        sf.write(str(out_wav), _wav_array(1.4), SR, subtype="PCM_16")
        return {"seconds": 0.1, "attempt": 1}
    monkeypatch.setattr(gemini, "call", fake_call)
    out = redo.redo(vd, 1, [("고친 문장", ""), ("다른 판", ""), ("세 번째 판", "")])
    assert len(calls) == 1 and out["scored"] is False
    assert len(out["trials"]) == 1 and out["trials"][0]["match"] is None
    assert out["chosen"]["variant"] == 0
    tm = json.loads((vd / "timings.json").read_text(encoding="utf-8"))
    assert tm["asr_mean_match"] is None and tm["redo"]["scored"] is False
    assert any("첫 판" in w for w in tm["warnings"])
    assert tm["sentences"][1]["spoken"] == "고친 문장"


def test_redo_with_asr_compares_variants(monkeypatch, tmp_path):
    from recap_shorts.voice import asr
    monkeypatch.setattr(asr, "available", lambda: True)
    heard = iter(["나쁜 말", "정확한 말", "또 나쁜 말"])
    monkeypatch.setattr(asr, "transcribe", lambda *a, **k: next(heard))
    monkeypatch.setattr(asr, "check_items", lambda items, threshold=0.8: (
        [{"index": i, "heard": "x", "match": 0.9, "match_text": 0.9, "match_spoken": 0.9} for i in range(len(items))],
        []))
    monkeypatch.setenv("RECAP_GEMINI_API_KEY", "test-gemini-key-0000000000")
    vd = tmp_path / "voice2"
    (vd / "sentences" / "cut").mkdir(parents=True)
    p = vd / "sentences" / "cut" / "s00.wav"
    sf.write(str(p), _wav_array(1.5), SR, subtype="PCM_16")
    (vd / "timings.json").write_text(json.dumps({"sentences": [
        {"index": 0, "role": "body", "text": "정확한 말", "start": 0.0, "end": 1.5, "syllables": 4}]},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(gemini, "call", lambda text, out_wav, **k: (
        sf.write(str(out_wav), _wav_array(1.4), SR, subtype="PCM_16"), {"seconds": 0.1, "attempt": 1})[1])
    out = redo.redo(vd, 0, [("가", ""), ("정확한 말", ""), ("다", "")])
    assert out["scored"] is True and out["chosen"]["variant"] == 1
    assert [t["match"] for t in out["trials"]][1] > [t["match"] for t in out["trials"]][0]


def test_supertonic_missing_model_names_the_command(monkeypatch, tmp_path):
    from recap_shorts.voice import tts
    monkeypatch.setenv("RECAP_SUPERTONIC_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(tts, "_CACHE", {})
    with pytest.raises(tts.TTSUnavailable) as e:
        tts.synth_one("안녕", sid=0)
    assert "Supertonic 모델 없음" in str(e.value) and "setup_models.py --supertonic" in str(e.value)


def test_default_dirs_point_into_repo_models():
    from recap_shorts import modelfiles
    from recap_shorts.voice import asr, tts
    assert asr.default_dir() == modelfiles.REPO_ROOT / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    assert tts.model_dir() == modelfiles.REPO_ROOT / "models" / "sherpa-onnx-supertonic-3-tts-int8-2026-05-11"


def test_gemini_api_key_message_points_at_settings(monkeypatch):
    monkeypatch.delenv("RECAP_GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as e:
        gemini.api_key()
    assert "설정" in str(e.value)
    settings.save({"gemini_api_key": "test-gemini-key-0000000000"})
    assert gemini.api_key() == "test-gemini-key-0000000000"
