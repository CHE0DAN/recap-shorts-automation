"""Qwen 엔진: 쉼 찾기·경계 자르기는 합성 wav(사인파+무음)로 GPU·네트워크 없이 시험. 실제 호출은 live."""
import numpy as np
import pytest
import soundfile as sf

from recap_shorts.voice import qwen

SR = 24000


def _tone(sec, hz=200):
    t = np.arange(int(sec * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _sil(sec):
    return np.zeros(int(sec * SR), dtype=np.float32)


def _build(durs, gaps, lead=0.3, tail=0.3):
    """durs 초짜리 소리 조각들을 gaps 초 쉼으로 이어 붙임. 반환 (wav, 실제 쉼 중앙 시각들)"""
    parts, centers, pos = [_sil(lead)], [], lead
    for i, d in enumerate(durs):
        parts.append(_tone(d, 150 + 40 * i))
        pos += d
        if i < len(durs) - 1:
            parts.append(_sil(gaps[i]))
            centers.append(pos + gaps[i] / 2)
            pos += gaps[i]
    parts.append(_sil(tail))
    return np.concatenate(parts), centers


def test_find_pauses():
    x, centers = _build([1.0, 2.0, 1.5], [0.4, 0.3])
    gaps, start, end = qwen.find_pauses(x, SR)
    assert len(gaps) == 2
    assert start == pytest.approx(0.3, abs=0.03) and end == pytest.approx(0.3 + 1 + 0.4 + 2 + 0.3 + 1.5, abs=0.03)
    for (a, b), c in zip(gaps, centers):
        assert (a + b) / 2 == pytest.approx(c, abs=0.03)


def test_short_pause_ignored():
    x, _ = _build([1.0, 1.0], [0.04])
    gaps, _, _ = qwen.find_pauses(x, SR)
    assert gaps == []


def test_expected_boundaries():
    b = qwen.expected_boundaries([10, 20, 10], 0.0, 4.0)
    assert b == pytest.approx([1.0, 3.0])


def test_choose_cuts_picks_real_pauses():
    # 가중치(음절)가 실제 길이와 어느 정도 비슷하게 어긋나 있어도 가장 가까운 쉼을 고른다
    x, centers = _build([1.0, 2.0, 1.5, 1.0], [0.4, 0.3, 0.5])
    cuts = qwen.choose_cuts(x, SR, [12, 22, 15, 12])
    assert len(cuts) == 3
    for c, real in zip(cuts, centers):
        assert c == pytest.approx(real, abs=0.05)


def test_choose_cuts_skips_inner_pause():
    # 문장 안에 쉼(쉼표)이 하나 더 있어도 문장 수(3)만큼의 경계만, 예상 위치에 가까운 쪽으로
    x, centers = _build([1.0, 0.8, 1.2, 1.5], [0.35, 0.15, 0.4])   # 2번째 쉼(0.15)은 문장 안 쉼표
    cuts = qwen.choose_cuts(x, SR, [10 + 8, 12, 15])               # 문장1=조각0+1, 문장2=조각2, 문장3=조각3
    assert len(cuts) == 2
    assert cuts[0] == pytest.approx(centers[0], abs=0.6) or cuts[0] == pytest.approx(centers[1], abs=0.1)
    assert cuts[1] == pytest.approx(centers[2], abs=0.05)


def test_choose_cuts_without_pauses_falls_back():
    x = _tone(6.0)                              # 쉼이 전혀 없음 -> 예상 위치 근처 대체 지점
    cuts = qwen.choose_cuts(x, SR, [10, 10, 10])
    assert len(cuts) == 2 and cuts[0] < cuts[1]
    assert cuts[0] == pytest.approx(2.0, abs=0.6) and cuts[1] == pytest.approx(4.0, abs=0.6)


def test_split_wav_pieces():
    x, centers = _build([1.0, 2.0, 1.5], [0.4, 0.3])
    pieces = qwen.split_wav(x, SR, centers)
    assert len(pieces) == 3
    for p, d in zip(pieces, [1.0, 2.0, 1.5]):
        assert len(p) / SR == pytest.approx(d, abs=0.15)      # 앞뒤 무음은 trim_silence 가 걷어냄


def test_single_sentence_no_cut():
    x, _ = _build([2.0], [])
    assert qwen.choose_cuts(x, SR, [20]) == []
    assert len(qwen.split_wav(x, SR, [])) == 1


def test_cut_items_roundtrip(tmp_path):
    x, _ = _build([1.0, 2.0, 1.5], [0.4, 0.3])
    full = tmp_path / "full.wav"
    sf.write(str(full), x, SR, subtype="PCM_16")
    items, cuts = qwen._cut_items(full, ["가나다라", "마바사아자차카타", "파하"], ["가나다라", "마바사아자차카타", "파하"], tmp_path / "cut")
    assert len(cuts) == 2
    assert len(items) == 3 and all(set(i) >= {"text", "spoken", "wav", "duration"} for i in items)
    assert items[1]["duration"] == pytest.approx(2.0, abs=0.15)


def test_refine_cuts_moves_to_true_boundary():
    # 쉼 3개 중 문장 경계는 두 번째(3.05초 근처)뿐. 처음 고른 경계(첫 쉼)가 틀렸을 때 점수로 바로잡는다
    x, centers = _build([0.6, 0.6, 0.6, 0.6], [0.3, 0.3, 0.3])
    true = centers[1]

    def score(i, a, b):                      # 조각이 진짜 경계에 맞을수록 높은 점수
        ref = [(0.0, true), (true, len(x) / SR)][i]
        return 1.0 - min(1.0, abs(a - ref[0]) + abs(b - ref[1]))

    out = qwen.refine_cuts(x, SR, [centers[0]], score)
    assert out[0] == pytest.approx(true, abs=0.05)


def test_refine_cuts_keeps_good_cut():
    x, centers = _build([1.0, 1.0, 1.0], [0.3, 0.3])
    out = qwen.refine_cuts(x, SR, [centers[0]], lambda i, a, b: 1.0)
    assert out == [centers[0]]


def test_unavailable_without_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RECAP_QWEN_PYTHON", str(tmp_path / "nope.exe"))
    with pytest.raises(qwen.QwenUnavailable):
        qwen.run_cli("안녕", "x", 1, tmp_path / "o.wav")


@pytest.mark.live
@pytest.mark.skipif(not qwen.python_exe().exists(), reason="qwen 환경 없음")
def test_live_two_sentences(tmp_path):
    r = qwen.synth_sentences(["오늘은 동네 이야기를 해볼게.", "어제 비가 많이 왔다고 해."], tmp_path, seed=1)
    assert len(r["items"]) == 2 and r["meta"]["tries"] <= qwen.MAX_TRIES
    assert all(1.0 < it["duration"] < 8.0 for it in r["items"])


def test_refine_cuts_keeps_pause_cut_against_small_valley_gain():
    """쉼 안의 경계는 말 중간 골짜기(낱말 속 짧은 약해짐)로 옮기지 않는다 — 받아쓰기 흔들림만큼의 차이로는.
    크게 좋아지면(VALLEY_MARGIN 이상) 옮긴다."""
    dip = np.full(int(0.03 * SR), 0.0, dtype=np.float32)
    x = np.concatenate([_sil(0.3), _tone(1.0), _tone(0.25, 260), dip, _tone(0.25, 260), _sil(0.4), _tone(1.0, 330), _sil(0.3)])
    valley, pause = 0.3 + 1.0 + 0.25 + 0.015, 0.3 + 1.0 + 0.25 + 0.03 + 0.25 + 0.2

    def scorer(gain):
        def score(i, a, b):
            near = abs((b if i == 0 else a) - valley) < 0.04
            return 1.0 + (gain if near and i == 0 else 0.0)
        return score

    assert qwen.refine_cuts(x, SR, [pause], scorer(0.02))[0] == pytest.approx(pause, abs=0.02)
    assert qwen.refine_cuts(x, SR, [pause], scorer(0.2))[0] == pytest.approx(valley, abs=0.04)


def test_end_level_detects_piece_cut_mid_word(tmp_path):
    """조각 끝이 말 중간이면(소리가 남은 채 끝남) END_CLIP_DB 보다 크고, 말이 잦아든 뒤 끝나면 작다."""
    from recap_shorts.voice import tts
    cut, ok = tmp_path / "cut.wav", tmp_path / "ok.wav"
    sf.write(str(cut), np.concatenate([_sil(0.1), _tone(0.5)]), SR, subtype="PCM_16")
    sf.write(str(ok), np.concatenate([_sil(0.1), _tone(0.5), _sil(0.08)]), SR, subtype="PCM_16")
    assert tts.end_level_db(cut) > tts.END_CLIP_DB > tts.end_level_db(ok)
