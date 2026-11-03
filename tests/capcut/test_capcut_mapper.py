"""썰쇼츠 타임라인 -> CapCut 초안: 렌더와 같은 배치·시간인지, 초안 폴더가 온전한지(임시 폴더에만 쓴다)."""
import json
import math
import struct
import wave

import pytest
from PIL import Image

from recap_shorts.capcut import desktop, export, mapper
from recap_shorts.render import captions as cap
from recap_shorts.render import layout as L

INTRO = {"style": "card", "pop_lead_s": 0.15, "pop_min_s": 0.6, "pop_before_cut_min_s": 0.5, "pop_s": 0.067,
         "pop_text_scale": 1.084, "ref_box_h": 1028, "panel_h_start": 1028, "panel_h_end": 792,
         "lines": ["빵에 얼굴이 나온다며", "소송 건 전직 시장"], "label": "| 테스트 게시판 >", "t_pop": 0.8, "t_cut": 1.5}


def _wav(path, sec, freq=440.0, amp=0.3):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        n = int(24000 * sec)
        w.writeframes(b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / 24000))) for i in range(n)))


def _job(tmp_path, *, intro=True):
    job = tmp_path / "job"
    (job / "assets").mkdir(parents=True)
    (job / "voice").mkdir()
    Image.new("RGB", (800, 1600), (200, 30, 30)).save(job / "assets" / "tall.png")      # 세로로 긴 캡처 → 4:3 으로 잘림
    Image.new("RGB", (1200, 900), (30, 30, 200)).save(job / "assets" / "wide.png")
    Image.new("RGBA", (300, 300), (0, 200, 0, 255)).save(job / "assets" / "meme.png")
    _wav(job / "voice" / "voice.wav", 5.5)
    _wav(job / "assets" / "pop.wav", 0.3, 880)
    tl = {
        "fps": 30, "size": [1080, 1920], "duration": 6.0,
        "title_lines": ["빵에 얼굴이 나온다며", "소송 건 전직 시장"],
        "hook": {"text": "빵에 얼굴이 나온다며 소송 건 전직 시장", "start": 0.0, "end": 1.5},
        "shots": [{"file": "assets/tall.png", "start": 0.0, "end": 1.5, "motion": "zoom_in", "focus": [0.5, 0.2]},
                  {"file": "assets/wide.png", "start": 1.5, "end": 3.0, "motion": "zoom_in", "focus": [0.5, 0.5]},
                  {"file": "assets/tall.png", "start": 3.0, "end": 4.5, "motion": "enter", "focus": [0.5, 0.5]},
                  {"file": "assets/wide.png", "start": 4.5, "end": 5.9, "motion": "static", "focus": [0.5, 0.5]}],
        "captions": [{"text": "동네 전직 시장 김도현씨가", "start": 1.0, "end": 2.6, "emphasis": "김도현씨"},
                     {"text": "빵집을 고소했대", "start": 2.6, "end": 4.4, "emphasis": None},
                     {"text": "빵이 자기를 닮았다더라고", "start": 4.4, "end": 6.0, "emphasis": ""}],
        "audio": {"voice": "voice/voice.wav", "bgm": None, "voice_offset_s": 0.2,
                  "sfx": [{"file": "assets/pop.wav", "t": 1.5, "db": -15.0, "id": "pop_02"},
                          {"file": "assets/pop.wav", "t": 1.55, "db": -15.0, "id": "pop_02"},      # 겹침 → 아래 트랙
                          {"file": "assets/pop.wav", "t": 9.0, "db": -15.0, "id": "late"}]},       # 영상 끝 뒤 → 뺌
        "options": {"snap_captions_to_cuts": True},
        "overlays": [{"kind": "sticker", "file": "assets/meme.png", "start": 3.2, "end": 4.2, "anchor": "box_br",
                      "size_frac": 0.3, "anim": "pop", "meme_id": "pepe"}],
    }
    if intro:
        tl["intro"] = dict(INTRO)
    (job / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    return job, tl


@pytest.fixture
def drafts(tmp_path, monkeypatch):
    d = tmp_path / "com.lveditor.draft"
    d.mkdir()
    (d / "root_meta_info.json").write_text(json.dumps({"all_draft_store": [{"draft_id": "OTHER", "draft_name": "남의 초안",
                                                                              "draft_fold_path": str(d / "other")}],
                                                       "draft_ids": 1, "root_path": str(d)}), encoding="utf-8")
    monkeypatch.setattr(desktop, "capcut_running", lambda: False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "no_local"))
    return d


