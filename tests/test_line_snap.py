"""캡처 카드의 자르는 선·빨간 테두리가 글줄을 가르지 않는지 — 선이 글자에 가리면 안 된다."""
import numpy as np
from PIL import Image, ImageDraw

from recap_shorts.images import regions as R
from recap_shorts.images.captures import make_cards_for_image

W, LH, STEP = 660, 24, 40      # 글줄 높이 24, 줄 간격 40 (블라인드 캡처와 비슷)


def page(n_lines=10, cut_bottom=False, scrollbar=True):
    """흰 바탕에 검은 '글줄' 띠. cut_bottom 이면 마지막 줄이 그림 끝에서 반쯤 잘림. 오른쪽 끝에 스크롤바."""
    h = 20 + STEP * n_lines - (STEP - LH) - (LH // 2 if cut_bottom else 0)
    im = Image.new("RGB", (W, h), "white")
    d = ImageDraw.Draw(im)
    for k in range(n_lines):
        y = 20 + STEP * k
        for x in range(32, 520, 18):          # 낱자 모양 띠(가로로 끊긴 글자들)
            d.rectangle((x, y, x + 12, y + LH - 1), fill=(20, 20, 20))
    if scrollbar:
        d.rectangle((W - 6, 0, W - 3, h - 1), fill=(120, 120, 120))
    return im


def cuts_a_line(im, y):
    return any(a < y < b for a, b in R.text_lines(im))


def test_text_lines_ignore_scrollbar():
    im = page(6)
    assert R.text_lines(im) == [(20 + STEP * k, 20 + STEP * k + LH) for k in range(6)]


def test_snap_crop_moves_edges_into_gaps():
    im = page(10)
    # 위 선이 3번째 줄 아래쪽 1/4, 아래 선이 7번째 줄 위쪽 3/4 를 지나는 상자
    crop = (0, 20 + STEP * 2 + 18, W, 20 + STEP * 6 + 18)
    out = R.snap_crop(im, crop)
    assert not cuts_a_line(im, out[1]) and not cuts_a_line(im, out[3])
    assert out[1] >= 20 + STEP * 2 + LH          # 덜 보이던 위 줄은 뺌
    assert out[3] >= 20 + STEP * 6 + LH          # 반 넘게 보이던 아래 줄은 다 담음


def test_snap_crop_keeps_target_and_drops_cut_edge_line():
    im = page(8, cut_bottom=True)
    h = im.height
    keep = (32, 20 + STEP * 5, 520, h)          # 찾은 부분이 잘린 끝 줄까지
    out = R.snap_crop(im, (0, 20 + STEP * 5 - 10, W, h), keep=keep)
    assert out[3] <= 20 + STEP * 7               # 원본에서 잘린 끝 줄은 뺌
    assert out[1] <= 20 + STEP * 5               # 찾은 부분 첫 줄은 그대로
    assert not cuts_a_line(im, out[1]) and not cuts_a_line(im, out[3])


def test_highlight_stroke_sits_between_lines():
    im = page(10)
    y_top, y_bot = 20 + STEP * 3, 20 + STEP * 4 + LH
    box = (40, y_top + 8, 300, y_bot - 8)        # 비전 상자가 글줄 안쪽을 지나는 경우
    hb = R.snap_box_to_lines(im, box)
    st = R.stroke_for(W)
    ink = np.asarray(im.convert("L")) < 128
    ink[:, W - 20:] = False                       # 스크롤바 제외
    # 테두리가 그려질 띠(위·아래 st 줄, 좌우 st 열)에 글자 화소가 없어야 한다
    for rows in (slice(hb[1], hb[1] + st), slice(hb[3] - st + 1, hb[3] + 1)):
        assert not ink[rows, hb[0]:hb[2] + 1].any()
    for cols in (slice(hb[0], hb[0] + st), slice(hb[2] - st + 1, hb[2] + 1)):
        assert not ink[hb[1]:hb[3] + 1, cols].any()
    assert hb[1] < y_top and hb[3] >= y_bot and hb[2] >= 520 - 2   # 걸친 두 줄을 끝까지 담음


def test_private_box_in_gap_covers_nearest_line():
    """비전 상자가 닉네임 줄 바로 위 빈 곳에 놓여도 그 줄을 끝까지 덮고, 다음 줄은 건드리지 않는다."""
    im = Image.new("RGB", (W, 200), (24, 24, 24))          # 어두운 바탕(블라인드 댓글)
    d = ImageDraw.Draw(im)
    top = 40
    for x in range(40, 150, 14):                            # 회사 이름 낱말
        d.rectangle((x, top, x + 9, top + LH - 1), fill=(200, 200, 200))
    for x in range(164, 300, 14):                           # 닉네임 낱말(앞 낱말과 14px 띄움)
        d.rectangle((x, top, x + 9, top + LH - 1), fill=(200, 200, 200))
    for x in range(40, 520, 14):                            # 본문 줄
        d.rectangle((x, top + 40, x + 9, top + 40 + LH - 1), fill=(240, 240, 240))
    (x0, y0, x1, y1), = R.snap_private(im, [(170, top - 14, 250, top - 2)])
    assert y0 <= top and y1 >= top + LH
    assert y1 < top + 40                           # 다음 줄(본문) 위
    assert x1 >= 300 and x0 > 150                  # 걸친 낱말 끝까지, 옆 낱말(회사 이름)은 그대로


def test_private_box_partly_on_line_gets_full_height():
    im = page(6)
    line2 = (20 + STEP * 2, 20 + STEP * 2 + LH)
    (x0, y0, x1, y1), = R.snap_private(im, [(100, line2[0] + 10, 200, line2[0] + 20)])
    assert y0 <= line2[0] and y1 >= line2[1]
    assert y0 > 20 + STEP + LH and y1 < 20 + STEP * 3     # 위아래 줄은 그대로


def test_focus_crop_end_to_end(tmp_path):
    im = page(10, cut_bottom=True)
    src = tmp_path / "a.png"
    im.save(src)
    crop, hl = R.focus_crop(src, (40, 20 + STEP * 4 + 6, 300, 20 + STEP * 4 + 20))   # 한 줄짜리 가는 상자
    assert hl is not None                          # 가늘어서 위아래를 넓힘 → 테두리로 표시
    assert crop[1] <= hl[1] and crop[3] >= hl[3]
    assert not cuts_a_line(im, crop[1]) and not cuts_a_line(im, crop[3])


def test_piece_cards_drop_cut_last_line(tmp_path):
    im = page(30, cut_bottom=True)                # 세로로 길어 두 조각 이상
    src = tmp_path / "long.png"
    im.save(src)
    cards = make_cards_for_image(src, tmp_path / "out", "c01")
    assert len(cards) >= 2
    last = cards[-1]["crop"]
    assert last[3] < im.height and not cuts_a_line(im, last[3])


def test_private_name_box_half_on_text_line_stays_on_name():
    """닉네임 상자가 아래 본문 줄에 반쯤 걸쳐도 본문 줄은 가리지 않는다(닉네임이 두 줄에 걸친 캡처)."""
    im = page(6)
    name, text = (20, 20 + LH), (20 + STEP, 20 + STEP + LH)
    (x0, y0, x1, y1), = R.snap_private(im, [(100, name[0] - 4, 200, text[0] + LH // 2)])
    assert y0 <= name[0] and y1 >= name[1]
    assert y1 <= text[0]                            # 본문 줄 위에서 멈춤


def test_private_large_box_only_grows():
    """얼굴·사진 같은 큰 상자는 줄여서 드러내지 않는다."""
    im = page(6)
    box = (100, 10, 300, 20 + STEP * 3)
    (x0, y0, x1, y1), = R.snap_private(im, [box])
    assert y0 <= box[1] and y1 >= box[3] and x0 <= box[0] and x1 >= box[2]


def test_private_box_on_blurred_name_stays():
    """캡처 때 이미 흐린 닉네임 줄(글줄로 안 잡히는 옅은 무늬)에 놓인 상자는 아래 본문 줄로 옮기지 않는다."""
    from PIL import ImageFilter
    im = Image.new("RGB", (W, 200), (248, 248, 248))
    d = ImageDraw.Draw(im)
    top = 40
    for x in range(40, 200, 14):                            # 닉네임 낱말 → 흐리게(옅은 파란 번짐)
        d.rectangle((x, top, x + 9, top + LH - 1), fill=(200, 220, 245))
    im = im.filter(ImageFilter.GaussianBlur(4))
    d = ImageDraw.Draw(im)
    for x in range(40, 520, 14):                            # 본문 줄(진한 글자)
        d.rectangle((x, top + 40, x + 9, top + 40 + LH - 1), fill=(30, 30, 30))
    box = (36, top - 2, 210, top + LH + 2)
    (x0, y0, x1, y1), = R.snap_private(im, [box])
    assert (x0, y0, x1, y1) == box                   # 그대로
    assert y1 < top + 40                             # 본문 줄 위


def test_word_span_grows_to_word_gaps():
    """상자 끝이 낱말 중간(글자 사이 빈칸 2~7)이면 낱말 사이 빈칸(9 이상)까지 넓힌다. 낱말 경계면 그대로."""
    cols = np.zeros(200, dtype=bool)
    for a, b in ((10, 30), (34, 54), (70, 90), (93, 113), (130, 150)):    # 낱말 '■■' 들: 안쪽 3~4, 사이 16~17
        cols[a:b] = True
    assert R._word_span(cols, 40, 100) == (10, 113)      # 양쪽 다 낱말 중간 → 그 낱말 끝까지
    assert R._word_span(cols, 60, 120) == (70, 113)      # 왼쪽은 빈칸에서 시작 → 그대로
    assert R._word_span(cols, 160, 200) == (160, 200)    # 글자 없음 → 그대로


def test_keep_off_text_trims_partial_text_line_only():
    """미리 흐린 캡처의 아이디 상자: 옮기지 않고, 반도 안 걸친 진한 글줄은 빼고, 반 넘게 걸친 줄은 그대로 덮는다."""
    im = Image.new("RGB", (W, 200), (248, 248, 248))
    d = ImageDraw.Draw(im)
    top = 80
    for x in range(40, 520, 14):                            # 본문 줄(진한 글자)
        d.rectangle((x, top, x + 9, top + LH - 1), fill=(30, 30, 30))
    assert R.keep_off_text(im, (30, 40, 300, 70)) == (30, 40, 300, 70)            # 글줄 없음 → 그대로(옮기지 않음)
    x0, y0, x1, y1 = R.keep_off_text(im, (30, 40, 300, top + 4))                   # 본문 줄 위쪽만 살짝 걸침
    assert y1 <= top and y0 == 40
    assert R.keep_off_text(im, (30, top - 2, 300, top + LH + 2)) == (30, top - 2, 300, top + LH + 2)   # 줄을 덮은 상자


def test_overlap_ratio():
    assert R.overlap_ratio((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert R.overlap_ratio((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(R.overlap_ratio((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-9
