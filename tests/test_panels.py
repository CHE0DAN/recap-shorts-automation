"""칸 쌓기 그림: panel_boxes 감지, pick_panels 파싱·정리, step_assets 연결."""
import json

import numpy as np
from PIL import Image, ImageDraw

from recap_shorts import pipeline as P
from recap_shorts.images import captures, regions
from tests.pipeline.fakes import FakeDeps, png

SRC = {"gallery": "dcbest", "no": 1, "url": "https://x/1", "minor": False}


def stack(path, n=6, w=300, ph=170, sep=8, gray=235):
    """무늬 있는 칸 n장을 회색 줄로 이은 그림."""
    rng = np.random.default_rng(1)
    h = n * ph + (n - 1) * sep
    a = np.full((h, w, 3), gray, np.uint8)
    for k in range(n):
        y = k * (ph + sep)
        a[y:y + ph] = rng.integers(0, 255, (ph, w, 3), dtype=np.uint8)
    Image.fromarray(a).save(path)
    return [(0, k * (ph + sep), w, k * (ph + sep) + ph) for k in range(n)]


def test_panel_boxes_on_stack(tmp_path):
    want = stack(tmp_path / "s.png")
    assert captures.panel_boxes(tmp_path / "s.png") == want


def test_panel_boxes_none_for_short_or_plain(tmp_path):
    Image.fromarray(np.random.default_rng(2).integers(0, 255, (300, 300, 3), dtype=np.uint8)).save(tmp_path / "a.png")
    assert captures.panel_boxes(tmp_path / "a.png") is None
    Image.fromarray(np.random.default_rng(3).integers(0, 255, (2000, 300, 3), dtype=np.uint8)).save(tmp_path / "b.png")
    assert captures.panel_boxes(tmp_path / "b.png") is None
    im = Image.new("RGB", (300, 2000), (255, 255, 255))      # 글줄 같은 줄무늬(사이가 8px 미만)
    d = ImageDraw.Draw(im)
    for y in range(0, 2000, 14):
        d.rectangle((10, y, 290, y + 7), fill=(30, 30, 30))
    im.save(tmp_path / "c.png")
    assert captures.panel_boxes(tmp_path / "c.png") is None


def test_panel_boxes_none_for_comment_list(tmp_path):
    im = Image.new("RGB", (300, 2000), (255, 255, 255))      # 짧은 댓글 + 흰 틈
    d = ImageDraw.Draw(im)
    for y in range(0, 2000, 70):
        for x in range(10, 290, 9):
            d.rectangle((x, y + 5, x + 4, y + 50), fill=(30, 30, 30))
    im.save(tmp_path / "d.png")
    assert captures.panel_boxes(tmp_path / "d.png") is None


SENTS = [{"index": 0, "role": "hook", "text": "훅", "hint": ""},
         {"index": 1, "role": "body", "text": "첫 문장", "hint": ""},
         {"index": 2, "role": "body", "text": "둘째 문장", "hint": ""}]


def test_pick_panels_parse_clamp_dedupe(tmp_path):
    boxes = stack(tmp_path / "s.png")
    seen = {}

    def read(images, instruction):
        seen["n"], seen["ins"] = len(images), instruction
        return ('```json\n{"picks": [{"sentence": 0, "panels": [1]}, {"sentence": 1, "panels": [2, 9, 3, 4]},'
                '{"sentence": 2, "panels": [2, 5]}], "faces": {"2": true}, "ids": [5],}\n```')
    r = regions.pick_panels(tmp_path / "s.png", boxes, SENTS, read)
    assert seen["n"] == 6 and "훅" not in seen["ins"]
    # 문장 1 은 [2, 3, 4] 중 얼굴 있는 2번을 뒤로 → 3, 4 / 문장 2 는 [2, 5] 둘 다 얼굴·아이디라 한 칸(2번)만
    assert r["picks"] == [{"sentence": 1, "panels": [3, 4]}, {"sentence": 2, "panels": [2]}]
    assert r["faces"] == {2: True, 3: False, 4: False} and r["ids"] == {2: False, 3: False, 4: False}
    r = regions.pick_panels(tmp_path / "s.png", boxes, SENTS, read, max_total=2)
    # 상한이 작으면 문장마다 한 칸씩 먼저(앞 문장이 두 칸을 다 먹지 않게)
    assert r["picks"] == [{"sentence": 1, "panels": [3]}, {"sentence": 2, "panels": [2]}]


def test_pick_panels_batches(tmp_path, monkeypatch):
    boxes = stack(tmp_path / "s.png", n=5)
    monkeypatch.setattr(regions, "PANEL_BATCH", 2)
    calls = []

    def read(images, instruction):
        calls.append(len(images))
        return {"picks": [{"sentence": 1, "panels": [len(images) - 1]}], "faces": {}, "ids": {}}
    r = regions.pick_panels(tmp_path / "s.png", boxes, SENTS, read, per_sentence=3)
    assert calls == [2, 2, 1] and r["picks"] == [{"sentence": 1, "panels": [1, 3, 4]}]