def _content(r):
    return json.loads((__import__("pathlib").Path(r["draft_dir"]) / "draft_content.json").read_text(encoding="utf-8"))


def _track(c, name):
    return next(t for t in c["tracks"] if t["name"] == name)


def _mat(c, mid):
    return next(m for g in c["materials"].values() for m in g if isinstance(m, dict) and m.get("id") == mid)


def test_export_writes_valid_registered_draft(tmp_path, drafts):
    job, _ = _job(tmp_path)
    r = export.export_job(job, drafts_dir=drafts)
    assert r["check"]["ok"], r["check"]
    assert r["registered"] and r["in_capcut_folder"]
    idx = json.loads((drafts / "root_meta_info.json").read_text(encoding="utf-8"))
    assert [e["draft_name"] for e in idx["all_draft_store"]][1] == "남의 초안"          # 남의 초안은 그대로, 새 초안이 맨 앞
    assert idx["all_draft_store"][0]["draft_fold_path"] == r["draft_dir"]
    c = _content(r)
    assert c["duration"] == 6_000_000 and c["canvas_config"]["width"] == 1080
    for g in ("videos", "audios"):                                                   # 미디어는 모두 초안 안으로 복사
        for m in c["materials"][g]:
            assert m["path"].startswith(__import__("pathlib").Path(r["draft_dir"]).resolve().as_posix())
    assert json.loads((job / "out" / "capcut.json").read_text(encoding="utf-8"))["draft_name"] == r["draft_name"]
    assert not list(drafts.glob(".recap-staging-*"))


def test_pictures_follow_render_layout(tmp_path, drafts):
    job, _ = _job(tmp_path)
    c = _content(export.export_job(job, drafts_dir=drafts, register=False))
    segs = _track(c, "그림")["segments"]
    starts = [s["target_timerange"]["start"] for s in segs]
    assert starts == [0, 1_500_000, 3_000_000, 4_500_000]                        # 인트로 카드가 첫 컷을 가림, 빈틈 없음
    assert segs[-1]["target_timerange"]["start"] + segs[-1]["target_timerange"]["duration"] == 6_000_000   # 마지막 컷은 끝까지
    intro = _mat(c, segs[0]["material_id"])
    assert intro["type"] == "video" and (intro["width"], intro["height"]) == (1080, 810)
    box_ty = (960 - (L.IMAGE_Y0 + L.IMAGE_Y1) / 2) / 960
    for s in segs:
        assert s["clip"]["transform"]["y"] == pytest.approx(box_ty, abs=1e-4)
    shot = _mat(c, segs[1]["material_id"])
    assert shot["type"] == "photo" and shot["width"] / shot["height"] == pytest.approx(4 / 3, abs=0.01)   # 렌더처럼 4:3
    kf = segs[1]["common_keyframes"][0]
    vals = [k["values"][0] for k in kf["keyframe_list"]]
    assert kf["property_type"] == "KFTypeScaleX" and vals[1] / vals[0] == pytest.approx(1.08, abs=1e-3)
    assert segs[2]["common_keyframes"][0]["property_type"] == "KFTypePositionY"       # enter: 올라오기
    assert not segs[3]["common_keyframes"]                                            # static
    mask = _track(c, "그림 상자 밖 가림")["segments"][0]
    assert mask["target_timerange"] == {"start": 0, "duration": 6_000_000}
    order = [t["name"] for t in c["tracks"] if t["type"] == "video"]
    assert order.index("짤") < order.index("그림 상자 밖 가림")                         # 짤도 상자 밖으로 넘치지 않게 가림 아래


