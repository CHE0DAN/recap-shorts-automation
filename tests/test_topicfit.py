"""채널 대주제: 설정·API·맞춤 점수·순서·보관·CLI. 진짜 Gemini 는 부르지 않는다(가짜 LLM)."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recap_shorts.app import create_app
from recap_shorts.app import server as S
from recap_shorts.collect import dcbest as B
from recap_shorts.collect import topicfit as T
from tests.pipeline.fakes import FakeDeps

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 18, 12, 30, tzinfo=KST)
FIX = Path(__file__).parent / "fixtures" / "dcbest"
REAL_CONFIG = Path(__file__).resolve().parents[1] / "config" / "channel.json"

PRESETS = [{"id": "daily_drama", "label": "일상 논란·썰", "desc": "일상 갈등·썰"},
           {"id": "money_life", "label": "돈·생활 경제", "desc": "돈과 생활 경제"}]
# 조회수 순: 1006 1005 1004 1003 1001 1002
FIT = {1006: 0, 1005: 2, 1004: 1, 1003: 2, 1001: 0, 1002: 1}
LINE = re.compile(r"^(\d+)\. (?:\[[^\]]*\] )?(.*)$")


class FakeFitLLM:
    """프롬프트의 '번호. [태그] 제목' 줄을 읽어 FIT 표대로 답한다(실제 모델처럼 번호를 키로)."""

    def __init__(self, items, table=None):
        self.title2no = {i.title: i.no for i in items}
        self.table = dict(FIT if table is None else table)
        self.prompts: list[str] = []
        self.models: list[str] = []
        self.fail_on: set[int] = set()       # 이 번째(1부터) 호출은 예외

    def __call__(self, prompt, model=None):
        self.prompts.append(prompt)
        self.models.append(model)
        if len(self.prompts) in self.fail_on:
            raise RuntimeError("Gemini API 실패: HTTP 429: quota")
        fits = {}
        for ln in prompt.splitlines():
            m = LINE.match(ln)
            if m and m.group(2) in self.title2no:
                fits[m.group(1)] = self.table[self.title2no[m.group(2)]]
        return {"fits": fits}


def write_cfg(d: Path, main_topic=None, custom=None, batch=30):
    (d / "channel.json").write_text(json.dumps({"main_topic": main_topic, "presets": PRESETS, "custom": custom,
                                                "fit": {"batch": batch, "model": "gemini-3.8-flash"}}, ensure_ascii=False),
                                    encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    items = B.parse_best_list((FIX / "list_page1.html").read_text(encoding="utf-8"), NOW)
    monkeypatch.setattr(B, "fetch_best", lambda pages=3, hours=48, sort="views", client=None, now=None, max_pages=5:
                        B.sort_items([i for i in items if i.age_hours <= hours], sort))
    monkeypatch.setattr(S, "FIT_RETRY_AFTER", 0.0)          # 실패 뒤 쉬는 시간은 따로 시험한다
    cfg_dir = T.CONFIG_PATH.parent
    write_cfg(cfg_dir)
    deps = FakeDeps()
    deps.clef_triage = lambda posts: [{"no": p["no"], "category": {"other": 1.0}} for p in posts]
    llm = FakeFitLLM(items)
    deps.topic_fit_llm = llm
    app = create_app(work_root=tmp_path / "work", deps=deps)
    with TestClient(app) as client:
        yield client, llm, tmp_path / "work", cfg_dir


def nos(r):
    return [i["no"] for i in r["items"]]


# ---------------------------------------------------------------- 없음: 예전 그대로
def test_no_topic_unchanged_and_zero_llm_calls(env):
    client, llm, work, cfg = env
    r = client.get("/api/topics?source=dcbest&sort=views").json()
    assert nos(r) == [1006, 1005, 1004, 1003, 1001, 1002]
    assert llm.prompts == []
    assert r["channel"] is None and r["fit"] == "off" and r["fit_note"] == "" and r["unfit_count"] == 0
    assert all("fit" not in i for i in r["items"])
    assert not list((work / "_topics").glob("fit_*"))
    client.post("/api/topics/refresh", json={"source": "dcbest"})
    client.get("/api/topics?source=dcbest&hide_unfit=true")
    assert llm.prompts == []


def test_unknown_or_empty_custom_topic_is_none(env):
    client, llm, work, cfg = env
    write_cfg(cfg, main_topic="gone_id")
    assert client.get("/api/topics?source=dcbest").json()["fit"] == "off"
    write_cfg(cfg, main_topic="custom", custom="   ")
    assert client.get("/api/topics?source=dcbest").json()["fit"] == "off"
    assert llm.prompts == []


# ---------------------------------------------------------------- 정해짐: 순서·보관
def test_order_fit_groups_keep_inner_order(env):
    client, llm, work, cfg = env
    assert client.put("/api/channel", json={"main_topic": "daily_drama"}).status_code == 200
    r = client.get("/api/topics?source=dcbest&sort=views").json()
    assert nos(r) == [1005, 1003, 1004, 1002, 1006, 1001]          # 2, 2, 1, 1, 0, 0 — 묶음 안은 조회수 순 그대로
    assert [i["fit"] for i in r["items"]] == [2, 2, 1, 1, 0, 0]
    assert r["fit"] == "ok" and r["fit_note"] == "" and r["unfit_count"] == 2
    assert r["channel"] == {"main_topic": "daily_drama", "label": "일상 논란·썰"}
    assert len(llm.prompts) == 1 and llm.models == ["gemini-3.8-flash"]
    p = llm.prompts[0]
    assert "일상 논란·썰" in p and "일상 갈등·썰" in p and "6." in p
    assert "nick" not in json.dumps(r).lower()
    # 다른 정렬 기준에서도 묶음 순서는 같고, 묶음 안은 그 기준 순서
    r2 = client.get("/api/topics?source=dcbest&sort=comments").json()
    assert [i["fit"] for i in r2["items"]] == [2, 2, 1, 1, 0, 0]
    assert nos(r2)[:2] == [1005, 1003] and nos(r2)[2:4] == [1004, 1002]
    assert len(llm.prompts) == 1                                                # 보관된 점수 — 다시 안 물음


def test_cache_hit_no_second_call_even_after_refresh_and_new_app(env, tmp_path):
    client, llm, work, cfg = env
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    client.get("/api/topics?source=dcbest")
    client.post("/api/topics/refresh", json={"source": "dcbest"})
    client.get("/api/topics?source=dcbest&refresh=true")
    assert len(llm.prompts) == 1
    assert len(list((work / "_topics").glob("fit_*_daily_drama-*.json"))) == 6
    # 프로세스를 다시 띄워도(같은 work) 보관된 점수를 쓴다
    deps2 = FakeDeps()
    deps2.clef_triage = lambda posts: None
    deps2.topic_fit_llm = lambda prompt, model=None: pytest.fail("보관된 점수가 있는데 다시 물음")
    with TestClient(create_app(work_root=work, deps=deps2)) as c2:
        assert [i["fit"] for i in c2.get("/api/topics?source=dcbest").json()["items"]] == [2, 2, 1, 1, 0, 0]


def test_hide_unfit_option(env):
    client, llm, work, cfg = env
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    r = client.get("/api/topics?source=dcbest&hide_unfit=true").json()
    assert nos(r) == [1005, 1003, 1004, 1002] and r["unfit_count"] == 2
    assert len(client.get("/api/topics?source=dcbest").json()["items"]) == 6
    r = client.post("/api/topics/refresh", json={"source": "dcbest", "hide_unfit": True}).json()
    assert len(r["items"]) == 4


def test_other_topic_or_changed_desc_is_asked_again(env):
    client, llm, work, cfg = env
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    client.get("/api/topics?source=dcbest")
    client.put("/api/channel", json={"main_topic": "money_life"})
    client.get("/api/topics?source=dcbest")
    assert len(llm.prompts) == 2 and "돈과 생활 경제" in llm.prompts[1]
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    client.get("/api/topics?source=dcbest")
    assert len(llm.prompts) == 2                                                # 돌아오면 보관된 것
    PRESETS[0] = {**PRESETS[0], "desc": "설명을 고침"}
    try:
        write_cfg(cfg, main_topic="daily_drama")
        client.get("/api/topics?source=dcbest")
        assert len(llm.prompts) == 3 and "설명을 고침" in llm.prompts[2]       # 설명이 바뀌면 키가 달라져 다시 매김
    finally:
        PRESETS[0] = {"id": "daily_drama", "label": "일상 논란·썰", "desc": "일상 갈등·썰"}


def test_batches_of_n(env):
    client, llm, work, cfg = env
    write_cfg(cfg, main_topic="daily_drama", batch=4)
    r = client.get("/api/topics?source=dcbest").json()
    assert len(llm.prompts) == 2 and r["fit"] == "ok"
    assert "4. " in llm.prompts[0] and "5. " not in llm.prompts[0] and "2. " in llm.prompts[1] and "3. " not in llm.prompts[1]
    assert [i["fit"] for i in r["items"]] == [2, 2, 1, 1, 0, 0]


def test_custom_topic_uses_its_text(env):
    client, llm, work, cfg = env
    r = client.put("/api/channel", json={"main_topic": "custom", "custom": "게임 업계 소식과 논란"}).json()
    assert r["main_topic"] == "custom" and r["custom"] == "게임 업계 소식과 논란" and r["label"].startswith("게임 업계")
    items = client.get("/api/topics?source=dcbest").json()
    assert "게임 업계 소식과 논란" in llm.prompts[0] and items["channel"]["main_topic"] == "custom"
    assert list((work / "_topics").glob("fit_*_custom-*.json"))


# ---------------------------------------------------------------- 실패
def test_llm_failure_leaves_list_unchanged_with_note(env):
    client, llm, work, cfg = env
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    llm.fail_on = {1}
    r = client.get("/api/topics?source=dcbest").json()
    assert nos(r) == [1006, 1005, 1004, 1003, 1001, 1002]          # 원래 순서
    assert all("fit" not in i for i in r["items"])
    assert r["fit"] == "unavailable" and "원래 순서" in r["fit_note"] and "429" in r["fit_note"] and r["unfit_count"] == 0
    assert not list((work / "_topics").glob("fit_*"))                           # 실패는 보관하지 않음
    r = client.get("/api/topics?source=dcbest").json()                          # 다음 요청에서 다시 물어 성공
    assert r["fit"] == "ok" and len(llm.prompts) == 2 and [i["fit"] for i in r["items"]] == [2, 2, 1, 1, 0, 0]


def test_failure_backs_off_instead_of_asking_every_request(env, monkeypatch):
    client, llm, work, cfg = env
    monkeypatch.setattr(S, "FIT_RETRY_AFTER", 60.0)
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    llm.fail_on = {1}
    r1 = client.get("/api/topics?source=dcbest").json()
    r2 = client.get("/api/topics?source=dcbest&sort=comments").json()
    assert len(llm.prompts) == 1 and r1["fit"] == r2["fit"] == "unavailable"            # 쉬는 동안 두 번째 요청은 Gemini 를 안 부름
    assert "429" in r2["fit_note"] and "쉬는 중" in r2["fit_note"] and all("fit" not in i for i in r2["items"])


def test_unusable_answer_is_a_failure(env):
    client, llm, work, cfg = env
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    client.app.state.deps.topic_fit_llm = lambda prompt, model=None: {"fits": {"1": 7, "2": "많이", "9": 2}}
    r = client.get("/api/topics?source=dcbest").json()
    assert r["fit"] == "unavailable" and "모양" in r["fit_note"] and all("fit" not in i for i in r["items"])


def test_real_gemini_is_blocked_under_pytest(env):
    """FakeDeps 가 기본 구현을 쓰면(가짜를 안 끼우면) 시험 중에는 예외 → 점수 없이 목록 그대로. 네트워크 호출 없음."""
    client, llm, work, cfg = env
    del client.app.state.deps.__dict__["topic_fit_llm"]
    client.put("/api/channel", json={"main_topic": "daily_drama"})
    r = client.get("/api/topics?source=dcbest").json()
    assert r["fit"] == "unavailable" and "시험 중" in r["fit_note"]


def test_partial_failure_puts_unscored_between_1_and_0(env):
    client, llm, work, cfg = env
    write_cfg(cfg, main_topic="daily_drama", batch=4)
    llm.fail_on = {2}                       # 첫 묶음(조회수 상위 4개)만 매겨짐
    r = client.get("/api/topics?source=dcbest").json()
    assert r["fit"] == "partial" and "일부만" in r["fit_note"]
    fits = {i["no"]: i.get("fit") for i in r["items"]}
    assert fits == {1006: 0, 1005: 2, 1004: 1, 1003: 2, 1001: None, 1002: None}
    assert nos(r) == [1005, 1003, 1004, 1001, 1002, 1006]          # 2,2,1,(없음,없음),0
    assert r["unfit_count"] == 1
    assert [i["no"] for i in client.get("/api/topics?source=dcbest&hide_unfit=true").json()["items"]][-1] == 1002
    assert len(llm.prompts) == 3                                                # 다음 요청은 안 매긴 2개만 다시 물음
    assert llm.prompts[2].count("\n1. ") == 1 and "3. " not in llm.prompts[2]


# ---------------------------------------------------------------- 설정·API
def test_get_put_channel_and_persistence(env):
    client, llm, work, cfg = env
    write_cfg(cfg, main_topic="daily_drama")
    g = client.get("/api/channel").json()
    assert g["main_topic"] == "daily_drama" and g["label"] == "일상 논란·썰" and g["source"] == "default" and g["custom"] is None
    assert [p["id"] for p in g["presets"]] == ["daily_drama", "money_life"]
    committed = (cfg / "channel.json").read_text(encoding="utf-8")

    p = client.put("/api/channel", json={"main_topic": None}).json()           # '없음' 도 선택이다 — 기본값을 끈다
    assert p["main_topic"] is None and p["source"] == "local"
    assert client.get("/api/channel").json()["main_topic"] is None
    assert client.get("/api/topics?source=dcbest").json()["fit"] == "off"
    assert (cfg / "channel.json").read_text(encoding="utf-8") == committed      # 커밋되는 파일은 건드리지 않는다
    assert json.loads((cfg / "channel.local.json").read_text(encoding="utf-8")) == {"main_topic": None, "custom": None}

    assert client.put("/api/channel", json={"main_topic": "money_life"}).json()["label"] == "돈·생활 경제"
    # 직접 입력 글은 다른 걸 골라도 남는다
    client.put("/api/channel", json={"main_topic": "custom", "custom": "  요즘   뜨는 밈  "})
    r = client.put("/api/channel", json={"main_topic": "daily_drama"}).json()
    assert r["custom"] == "요즘 뜨는 밈" and r["main_topic"] == "daily_drama"
    assert client.put("/api/channel", json={"main_topic": "custom"}).json()["main_topic"] == "custom"
    assert client.put("/api/channel", json={"main_topic": "none"}).json()["main_topic"] is None


def test_put_channel_rejects_bad_values(env):
    client, llm, work, cfg = env
    assert client.put("/api/channel", json={"main_topic": "zzz"}).status_code == 400
    assert client.put("/api/channel", json={"main_topic": "custom"}).status_code == 400          # 직접 입력 글이 없음
    assert client.put("/api/channel", json={"main_topic": "custom", "custom": " "}).status_code == 400
    assert client.put("/api/channel", json={"main_topic": "custom", "custom": "가" * 201}).status_code == 400
    assert client.put("/api/channel", json={"main_topic": "custom", "custom": 5}).status_code == 400
    assert client.put("/api/channel", json={}).status_code == 400
    assert not (cfg / "channel.local.json").exists()


def test_committed_default_config_is_valid():
    cfg = T.load_config(REAL_CONFIG, REAL_CONFIG.parent / "no_such_local.json")
    assert cfg["main_topic"] == "daily_drama" and cfg["source"] == "default"
    assert [p["id"] for p in cfg["presets"]] == ["daily_drama", "money_life", "curious_facts"]
    assert all(p["label"] and p["desc"] for p in cfg["presets"])
    t = T.resolve(cfg)
    assert t and t.label == "일상 논란·썰" and t.key.startswith("daily_drama-")
    assert cfg["fit"]["batch"] >= 1 and cfg["fit"]["model"]


def test_missing_or_broken_config_means_none(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{not json", encoding="utf-8")
    for p in (tmp_path / "nope.json", bad):
        cfg = T.load_config(p, tmp_path / "nope2.json")
        assert cfg["main_topic"] is None and T.resolve(cfg) is None


# ---------------------------------------------------------------- 단위
def test_parse_answer_shapes():
    assert T.parse_answer({"fits": {"1": 2, "2": 0, "3": 1}}, 3) == {1: 2, 2: 0, 3: 1}
    assert T.parse_answer({"1": 2, "2": "1"}, 3) == {1: 2, 2: 1}
    assert T.parse_answer({"fits": [{"i": 1, "fit": 2}, {"id": 3, "score": 0}]}, 3) == {1: 2, 3: 0}
    assert T.parse_answer({"fits": {"0": 2, "4": 2, "1": 3, "2": 1.5, "3": True, "x": 1}}, 3) == {}
    assert T.parse_answer(["nope"], 3) == {} and T.parse_answer({"fits": "?"}, 3) == {}


def test_order_is_stable_and_unscored_between():
    items = [{"no": n, "fit": f} for n, f in [(1, 0), (2, None), (3, 1), (4, 2), (5, 1), (6, 2), (7, 0)]]
    assert [i["no"] for i in T.order(items)] == [4, 6, 3, 5, 2, 1, 7]
    assert [i["no"] for i in T.order(items, hide_unfit=True)] == [4, 6, 3, 5, 2]
    plain = [{"no": n} for n in (3, 1, 2)]
    assert [i["no"] for i in T.order(plain)] == [3, 1, 2]


def test_prompt_has_rubric_and_titles():
    t = T.Topic("x", "라벨", "설명 한 줄", "x-1")
    p = T.build_prompt(t, [(1, "싱갤", "제목   하나"), (2, "", "제목 둘")])
    assert "라벨" in p and "설명 한 줄" in p and "1. [싱갤] 제목 하나" in p and "2. 제목 둘" in p
    assert "2 = 딱 맞음" in p and "1 = 조금" in p and "0 = 아님" in p


# ---------------------------------------------------------------- CLI
def test_cli_topics_fit_dry_run_prints_and_stores_nothing(tmp_path, monkeypatch, capsys):
    items = B.sort_items(B.parse_best_list((FIX / "list_page1.html").read_text(encoding="utf-8"), NOW), "views")
    monkeypatch.setattr(T, "ROOT", tmp_path)
    write_cfg(T.CONFIG_PATH.parent, main_topic=None)
    llm = FakeFitLLM(items)
    rc = T.cli_main(["--topic", "daily_drama", "--dry-run"], fetch=lambda pages, hours: items, llm=llm)
    out = capsys.readouterr().out
    assert rc == 0 and len(llm.prompts) == 1
    lines = [ln for ln in out.splitlines() if re.match(r"^[012-]  ", ln)]
    assert [ln[0] for ln in lines] == ["2", "2", "1", "1", "0", "0"]
    assert "딱 맞음(2) 2 · 조금(1) 2 · 아님(0) 2" in out and "Gemini 호출 1회" in out and "--dry-run" in out
    assert not (tmp_path / "work").exists()
    # --dry-run 이 아니면 앱이 같이 쓰도록 보관한다
    T.cli_main(["--topic", "daily_drama", "--limit", "3"], fetch=lambda pages, hours: items, llm=llm)
    assert len(list((tmp_path / "work" / "_topics").glob("fit_*_daily_drama-*.json"))) == 3


def test_cli_without_topic_and_main_dispatch(capsys):
    from recap_shorts.collect import __main__ as M
    write_cfg(T.CONFIG_PATH.parent)
    with pytest.raises(SystemExit) as e:
        M.main(["topics-fit"])                  # 대주제 없음(시험 설정) → 안내만 하고 네트워크는 안 건드림
    out = capsys.readouterr().out
    assert e.value.code == 2 and "대주제가 없습니다" in out and "daily_drama" in out         # 고를 수 있는 id 를 알려 준다
    assert T.cli_main(["--topic", "nope"]) == 2


def test_cli_failure_exit_code(tmp_path, monkeypatch, capsys):
    items = B.sort_items(B.parse_best_list((FIX / "list_page1.html").read_text(encoding="utf-8"), NOW), "views")
    monkeypatch.setattr(T, "ROOT", tmp_path)
    write_cfg(T.CONFIG_PATH.parent)

    def boom(prompt, model):
        raise RuntimeError("키 없음")
    rc = T.cli_main(["--topic", "money_life", "--dry-run"], fetch=lambda p, h: items, llm=boom)
    out = capsys.readouterr().out
    assert rc == 1 and "unavailable" in out and "키 없음" in out
