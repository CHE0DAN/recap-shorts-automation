"""이미 만든 소재 표시(중복 소재) — recap_shorts/collect/made.py 와 /api/topics 의 made·hide_made, POST /api/jobs 의 409 중복 막기.
모두 오프라인: 가짜 job 폴더·가짜 보관 색인(드라이브 경로가 없는 것 포함)만 쓴다."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recap_shorts import archive
from recap_shorts.app import create_app
from recap_shorts.collect import dcbest as B
from recap_shorts.collect import dcinside
from recap_shorts.collect import made as M
from tests.pipeline.fakes import FakeDeps

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=KST)
FIX = Path(__file__).parent / "fixtures" / "dcbest"


# ---------------------------------------------------------------- 가짜 job 만들기
def fake_state(jid, gallery, no, src_title, our_title, created_at="2026-10-18T12:00:00+09:00", *, render="done",
               source="done", status="done"):
    keys = ["source", "read", "script", "voice", "assets", "scenes", "render", "review"]
    done_upto = keys.index("render") if render == "done" else keys.index("source")
    steps = []
    for i, k in enumerate(keys):
        st = "done" if i <= done_upto else "todo"
        if k == "source":
            st = source
        if k == "render" and render != "done":
            st = render
        steps.append({"key": k, "label": k, "status": st, "progress": 0.0, "detail": "", "sub": [], "started_at": None,
                      "ended_at": None, "error": None})
    return {"id": jid, "title": our_title, "source": {"gallery": gallery, "no": no, "title": src_title,
                                                      "url": f"https://gall.dcinside.com/board/view/?id={gallery}&no={no}"},
            "created_at": created_at, "status": status, "progress": 1.0, "options": {}, "steps": steps, "artifacts": {}, "log": []}


def write_job(root: Path, state: dict, origin_url: str | None = None) -> Path:
    d = root / state["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    if origin_url is not None:
        (d / "post").mkdir(exist_ok=True)
        (d / "post" / f"post_{state['source']['no']}.json").write_text(
            json.dumps({"no": state["source"]["no"], "origin_gallery": "잡담", "origin_url": origin_url}, ensure_ascii=False),
            encoding="utf-8")
    return d


def add_archived(root: Path, state: dict, drive_dir: Path | None, origin_url: str | None = None) -> None:
    """보관 색인(work/_archive.json)에만 있는 job. drive_dir 이 None 이면 드라이브가 꺼진 것(경로가 없음)."""
    path = drive_dir or (root.parent / "G_missing_drive" / state["id"])
    if drive_dir is not None and origin_url is not None:
        (drive_dir / "post").mkdir(parents=True, exist_ok=True)
        (drive_dir / "post" / f"post_{state['source']['no']}.json").write_text(
            json.dumps({"origin_url": origin_url}), encoding="utf-8")
    archive.add_index_entry(root, archive.make_entry(state, path, 1, 1))


@pytest.fixture(autouse=True)
def _fresh_cache():
    M.clear_cache()
    yield
    M.clear_cache()


# ---------------------------------------------------------------- 제목 정리
@pytest.mark.parametrize("raw,expected", [
    ("[가갤] 싱글벙글 동네 문구점에서 산 100원 연필.jpg", "동네문구점에서산100원연필"),
    ("[가갤] 안싱글벙글 야간 근무 첫날 후기", "야간근무첫날후기"),
    ("[가갤] 와들와들 이웃과 결혼 후 바뀐 사람...JPG", "이웃과결혼후바뀐사람"),
    ("[가갤] 훌쩍훌쩍 폐교를 지킨 마지막 학생이 받은 선물", "폐교를지킨마지막학생이받은선물"),
    ("[카연] 요즘 화제인 작가 vs 편집자 대결 ㅎㄷㄷ", "요즘화제인작가vs편집자대결"),
    ("[치갤] 판다 삼국지.manhwa", "판다삼국지"),
    ("블라인드) 택배 때문에 이사하면 어떨거같아?.jpg", "택배때문에이사하면어떨거같아"),
    ("[미갤] 헉ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ", "헉"),
    ("AI 그림ㅋㅋ라고 분노하는 사람들...jpg", "ai그림라고분노하는사람들"),
    ("[가갤] 싱글벙글 어떤 회사 주식 레버리지 근황...", "어떤회사주식레버리지"),
    ("(스압?)갑자기 생각나서 대충 적어보는 25시즌 결산", "갑자기생각나서대충적어보는25시즌결산"),
    ('"간판 모양이 이상한데 장난임?"', "간판모양이이상한데장난임"),
    ("3만 원짜리 중고 의자, 실제 상태 ㄷㄷ.jpg", "3만원짜리중고의자실제상태"),
    ("", ""),
    (None, ""),
])
def test_normalize_title(raw, expected):
    assert M.normalize_title(raw) == expected


def test_similarity_ignores_tags_suffixes_and_laughter():
    a = "[가갤] 싱글벙글 동네 문구점에서 산 100원 연필.jpg"
    assert M.similarity(a, "동네 문구점에서 산 100원 연필 ㅋㅋㅋ") == 1.0
    assert M.similarity(a, "[미갤] 동네 문구점에서 산 100원 연필...PNG") == 1.0
    # 전혀 다른 제목, 너무 짧은 제목, 빈 제목
    assert M.similarity(a, "오늘 동네 시장에 사람이 엄청 많네?") == 0.0
    assert M.similarity("빵집", "빵집 근황") == 0.0       # 정리하면 너무 짧아 비교하지 않음
    assert M.similarity("", "아무거나 긴 제목입니다") == 0.0


def test_similarity_threshold_on_real_wordings():
    """'원본 글 제목 ↔ 우리 영상 제목'(같은 이야기를 다르게 쓴 쌍) 중 겹치는 말이 뚜렷한 것은 기준 이상,
    제목이 전혀 다른 일반 글은 기준 미만."""
    same = [("[가상] 동네 빵집 오픈런 실제 대기 시간.jpg", "빵집 오픈런 대기 시간이 이렇게 길다고?"),
            ("블라인드) 택배 때문에 이사하면 어떨거같아?.jpg", "택배 때문에 이사까지 고민한다는 사연"),
            ("동네 목공방은 목재를 어디서 조달할까?", "목공방 목재는 어디서 올까?")]
    for a, b in same:
        assert M.similarity(a, b) >= M.SIMILAR_THRESHOLD, (a, b)
    diff = [("새로 산 자전거 배송이 취소된 사연", "인생이 허무한 진짜 이유"),
            ("동네 시장 상인들이 요즘 쓰는 결제 방법", "요즘 취업난 많이 심각하다네"),
            ("학교 교실의 창문은 항상 왼쪽인 이유", "동네 빵집이 아침에만 문을 여는 이유")]
    for a, b in diff:
        assert M.similarity(a, b) < M.SIMILAR_THRESHOLD, (a, b)


def test_origin_key_and_fmt_when():
    assert M.origin_key("https://gall.dcinside.com/board/view/?id=testgallery&no=2001") == ("testgallery", 2001)
    assert M.origin_key("https://gall.dcinside.com/mgallery/board/view/?id=x&no=5&page=2") == ("x", 5)
    assert M.origin_key("") is None and M.origin_key(None) is None and M.origin_key("https://example.com/") is None
    assert M.fmt_when("2026-10-18T12:38:45+09:00") == "10-18 12:38"
    assert M.fmt_when("이상한 값") == "이상한 값" and M.fmt_when(None) == ""


# ---------------------------------------------------------------- 색인
def build_fixture(tmp_path):
    root = tmp_path / "work"
    # 로컬: 같은 글로 job 3개(영상까지 / 영상까지 / 중간에 멈춤), 원본 주소가 있는 dcbest job, 글 가져오기에 실패한 job
    write_job(root, fake_state("20261017-190523_baseball_new13_2001", "baseball_new13", 2001, "[가상] 3만 원짜리 중고 의자, 실제 상태 ㄷㄷ.jpg",
                               "3만 원 중고 의자 실제 상태가 이렇다고?", "2026-10-17T19:05:23+09:00"))
    write_job(root, fake_state("20261017-195542_baseball_new13_2001", "baseball_new13", 2001, "[가상] 3만 원짜리 중고 의자, 실제 상태 ㄷㄷ.jpg",
                               "3만 원에 산 중고 의자, 실제 상태는 이랬어", "2026-10-17T19:55:42+09:00"))
    write_job(root, fake_state("20261017-201059_baseball_new13_2001", "baseball_new13", 2001, "[가상] 3만 원짜리 중고 의자, 실제 상태 ㄷㄷ.jpg",
                               "3만 원 중고 의자 실제로 받아 보니", "2026-10-17T20:10:59+09:00", render="todo", status="waiting"))
    write_job(root, fake_state("20261026-072157_dcbest_2002", "dcbest", 2002, "[가상] 새로 산 자전거 배송이 취소된 사연",
                               "자전거 배송 하루 앞두고 취소된 진짜 이유", "2026-10-26T07:21:57+09:00"),
              origin_url="https://gall.dcinside.com/board/view/?id=testgallery&no=2001")
    write_job(root, fake_state("20261027-100000_dcbest_999", "dcbest", 999, "가져오지 못한 글", "가져오지 못한 글",
                               "2026-10-27T10:00:00+09:00", render="todo", source="error", status="error"))
    # 보관: 드라이브가 있는 것(원본 주소를 드라이브의 post_*.json 에서 읽음) / 드라이브가 꺼진 것(색인 요약만)
    drive = tmp_path / "drive" / "20261019-215321_dcbest_2003"
    add_archived(root, fake_state("20261019-215321_dcbest_2003", "dcbest", 2003, "[가상] 동네 목공방은 목재를 어디서 조달할까?",
                                  "목공방 목재는 어디서 올까?", "2026-10-19T21:53:21+09:00"), drive,
                 origin_url="https://gall.dcinside.com/board/view/?id=testgallery&no=2004")
    add_archived(root, fake_state("20261019-024130_dcbest_2005", "dcbest", 2005, "[가상] 폐교를 지킨 마지막 학생이 받은 선물",
                                  "폐교를 지킨 마지막 학생의 선물", "2026-10-19T02:41:30+09:00"), None)
    return root


def test_build_index_local_and_archived(tmp_path):
    root = build_fixture(tmp_path)
    idx = M.build_index(root)
    ids = [j.job_id for j in idx.jobs]
    assert len(idx) == 7 - 1                                         # 글 가져오기 실패 job 은 뺀다
    assert "20261027-100000_dcbest_999" not in ids
    assert ids == sorted(ids, key=lambda i: next(j.created_at for j in idx.jobs if j.job_id == i))     # 만든 시각 순
    post = idx.same_post("baseball_new13", 2001)
    assert [j.finished for j in post] == [True, True, False]         # 세 번째는 영상까지 못 감
    assert all(not j.archived for j in post)
    j = idx.same_post("dcbest", 2002)[0]
    assert j.origin == ("testgallery", 2001) and j.source_title == "[가상] 새로 산 자전거 배송이 취소된 사연" and j.our_title.startswith("자전거")
    on = idx.same_post("dcbest", 2003)[0]
    assert on.archived and on.origin == ("testgallery", 2004)         # 드라이브 폴더가 있으면 원본 주소도 읽는다
    off = idx.same_post("dcbest", 2005)[0]
    assert off.archived and off.origin_url == "" and off.our_title == "폐교를 지킨 마지막 학생의 선물"   # 드라이브가 꺼져 있어도 색인 요약으로 안다


def test_build_index_tolerates_junk(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    (root / "_archive.json").write_text("{깨진 json", encoding="utf-8")
    (root / "broken").mkdir()
    (root / "broken" / "state.json").write_text("not json", encoding="utf-8")
    (root / "wrongname").mkdir()                                                                               # 폴더 이름과 id 가 다름 → 건너뜀
    (root / "wrongname" / "state.json").write_text(json.dumps(fake_state("other_id", "dcbest", 1, "제목 제목 제목", "제목")), encoding="utf-8")
    write_job(root, {"id": "nosrc", "title": "x", "steps": []})                                                # source 없음 → 건너뜀
    write_job(root, fake_state("ok_job", "dcbest", 5, "정상적인 제목입니다", "정상 제목"))
    assert [j.job_id for j in M.build_index(root).jobs] == ["ok_job"]
    assert len(M.build_index(tmp_path / "없는 폴더")) == 0


def test_get_index_cache_follows_files(tmp_path):
    root = tmp_path / "work"
    write_job(root, fake_state("20261001-000000_dcbest_1", "dcbest", 1, "첫 번째 글 제목입니다", "첫 번째"))
    a = M.get_index(root)
    assert M.get_index(root) is a                                      # 파일이 그대로면 같은 색인
    write_job(root, fake_state("20261002-000000_dcbest_2", "dcbest", 2, "두 번째 글 제목입니다", "두 번째"))
    b = M.get_index(root)
    assert b is not a and len(b) == 2                                  # job 이 늘면 새로 만든다
    add_archived(root, fake_state("20261003-000000_dcbest_3", "dcbest", 3, "세 번째 글 제목입니다", "세 번째"), None)
    c = M.get_index(root)
    assert c is not b and len(c) == 3                                  # 보관 색인이 바뀌어도
    st = fake_state("20261002-000000_dcbest_2", "dcbest", 2, "두 번째 글 제목입니다", "바뀐 영상 제목")
    write_job(root, st)
    assert M.get_index(root).same_post("dcbest", 2)[0].our_title == "바뀐 영상 제목"       # state.json 이 바뀌어도(내용 길이가 달라짐)


# ---------------------------------------------------------------- 견주기
def test_match_same_post_prefers_latest_and_counts(tmp_path):
    idx = M.build_index(build_fixture(tmp_path))
    m = idx.match("baseball_new13", 2001, "아무 제목")
    assert m["kind"] == "same_post" and m["count"] == 3 and m["score"] == 1.0
    assert m["job_id"].endswith("201059_baseball_new13_2001") and m["finished"] is False       # 가장 최근 job
    assert m["our_title"] == "3만 원 중고 의자 실제로 받아 보니" and m["created_at"].startswith("2026-10-17T20:10")
    assert idx.match("dcbest", 2005, "x")["archived"] is True
    # 같은 번호라도 갤러리가 다르면 같은 글이 아니다
    assert (idx.match("dcbest", 2001, "전혀 상관없는 제목이 들어 있는 글") or {}).get("kind") != "same_post"


def test_match_similar_and_none(tmp_path):
    idx = M.build_index(build_fixture(tmp_path))
    m = idx.match("dcbest", 3001, "[가갤] 싱글벙글 동네 목공방은 목재를 어디서 조달할까?.jpg")
    assert m["kind"] == "similar" and m["job_id"].endswith("dcbest_2003") and m["score"] >= M.SIMILAR_THRESHOLD and m["count"] == 1
    # 우리 영상 제목과 비슷한 새 글도 잡는다(원본 제목이 아니라 영상 제목 쪽과 겹침)
    m2 = idx.match("dcbest", 3002, "폐교를 지킨 마지막 학생의 선물 이야기")
    assert m2["kind"] == "similar" and m2["job_id"].endswith("dcbest_2005")
    assert idx.match("dcbest", 3003, "오늘 시장에 사람이 엄청 많네?") is None
    assert idx.match("dcbest", 3004, "짧음") is None


def test_match_same_original(tmp_path):
    idx = M.build_index(build_fixture(tmp_path))
    url = "https://gall.dcinside.com/board/view/?id=testgallery&no=2001"
    m = idx.match("dcbest", 555, "제목이 전혀 다른 글입니다 정말로", origin_url=url)
    assert m["kind"] == "same_original" and m["job_id"].endswith("dcbest_2002")
    assert idx.same_original("https://gall.dcinside.com/board/view/?id=nothing&no=1") == []
    # 원본 글 자체로 만든 job 도 같은 원본으로 본다
    ids = [j.job_id for j in idx.same_original("https://gall.dcinside.com/board/view/?id=baseball_new13&no=2001")]
    assert len(ids) == 3
    assert idx.match("dcbest", 556, "제목이 전혀 다른 글입니다 정말로") is None            # 원본 주소 없이는 같은 원본을 알 수 없다


def test_annotate_and_drop(tmp_path):
    idx = M.build_index(build_fixture(tmp_path))
    items = [{"no": 2002, "title": "[가상] 새로 산 자전거 배송이 취소된 사연"},
             {"no": 1, "title": "동네 목공방은 목재를 어디서 조달할까?"},
             {"no": 2, "title": "오늘 시장에 사람이 엄청 많네?"}]
    extra = M.annotate_items(idx, items, "dcbest")
    assert extra == {"made_count": 2, "made_same_count": 1}
    assert [i["made"]["kind"] if i["made"] else None for i in items] == ["same_post", "similar", None]
    assert [i["no"] for i in M.drop_made(items)] == [1, 2]            # 같은 글만 빠지고 비슷한 이야기는 남는다


def test_duplicate_message_names_jobs(tmp_path):
    idx = M.build_index(build_fixture(tmp_path))
    msg = M.duplicate_message(idx.same_post("baseball_new13", 2001))
    assert msg.startswith("이미 만든 글입니다 (3번)")
    assert "10-17 20:10 · 3만 원 중고 의자 실제로 받아 보니 (영상 안 끝남)" in msg and msg.index("20:10") < msg.index("19:55")      # 최신 순


# ---------------------------------------------------------------- API
@pytest.fixture
def env(tmp_path, monkeypatch):
    items = B.parse_best_list((FIX / "list_page1.html").read_text(encoding="utf-8"), NOW)
    monkeypatch.setattr(B, "fetch_best", lambda pages=3, hours=48, sort="views", client=None, now=None, max_pages=5:
                        B.sort_items([i for i in items if i.age_hours <= hours], sort))
    deps = FakeDeps()
    deps.clef_triage = lambda posts: [{"no": p["no"], "category": {"politics": 0.8, "other": 0.2}, "hidden": False,
                                       "hidden_by": []} for p in posts]
    app = create_app(work_root=tmp_path, deps=deps)
    with TestClient(app) as client:
        yield client, app, tmp_path


def test_api_topics_made_fields_and_hide_made(env):
    client, app, root = env
    # 1001 은 같은 글, 1005 는 다른 번호로 만든 비슷한 제목의 이야기(원본 제목에서 말머리·태그만 다름)로 이미 만들어 둠
    write_job(root, fake_state("20261017-100000_dcbest_1001", "dcbest", 1001, "[가상] 의외로 흔적이 남지 않는 사람", "흔적이 남지 않는 사람들의 정체", "2026-10-17T10:00:00+09:00"))
    write_job(root, fake_state("20261016-100000_dcbest_2001", "dcbest", 2001, "[가상] 오래된 사진 한 장에 붙은 질문", "오래된 사진 한 장에 담긴 질문", "2026-10-16T10:00:00+09:00"))
    r = client.get("/api/topics?source=dcbest").json()
    by = {i["no"]: i for i in r["items"]}
    assert by[1001]["made"]["kind"] == "same_post" and by[1001]["made"]["our_title"] == "흔적이 남지 않는 사람들의 정체"
    assert by[1001]["made"]["created_at"].startswith("2026-10-17T10:00") and by[1001]["made"]["finished"] is True
    assert by[1005]["made"]["kind"] == "similar" and 0.22 <= by[1005]["made"]["score"] <= 1.0 and by[1005]["made"]["job_id"].endswith("2001")
    assert by[1006]["made"] is None and len(r["items"]) == 6
    assert r["made_count"] == 2 and r["made_same_count"] == 1 and r["made_hidden"] == 0
    # hide_made: 같은 글만 숨기고 비슷한 이야기는 남긴다
    h = client.get("/api/topics?source=dcbest&hide_made=true").json()
    assert 1001 not in [i["no"] for i in h["items"]] and 1005 in [i["no"] for i in h["items"]]
    assert len(h["items"]) == 5 and h["made_hidden"] == 1 and h["made_count"] == 2
    # refresh 쪽도 같은 옵션
    h2 = client.post("/api/topics/refresh", json={"source": "dcbest", "hide_made": True}).json()
    assert len(h2["items"]) == 5 and h2["made_hidden"] == 1
    # 목록 캐시는 그대로여도 새로 만든 job 은 바로 표시됨(네트워크 호출 없음)
    write_job(root, fake_state("20261018-110000_dcbest_1006", "dcbest", 1006, "[가상] 편의점 야간 근무를 그만둔 이유", "편의점 야간 근무를 그만둔 이유", "2026-10-18T11:00:00+09:00"))
    again = {i["no"]: i for i in client.get("/api/topics?source=dcbest").json()["items"]}
    assert again[1006]["made"]["kind"] == "same_post"


def test_api_topics_without_jobs_has_null_made(env):
    client, app, root = env
    r = client.get("/api/topics?source=dcbest").json()
    assert all(i["made"] is None for i in r["items"]) and r["made_count"] == 0 and r["made_same_count"] == 0


def test_api_gallery_topics_made(env, monkeypatch):
    client, app, root = env
    monkeypatch.setattr(dcinside, "list_posts", lambda *a, **k: [dcinside.PostSummary(2001, "[가상] 3만 원짜리 중고 의자, 실제 상태 ㄷㄷ.jpg", "10.17", 10, 5, 1, "u"),
                                                                dcinside.PostSummary(7, "오늘 시장에 사람이 엄청 많네?", "10.17", 10, 5, 1, "u")])
    write_job(root, fake_state("20261017-190523_baseball_new13_2001", "baseball_new13", 2001, "[가상] 3만 원짜리 중고 의자, 실제 상태 ㄷㄷ.jpg", "3만 원 중고 의자", "2026-10-17T19:05:23+09:00"))
    r = client.get("/api/topics?gallery=baseball_new13&pages=1").json()
    assert [i["made"]["kind"] if i["made"] else None for i in r["items"]] == ["same_post", None] and r["made_count"] == 1
    r2 = client.get("/api/topics?gallery=baseball_new13&pages=1&hide_made=true").json()          # 캐시에서 읽어도 made 가 붙고 hide_made 가 먹는다
    assert [i["no"] for i in r2["items"]] == [7] and r2["made_hidden"] == 1


def test_api_create_job_409_and_allow_duplicate(env):
    client, app, root = env
    idle = lambda: app.state.runner.wait_idle(60)      # noqa: E731
    body = {"gallery": "baseball_new13", "no": 2101}
    r1 = client.post("/api/jobs", json=body)
    assert r1.status_code == 200
    idle()
    r2 = client.post("/api/jobs", json=body)                                   # 같은 글 → 409, 기존 job 을 이름 붙여 알려 준다
    assert r2.status_code == 409
    d = r2.json()["detail"]
    assert d["code"] == "duplicate" and d["count"] == 1 and d["jobs"][0]["id"] == r1.json()["id"]
    assert "이미 만든 글입니다" in d["message"] and "[가상] 동네 축구 결승전에 구청 직원이 셋이나" in d["message"] and d["jobs"][0]["created_at"][5:10] in d["message"]
    assert len(client.get("/api/jobs").json()) == 1                            # 하나도 더 만들어지지 않음
    # URL 로 같은 글을 넣어도 막힌다
    r3 = client.post("/api/jobs", json={"url": "https://gall.dcinside.com/board/view/?id=baseball_new13&no=2101"})
    assert r3.status_code == 409
    # 그래도 만들겠다고 하면(allow_duplicate) 만든다 — 같은 초에 만들면 id 가 겹치므로 한 초 쉬어 간다
    import time
    time.sleep(1.1)
    r4 = client.post("/api/jobs", json={**body, "allow_duplicate": True})
    assert r4.status_code == 200 and r4.json()["id"] != r1.json()["id"]
    idle()
    assert len(client.get("/api/jobs").json()) == 2
    # 이제 두 개 → 메시지에 개수
    r5 = client.post("/api/jobs", json=body)
    assert r5.status_code == 409 and r5.json()["detail"]["count"] == 2 and "(2번)" in r5.json()["detail"]["message"]
    # 다른 글·같은 번호의 다른 갤러리는 막지 않는다
    assert client.post("/api/jobs", json={"gallery": "baseball_new13", "no": 2102}).status_code == 200
    assert client.post("/api/jobs", json={"gallery": "dcbest", "no": 2101}).status_code == 200
    idle()


def test_api_create_job_conflicts_with_archived_and_ignores_failed(env):
    client, app, root = env
    add_archived(root, fake_state("20261017-184209_baseball_new13_2101", "baseball_new13", 2101, "[가상] 동네 축구 결승전에 구청 직원이 셋이나",
                                  "동네 축구 결승, 구청 직원이 나온 이유", "2026-10-17T18:42:09+09:00"), None)       # 드라이브가 꺼진 보관 job
    r = client.post("/api/jobs", json={"gallery": "baseball_new13", "no": 2101})
    assert r.status_code == 409 and r.json()["detail"]["jobs"][0]["archived"] is True and "동네 축구 결승, 구청 직원이 나온 이유" in r.json()["detail"]["message"]
    # 글 가져오기에 실패한 job 은 막지 않는다(다시 시도)
    write_job(root, fake_state("20261027-100000_dcbest_999", "dcbest", 999, "가져오지 못한 글", "가져오지 못한 글", "2026-10-27T10:00:00+09:00",
                               render="todo", source="error", status="error"))
    r = client.post("/api/jobs", json={"gallery": "dcbest", "no": 999})
    assert r.status_code == 200
    assert app.state.runner.wait_idle(60)