def test_texts_match_render(tmp_path, drafts):
    job, tl = _job(tmp_path)
    c = _content(export.export_job(job, drafts_dir=drafts, register=False))
    titles = [json.loads(_mat(c, _track(c, f"제목 {i}줄")["segments"][0]["material_id"])["content"]) for i in (1, 2)]
    assert [t["text"] for t in titles] == tl["title_lines"]
    assert titles[1]["styles"][0]["fill"]["content"]["solid"]["color"] == pytest.approx([1.0, 212 / 255, 0.0], abs=1e-3)
    segs = _track(c, "자막")["segments"]
    assert segs[0]["target_timerange"]["start"] == 1_500_000                         # 훅·인트로 동안 자막 없음
    first = json.loads(_mat(c, segs[0]["material_id"])["content"])
    size, lines, _ = cap.fit_text("동네 전직 시장 김도현씨가")
    assert first["text"] == "\n".join(lines)                                         # 렌더와 같은 줄바꿈
    emph = [s for s in first["styles"] if s["fill"]["content"]["solid"]["color"] != [1.0, 1.0, 1.0]]
    a, b = emph[0]["range"]
    assert first["text"][a:b].replace("\n", " ") == "김도현씨"
    assert first["styles"][0]["size"] == pytest.approx(size / 5.5, abs=0.01)
    assert first["styles"][0]["strokes"]                                             # 검은 외곽선
    assert segs[0]["clip"]["transform"]["y"] == pytest.approx((960 - (L.CAPTION_Y0 + L.CAPTION_Y1) / 2) / 960, abs=1e-4)


def test_audio_and_stickers(tmp_path, drafts):
    job, _ = _job(tmp_path)
    r = export.export_job(job, drafts_dir=drafts, register=False)
    c = _content(r)
    voice = _track(c, "목소리")["segments"][0]
    assert voice["target_timerange"]["start"] == 200_000 and voice["volume"] == 1.0
    sfx = [t for t in c["tracks"] if t["name"].startswith("효과음")]
    assert len(sfx) == 2 and sum(len(t["segments"]) for t in sfx) == 2               # 겹친 것은 아래 트랙, 끝 뒤 것은 뺌
    st = _track(c, "짤")["segments"][0]
    props = {k["property_type"] for k in st["common_keyframes"]}
    assert props == {"KFTypeScaleX", "KFTypeAlpha"}
    assert st["clip"]["transform"]["x"] > 0 and st["clip"]["transform"]["y"] < (960 - L.IMAGE_Y0) / 960   # 상자 오른쪽 아래
    modes = {x["element"]: x["mode"] for x in r["report"]}
    assert modes["인트로 카드"] == "approx" and modes["자막"] == "native"


def test_hook_band_without_intro(tmp_path, drafts):
    job, _ = _job(tmp_path, intro=False)
    c = _content(export.export_job(job, drafts_dir=drafts, register=False))
    hook = _track(c, "훅 띠")["segments"][0]
    assert hook["target_timerange"] == {"start": 0, "duration": 1_500_000}
    assert _track(c, "그림")["segments"][0]["target_timerange"]["start"] == 0
    assert _track(c, "자막")["segments"][0]["target_timerange"]["start"] == 1_500_000


def test_no_registration_while_capcut_runs(tmp_path, drafts, monkeypatch):
    monkeypatch.setattr(desktop, "capcut_running", lambda: True)
    job, _ = _job(tmp_path)
    r = export.export_job(job, drafts_dir=drafts)
    assert not r["registered"] and any("실행 중" in w for w in r["warnings"])
    assert (drafts / r["draft_name"] / "draft_content.json").is_file()


def test_caption_layout_matches_render():
    size, text, runs = mapper.caption_layout("빵집은 자기 얼굴을  빵에 그대로 그린 게 뭔 잘못이냐고", "자기 얼굴")
    fit = cap.fit_text("빵집은 자기 얼굴을 빵에 그대로 그린 게 뭔 잘못이냐고")
    assert (size, text.split("\n")) == (fit[0], fit[1])
    assert len(runs) == 1 and text[runs[0][0]:runs[0][1]] == "자기 얼굴"
