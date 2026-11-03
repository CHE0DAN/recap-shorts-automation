import pytest

from recap_shorts.voice import asr, tts
from recap_shorts.voice.spoken import native_det, to_spoken


@pytest.mark.parametrize("src,want", [
    ("9월 25일", "구월 이십오일"),
    ("6월 10월", "유월 시월"),
    ("5대 0", "오 대 영"),
    ("0대 5로", "영 대 오로"),
    ("5:0", "오 대 영"),
    ("5 : 0", "오 대 영"),
    ("7이닝", "칠이닝"),
    ("4안타", "사안타"),
    ("2루타", "이루타"),
    ("5연패", "오연패"),
    ("3명", "세 명"),
    ("10억 원", "십억 원"),
    ("2억 5,000만 원", "이억 오천만 원"),
    ("0.362", "영 점 삼육이"),
    ("타율 0.362", "타율 영 점 삼육이"),
    ("36.2%", "삼십육 점 이 퍼센트"),
    ("50%", "오십 퍼센트"),
    ("NTT", "엔티티"), ("JR", "제이알"), ("KBO", "케이비오"), ("AG", "에이지"),
    ("1개 2명 3살 20살 21살", "한 개 두 명 세 살 스무 살 스물한 살"),
    ("3시 30분", "세 시 삼십분"),
    ("2시간", "두 시간"),
    ("1번째 2번째 3번째 10번째", "첫 번째 두 번째 세 번째 열 번째"),
    ("4마리 5잔 6병 7권 8장", "네 마리 다섯 잔 여섯 병 일곱 권 여덟 장"),
    ("3개월", "삼개월"),
    ("3시즌", "삼시즌"),
    ("2026년", "이천이십육년"),
    ("70킬로", "칠십킬로"),
    ("100명", "백명"),
    ("0개", "영개"),
])
def test_examples(src, want):
    assert to_spoken(src) == want


@pytest.mark.parametrize("src,want", [
    ("0", "영"), ("10", "십"), ("11", "십일"), ("20", "이십"), ("99", "구십구"), ("100", "백"),
    ("1000", "천"), ("10000", "만"), ("100000000", "일억"), ("1억", "일억"), ("1,000", "천"),
])
def test_boundaries_sino(src, want):
    assert to_spoken(src) == want


def test_boundaries_native():
    assert [to_spoken(f"{n}개") for n in (1, 10, 11, 20, 99)] == ["한 개", "열 개", "열한 개", "스무 개", "아흔아홉 개"]
    assert to_spoken("100개") == "백개"
    assert native_det(2) == "두"


def test_original_untouched_in_items(tmp_path):
    if not (tts.model_dir() / "vocoder.int8.onnx").exists():
        pytest.skip("Supertonic 모델 없음")
    it = tts.synth_sentences(["3명이 2루타를 쳤다"], tmp_path, sid=7)[0]
    assert it["text"] == "3명이 2루타를 쳤다" and it["spoken"] == "세 명이 이루타를 쳤다"
    r, _ = asr.check_items([it])
    assert r[0]["match"] >= 0.8


def test_pronounce_dictionary():
    from recap_shorts.voice.spoken import PRONOUNCE, to_spoken
    assert PRONOUNCE                                     # 낱말 사전이 비어 있으면 이 시험은 아무것도 확인하지 못한다
    for src, want in PRONOUNCE.items():                  # 사전의 모든 낱말이 문장 안에서 바뀐다
        assert to_spoken(f"{src} 당했다") == f"{want} 당했다"
