import json

import numpy as np
import pytest
import soundfile as sf

from recap_shorts.voice import asr, tts


def _tone(path, sec, sr=44100):
    t = np.arange(int(sec * sr)) / sr
    sf.write(str(path), (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), sr, subtype="PCM_16")
    return {"text": "가나다라마바사아자차", "wav": str(path), "duration": sec}


def test_trim_silence():
    sr = 1000
    x = np.concatenate([np.zeros(500), np.ones(100) * 0.5, np.zeros(500)]).astype(np.float32)
    y = tts.trim_silence(x, sr)
    assert 100 < len(y) < 200


def test_fit_rate_slows_fast_voice(tmp_path):
    # 10음절 문장 20개, 문장당 1.2초 -> 약 7.7/초(너무 빠름) -> 배율 < 1
    items = [_tone(tmp_path / f"a{i}.wav", 1.2) for i in range(20)]
    assert tts.speech_rate(items) > 7
    r = tts.fit_rate(items, tmp_path / "fit")
    assert tts.TARGET_RATE[0] <= r["rate_after"] <= tts.TARGET_RATE[1]
    assert r["factor"] < 1 and not r["warnings"]


def test_fit_rate_noop_inside_range(tmp_path):
    # 문장 1.45초 + 쉼 0.1초 -> 10/1.55 = 6.45/초: 범위 안이라 그대로
    items = [_tone(tmp_path / f"b{i}.wav", 1.45) for i in range(10)]
    r = tts.fit_rate(items, tmp_path / "fit")
    assert tts.TARGET_RATE[0] <= r["rate_before"] <= tts.TARGET_RATE[1]
    assert r["factor"] == 1.0


def test_fit_rate_warns_out_of_tempo_range(tmp_path):
    items = [_tone(tmp_path / f"c{i}.wav", 3.0) for i in range(3)]      # 매우 느림: 필요한 배율 > 1.25
    r = tts.fit_rate(items, tmp_path / "fit")
    assert r["factor"] == tts.TEMPO_RANGE[1]
    assert r["warnings"]


def test_assemble_times(tmp_path):
    items = [_tone(tmp_path / f"d{i}.wav", 0.5) for i in range(3)]
    items[1]["text"] = "정말이냐?"
    t = tts.assemble(items, tmp_path / "out", roles=["hook", "body", "closing"])
    s = t["sentences"]
    assert s[0]["start"] == pytest.approx(tts.LEAD_IN, abs=0.002) and tts.LEAD_IN <= 0.15
    for a, b in zip(s, s[1:]):
        assert 0.08 <= b["start"] - a["end"] <= 0.15
    assert s[0]["end"] - s[0]["start"] == pytest.approx(0.5, abs=0.01)
    info = sf.info(str(tmp_path / "out" / "voice.wav"))
    assert info.frames / info.samplerate == pytest.approx(t["duration"], abs=0.01)
    saved = json.loads((tmp_path / "out" / "timings.json").read_text(encoding="utf-8"))
    assert saved["sentences"][0]["role"] == "hook"


def _have_model():
    return (tts.model_dir() / "vocoder.int8.onnx").exists()


@pytest.mark.skipif(not _have_model(), reason="Supertonic 모델 없음")
def test_real_supertonic_one_sentence(tmp_path):
    items = tts.synth_sentences(["동네 야구 경기에서 황당한 일이 벌어졌다는데"], tmp_path, sid=7)
    assert len(items) == 1 and 1.0 < items[0]["duration"] < 8.0
    heard = asr.transcribe(items[0]["wav"])
    assert asr.match_ratio(items[0]["text"], heard) > 0.8


@pytest.mark.skipif(not _have_model(), reason="Supertonic 모델 없음")
def test_bad_sid():
    with pytest.raises(ValueError):
        tts.synth_one("안녕", sid=10)


def test_match_ratio_numbers():
    assert asr.match_ratio("980엔 라멘", "구백팔십엔 라멘.") == 1.0
    assert asr.match_ratio("안녕하세요", "전혀 다른 말") < 0.5
