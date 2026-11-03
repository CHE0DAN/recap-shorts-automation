"""대본 속 대상(캐릭터·동물 등) 사진 찾기 — 네트워크·Gemini 는 전부 가짜."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from recap_shorts import pipeline as P
from recap_shorts.collect.http import Blocked
from recap_shorts.images import entities as E
from tests.pipeline.fakes import FakeDeps
from tests.pipeline.test_pipeline import go, make

FIX = Path(__file__).parent / "fixtures" / "entities"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def png_bytes(size=(400, 300), color=(200, 90, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class Resp:
    def __init__(self, content: bytes):
        self.content, self.url, self.final_url, self.status = content, "", "", 200

    @property
    def text(self):
        return self.content.decode("utf-8")


class FakeClient:
    """routes: {url 앞부분: bytes | dict}. 등록 안 된 주소는 404 Blocked. 불러 본 주소를 calls 에 남긴다."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def fetch(self, url, *, check_robots=True, use_cache=True, timeout=None):
        self.calls.append(url)
        for prefix, val in self.routes.items():
            if url.startswith(prefix):
                return Resp(val if isinstance(val, bytes) else json.dumps(val, ensure_ascii=False).encode("utf-8"))
        return Blocked(url, "http_404")


SENTS = [{"index": i, "text": t} for i, t in enumerate(
    ["동네 도서관이 새 마스코트를 냈어.", "달래라는 이름이야.", "옛 심부름꾼 억쇠가 모티브래.", "귀엽지?", "근데", "이게",
     "느티 베낀 거래.", "너구리래."])]
SHOWN = ["동네 도서관의 새 마스코트 캐릭터 달래를 소개하는 글"]
YES = {"is_match": "yes", "clear": True, "real_face": False, "mostly_text": False, "note": "ok"}


# ------------------------------------------------------------------ extract
def test_extract_filters_and_validates():
    out = E.extract(SENTS, "제목", SHOWN, text_fn=lambda p: fx("extract_response.json"))
    assert [(o["name_ko"], o["sentence"]) for o in out] == [("느티", 6)]       # 달래(이미 보임)·억쇠(실존 인물)·없는 문장·이상한 종류·중복 제외
    assert out[0]["name_en"] == "Neuti" and out[0]["kind"] == "character" and out[0]["real_person"] is False


def test_extract_caps_at_three_and_survives_garbage():
    many = {"items": [{"sentence": 1, "name_ko": f"이름{i}", "kind": "place"} for i in range(6)]}
    assert len(E.extract(SENTS, "t", [], text_fn=lambda p: many)) == 3
    assert E.extract(SENTS, "t", [], text_fn=lambda p: "not json") == []
    assert E.extract(SENTS, "t", [], text_fn=lambda p: {"items": "x"}) == []

    def boom(p):
        raise RuntimeError("api down")
    assert E.extract(SENTS, "t", [], text_fn=boom) == []


def test_extract_prompt_lists_sentences_and_shown():
    seen = []
    E.extract(SENTS, "제목줄", SHOWN, text_fn=lambda p: seen.append(p) or {"items": []})
    assert "6: 느티 베낀 거래." in seen[0] and "달래" in seen[0] and "제목줄" in seen[0]


def test_default_fns_never_call_gemini_under_pytest():
    assert E.extract(SENTS, "t", []) == []                      # 기본 text_fn 은 시험 중 예외 → []
    with pytest.raises(RuntimeError):
        E._default_vision_fn(b"x", "q")


# ------------------------------------------------------------------ 위키백과
def test_parse_summary_original_and_clean_urls():
    (c,) = E.parse_summary(fx("summary_ko_neuti.json"), "ko")
    assert c.image_url == "https://upload.wikimedia.org/wikipedia/ko/2/29/Neuti_Vol._2.jpg"
    assert c.site == "ko.wikipedia.org" and c.page_url.startswith("https://ko.wikipedia.org/wiki/")


def test_parse_summary_disambiguation_and_no_image():
    assert E.parse_summary(fx("summary_disambig.json"), "ko") == []
    assert E.parse_summary({"type": "standard", "title": "x"}, "en") == []
    svg = {"title": "t", "originalimage": {"source": "https://u/a.svg"}, "thumbnail": {"source": "https://u/a.svg.png"}}
    assert E.parse_summary(svg, "en")[0].image_url == "https://u/a.svg.png"


def test_accept_verdict():
    assert E.accept_verdict(YES)
    assert not E.accept_verdict({**YES, "is_match": "no"})
    assert not E.accept_verdict({**YES, "clear": False})
    assert not E.accept_verdict({**YES, "real_face": True})
    assert not E.accept_verdict({**YES, "mostly_text": True})
    assert not E.accept_verdict({"is_match": "yes"})            # 빠진 칸은 탈락
    assert not E.accept_verdict("yes")


