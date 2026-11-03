"""단계가 예외로 멈출 때: 화면(status=error) 문구에는 예외 이름·Traceback·경로가 없고, 자세한 기록은 작업 폴더 _logs/errors.log 에만."""
import json
import re

from recap_shorts import pipeline as P
from tests.pipeline.fakes import FakeDeps

SRC = {"gallery": "baseball_new13", "no": 2101,
       "url": "https://gall.dcinside.com/board/view/?id=baseball_new13&no=2101", "minor": False}
LEAK = re.compile(r"[A-Za-z]:\\|Traceback|File \"|RuntimeError|GeminiApiError")


class WrongKeyDeps(FakeDeps):
    """Gemini 키가 틀렸을 때 실제로 나는 것과 같은 오류(HTTP 400 + API key not valid)를 8장 모두에서 낸다."""

    def __init__(self):
        super().__init__()
        self.reads = 0

    def read_image(self, images, instruction):
        self.reads += 1
        r = __import__("requests").Response()
        r.status_code = 400
        raise __import__("recap_shorts.llm.gemini_api", fromlist=["GeminiApiError"]).GeminiApiError(
            "Gemini API 실패(gemini-3.8-flash): HTTP 400: API key not valid. Please pass a valid API key.",
            kind="bad_key", http=400)


def run(tmp_path, deps, options=None):
    store = P.JobStore(tmp_path)
    runner = P.Runner(store, deps)
    runner.start()
    job = store.create(dict(SRC), options or {"auto_steps": ["read"]})
    runner.submit(job)
    assert runner.wait_idle(60)
    return job


def test_wrong_key_stops_at_first_image_and_says_so(tmp_path):
    deps = WrongKeyDeps()
    job = run(tmp_path, deps)
    st = job.step("read")
    assert job.state["status"] == "error" and st["status"] == "error"
    assert deps.reads == 1                                        # 그림 8장을 같은 실패로 되풀이하지 않는다
    assert "Gemini API 키가 맞지 않습니다" in st["error"] and "설정" in st["error"]
    assert "_logs/errors.log" in st["error"]                      # 자세한 기록 위치는 알려 준다
    assert not LEAK.search(st["error"]), st["error"]
    assert not LEAK.search(json.dumps(job.state["log"], ensure_ascii=False))   # 제작 기록에도 없다
    assert st["sub"][0]["status"] == "error" and "키가 맞지 않습니다" in st["sub"][0]["note"]
    log = (job.dir / "_logs" / "errors.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in log and "GeminiApiError" in log   # 파일에는 남는다


def test_step_error_with_plain_exception_keeps_korean_message(tmp_path):
    deps = FakeDeps()
    deps.fail_once.add("make_voice")
    job = run(tmp_path, deps, {"auto_steps": ["read", "script"]})
    st = job.step("voice")
    assert job.state["status"] == "error" and "일부러 실패" in st["error"]
    assert not LEAK.search(st["error"]) and "_logs/errors.log" in st["error"]
    assert (job.dir / "_logs" / "errors.log").is_file()


def test_read_failure_without_key_text_keeps_old_message(tmp_path):
    """키 문제가 아닌 읽기 실패는 예전처럼 '글자를 하나도 읽지 못했습니다'로 모은다."""
    deps = FakeDeps()

    def boom(images, instruction):
        raise RuntimeError("모델이 이상한 답을 냄")
    deps.read_image = boom
    job = run(tmp_path, deps)
    st = job.step("read")
    assert st["status"] == "error" and "글자를 하나도 읽지 못했습니다" in st["error"]


def test_archive_error_text_has_no_class_name(tmp_path, monkeypatch):
    from recap_shorts import archive
    monkeypatch.setattr(archive, "_sha256", lambda p: (_ for _ in ()).throw(OSError("disk")))
    job = P.JobStore(tmp_path).create(dict(SRC), {"auto_steps": ["read"]})
    drive = tmp_path / "drive" / "보관"
    drive.mkdir(parents=True)
    (job.dir / "out").mkdir(parents=True, exist_ok=True)
    (job.dir / "out" / "x.txt").write_text("x", encoding="utf-8")
    res = archive.archive_job(job.dir, drive / job.id, delete_local=False)
    assert not res["ok"] and "OSError" not in res["error"] and str(tmp_path) not in res["error"]