def make_ctx(tmp_path, deps, stacked=True):
    store = P.JobStore(tmp_path)
    job = store.create(dict(SRC), {"no_image_gen": True, "entity_images": False})
    d = job.dir
    (d / "post").mkdir(parents=True, exist_ok=True)
    if stacked:
        stack(d / "post" / "img_1.png", n=6, w=300, ph=170)
    else:
        png(d / "post" / "img_1.png", (300, 300))
    (d / "topic.json").write_text(json.dumps({"attachments": [{"n": 1, "file": "post/img_1.png"}]}), encoding="utf-8")
    (d / "script_final").mkdir()
    (d / "voice").mkdir()
    (d / "script_final/script.json").write_text(json.dumps({"title_lines": ["t"], "sentences": [
        {"text": "첫 문장", "image_hint": ""}, {"text": "둘째 문장", "image_hint": ""}]}), encoding="utf-8")
    (d / "voice/timings.json").write_text(json.dumps({"sentences": [
        {"index": 0, "role": "hook", "text": "훅"}, {"index": 1, "role": "body", "text": "첫 문장"},
        {"index": 2, "role": "body", "text": "둘째 문장"}]}), encoding="utf-8")
    return job, P.Ctx(job, "assets", deps)


class PanelDeps(FakeDeps):
    def __init__(self, picks):
        super().__init__()
        self.picks = picks
        self.got = None
        self.located = []

    def pick_panels(self, src, boxes, sentences):
        self.got = (len(boxes), [s["index"] for s in sentences])
        return self.picks

    def locate_regions(self, path, wants):
        self.located.append(path.name)
        return {"parts": [None] * len(wants), "private": [(5, 5, 40, 40)] if path.name.endswith("_02.png") else [],
                "size": [300, 170]}


def test_step_assets_uses_picked_panels(tmp_path):
    deps = PanelDeps({"picks": [{"sentence": 1, "panels": [2, 3]}, {"sentence": 2, "panels": [5]}],
                      "faces": {3: True}, "ids": {}})
    job, c = make_ctx(tmp_path, deps)
    P.step_assets(c)
    ents = json.loads((job.dir / "assets/assets.json").read_text(encoding="utf-8"))
    cap = [e for e in ents if e["kind"] == "cap"]
    assert deps.got == (6, [1, 2]) and len(deps.located) == 3
    assert [(e["sentence"], e["panel"]) for e in cap] == [(1, 2), (1, 3), (2, 5)]
    assert [e["file"] for e in cap] == ["assets/cap/c01_s01.png", "assets/cap/c01_s01_2.png", "assets/cap/c01_s02.png"]
    assert all(e["role"] == "focus" and (job.dir / e["file"]).is_file() and (job.dir / e["src"]).is_file() for e in cap)
    assert cap[0]["blurred"] and "자동 가림 1곳" in cap[0]["review_reason"] and not cap[0]["unblurred_risk"]
    assert cap[1]["needs_review"] and cap[1]["unblurred_risk"] and "가림 확인" in cap[1]["review_reason"]
    # crop 은 칸 그림(src) 기준이라 None, 원본 속 위치는 panel_box — 원본 좌표를 crop 에 두면 '가리기 적용'이 검은 카드가 됐다
    assert cap[2]["review_reason"] is None and cap[2]["crop"] is None and cap[2]["panel_box"] == [0, 5 * 178, 300, 5 * 178 + 170]
    assert not any("_p1" in e["file"] for e in ents)


def test_step_assets_falls_back_without_picks(tmp_path):
    deps = PanelDeps({"picks": []})
    job, c = make_ctx(tmp_path, deps)
    P.step_assets(c)
    ents = json.loads((job.dir / "assets/assets.json").read_text(encoding="utf-8"))
    cap = [e for e in ents if e["kind"] == "cap"]
    assert cap and all("panel" not in e for e in cap)
    assert any("_p" in e["file"] for e in cap)               # 기존 조각 카드


def test_step_assets_non_stack_unchanged(tmp_path):
    deps = PanelDeps({"picks": [{"sentence": 1, "panels": [0]}]})
    job, c = make_ctx(tmp_path, deps, stacked=False)
    P.step_assets(c)
    assert deps.got is None


def test_pick_panels_prefers_panels_without_faces(tmp_path):
    boxes = stack(tmp_path / "s.png")

    def read(images, instruction):
        assert "모자이크" in instruction
        return {"picks": [{"sentence": 1, "panels": [0, 1]}, {"sentence": 2, "panels": [2, 3]}],
                "faces": {"0": True, "2": True, "3": True}, "ids": {}}
    r = regions.pick_panels(tmp_path / "s.png", boxes, SENTS, read)
    # 문장 1: 얼굴 없는 1번이 먼저, 얼굴 있는 0번은 두 번째로 안 씀 / 문장 2: 둘 다 얼굴이면 한 칸만
    assert r["picks"] == [{"sentence": 1, "panels": [1]}, {"sentence": 2, "panels": [2]}]