def test_licence_nonfree_for_local_wikipedia_file():
    c = E.Cand(page_url="p", image_url="https://upload.wikimedia.org/wikipedia/en/e/e0/X.jpg", site="en.wikipedia.org")
    assert E.resolve_licence(FakeClient({}), c).licence == "non-free (Wikipedia fair use)"


def test_licence_from_commons_metadata():
    c = E.Cand(page_url="p", image_url="https://upload.wikimedia.org/wikipedia/commons/1/17/Neuti_face.jpg", site="ko.wikipedia.org")
    cl = FakeClient({"https://commons.wikimedia.org/w/api.php": fx("commons_fileinfo_neuti.json")})
    E.resolve_licence(cl, c)
    assert c.licence == "CC BY 2.0" and c.artist == "가상작가" and "File:Neuti_face.jpg" in c.page_url
    assert "titles=File%3ANeuti_face.jpg" in cl.calls[0]


# ------------------------------------------------------------------ 찾기·확인
ENT = {"sentence": 6, "name_ko": "느티", "name_en": "Neuti", "name_ja": "", "kind": "character", "query_hints": [], "why": ""}
KO_SUM = "https://ko.wikipedia.org/api/rest_v1/page/summary/"
IMG = "https://upload.wikimedia.org/wikipedia/ko/2/29/Neuti_Vol._2.jpg"


def test_find_for_entity_accepts_and_records_provenance(tmp_path):
    cl = FakeClient({KO_SUM: fx("summary_ko_neuti.json"), IMG: png_bytes((240, 338))})
    st = E.Stats()
    got = E.find_for_entity(ENT, 1, tmp_path, cl, st, lambda b, i: YES)
    assert got["file"] == "post/ref_1.png" and (tmp_path / got["file"]).is_file()
    r = got["ref"]
    assert r["licence"] == "non-free (Wikipedia fair use)" and r["site"] == "ko.wikipedia.org"
    assert r["image_url"] == IMG and r["page_url"].startswith("https://ko.wikipedia.org/wiki/") and r["retrieved_at"]
    assert st.calls == 1


def test_find_for_entity_rejects_then_stops_after_two_verifies(tmp_path):
    summ = fx("summary_ko_neuti.json")
    cl = FakeClient({KO_SUM: summ, "https://en.wikipedia.org/api/rest_v1/page/summary/": {**summ, "originalimage": {"source": IMG.replace("ko/", "en/")}},
                     "https://upload.wikimedia.org/wikipedia/": png_bytes((500, 400)),
                     "https://commons.wikimedia.org/w/api.php": {"query": {}}})
    n = []

    def no(b, i):
        n.append(1)
        return {**YES, "is_match": "no"}
    st = E.Stats()
    assert E.find_for_entity(ENT, 1, tmp_path, cl, st, no, sources=[lambda: E.wikipedia_candidates(cl, ENT)]) is None
    assert len(n) == 2 and st.calls == 2
    assert not list((tmp_path / "post").glob("ref_*")) if (tmp_path / "post").exists() else True


def test_find_for_entity_skips_tiny_image_without_gemini(tmp_path):
    cl = FakeClient({KO_SUM: fx("summary_ko_neuti.json"), IMG: png_bytes((100, 100))})
    st = E.Stats()
    n = []
    assert E.find_for_entity(ENT, 1, tmp_path, cl, st, lambda b, i: n.append(1) or YES,
                             sources=[lambda: E.wikipedia_candidates(cl, ENT)]) is None
    assert n == [] and st.calls == 0


def test_wikipedia_disambiguation_falls_back_to_search(tmp_path):
    ent = {**ENT, "name_en": ""}
    cl = FakeClient({KO_SUM + "%EB%8A%90%ED%8B%B0_%28%EB%A7%8C%ED%99%94%29": fx("summary_ko_neuti.json"),
                     "https://ko.wikipedia.org/w/api.php": {"query": {"search": [{"title": "느티 (만화)"}]}},
                     KO_SUM + "%EB%8A%90%ED%8B%B0": fx("summary_disambig.json")})
    (c,) = list(E.wikipedia_candidates(cl, ent))
    assert c.site == "ko.wikipedia.org"
    assert any("list=search" in u for u in cl.calls)


# ------------------------------------------------------------------ 전체·캐시
def timings(sents):
    return {"sentences": [{"index": s["index"], "text": s["text"], "role": "body"} for s in sents]}


def test_find_entity_images_end_to_end_and_cache(tmp_path):
    cl = FakeClient({KO_SUM: fx("summary_ko_neuti.json"), IMG: png_bytes((240, 338))})
    topic = {"attachments": [{"summary": s} for s in SHOWN]}
    calls = {"t": 0, "v": 0}

    def tf(p):
        calls["t"] += 1
        return fx("extract_response.json")

    def vf(b, i):
        calls["v"] += 1
        return YES
    res = E.find_entity_images(tmp_path, {"title_lines": ["a", "b"], "hook": "h"}, timings(SENTS), topic, cl, text_fn=tf, vision_fn=vf)
    assert res["found"] == ["느티"] and res["missed"] == [] and res["calls"] == 2 == calls["t"] + calls["v"]
    (e,) = res["entries"]
    assert e["file"] == "assets/cap/r1.png" and e["role"] == "focus" and e["sentence"] == 6 and e["src"] == "post/ref_1.png"
    assert e["kind"] == "cap" and e["status"] == "ok" and e["unblurred_risk"] is False and e["ref"]["licence"]
    assert (tmp_path / "assets/cap/r1.png").is_file()
    again = E.find_entity_images(tmp_path, {}, timings(SENTS), topic, cl, text_fn=tf, vision_fn=vf)   # 다시: 호출 0회
    assert again["calls"] == 0 and calls == {"t": 1, "v": 1} and again["entries"] == res["entries"]


def test_find_entity_images_reports_missed_and_no_card(tmp_path):
    cl = FakeClient({})
    res = E.find_entity_images(tmp_path, {}, timings(SENTS), {"attachments": [{"summary": s} for s in SHOWN]}, cl,
                               text_fn=lambda p: fx("extract_response.json"), vision_fn=lambda b, i: YES, sources_for=lambda ent: [lambda: iter(())])
    assert res["entries"] == [] and res["missed"] == ["느티"] and res["calls"] == 1


# ------------------------------------------------------------------ 파이프라인
class EntDeps(FakeDeps):
    def entity_images(self, job_dir, script, timings, topic):
        self.hit("entity_images")
        cl = FakeClient({KO_SUM: fx("summary_ko_neuti.json"), IMG: png_bytes((240, 338))})
        ext = {"items": [{"sentence": 2, "name_ko": "느티", "name_en": "Neuti", "kind": "character", "real_person": False}]}
        return E.find_entity_images(job_dir, script, timings, topic, cl, text_fn=lambda p: ext, vision_fn=lambda b, i: YES)


def run_to_assets(tmp_path, deps, options=None):
    store, runner, job = make(tmp_path, deps, {"auto_steps": ["read", "script", "scenes", "review"], **(options or {})})
    go(runner, job)
    return job


def test_pipeline_adds_entity_entry_and_description(tmp_path):
    deps = EntDeps()
    job = run_to_assets(tmp_path, deps)
    assert job.state["status"] == "done"
    entries = json.loads((job.dir / "assets/assets.json").read_text(encoding="utf-8"))
    ent = [e for e in entries if e.get("ref")]
    assert len(ent) == 1 and ent[0]["file"] == "assets/cap/r1.png" and ent[0]["role"] == "focus" and ent[0]["sentence"] == 2
    sub = {s["label"]: s for s in job.step("assets")["sub"]}
    assert sub["대상 사진"]["status"] == "done" and "느티" in sub["대상 사진"]["note"]
    plan = json.loads((job.dir / "shot_plan.json").read_text(encoding="utf-8"))["plan"]
    used = {f for fs in plan.values() for f in fs}
    desc = (job.dir / "out/description.txt").read_text(encoding="utf-8")
    assert ("참고 이미지 「느티」" in desc) == (ent[0]["file"] in used)
    assert len(plan.get("2", [])) >= 1


def test_pipeline_option_off_and_failure_do_not_stop_job(tmp_path):
    deps = EntDeps()
    job = run_to_assets(tmp_path / "off", deps, {"entity_images": False})
    assert job.state["status"] == "done" and "entity_images" not in deps.calls

    class Bad(FakeDeps):
        def entity_images(self, *a):
            raise RuntimeError("검색 서버 죽음")
    job2 = run_to_assets(tmp_path / "bad", Bad())
    assert job2.state["status"] == "done"
    assert {s["label"]: s for s in job2.step("assets")["sub"]}["대상 사진"]["status"] == "error"


def test_default_deps_noop_under_pytest(tmp_path):
    res = P.Deps().entity_images(tmp_path, {}, {"sentences": []}, {})
    assert res["entries"] == [] and res["calls"] == 0


def test_description_line_has_artist_and_licence(tmp_path):
    job = run_to_assets(tmp_path, EntDeps())
    entries = json.loads((job.dir / "assets/assets.json").read_text(encoding="utf-8"))
    assert entries and any(e.get("ref", {}).get("licence") == "non-free (Wikipedia fair use)" for e in entries)
