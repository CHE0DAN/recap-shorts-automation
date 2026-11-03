import io
import subprocess
import sys

from recap_shorts import desktop as D


def test_hide_adds_no_window():
    kw = D.hide_console_flags({})
    assert kw["creationflags"] & D.CREATE_NO_WINDOW
    assert kw["startupinfo"].wShowWindow == 0


def test_hide_keeps_other_flags_and_startupinfo():
    si = subprocess.STARTUPINFO()
    kw = D.hide_console_flags({"creationflags": 0x200, "startupinfo": si})
    assert kw["creationflags"] == 0x200 | D.CREATE_NO_WINDOW
    assert kw["startupinfo"] is si


def test_hide_respects_new_console_and_detached():
    for f in (D.CREATE_NEW_CONSOLE, D.DETACHED_PROCESS):
        assert not D.hide_console_flags({"creationflags": f})["creationflags"] & D.CREATE_NO_WINDOW


def test_single_instance_check():
    assert D.is_our_server(1, fetch=lambda u: {"gemini_key": {"ok": True}})
    assert not D.is_our_server(1, fetch=lambda u: {"other": 1})
    assert not D.is_our_server(1, fetch=lambda u: "<html>")

    def boom(u):
        raise OSError("refused")
    assert not D.is_our_server(1, fetch=boom)


def test_running_job_detection():
    assert D.has_running_job(1, fetch=lambda u: [{"status": "done"}, {"status": "running"}])
    assert not D.has_running_job(1, fetch=lambda u: [{"status": "done"}])


def test_log_redirect_when_stdout_none(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    import logging
    saved = {n: (logging.getLogger(n).handlers[:], logging.getLogger(n).propagate)
             for n in ("", "uvicorn", "uvicorn.error", "uvicorn.access")}
    try:
        p = D.setup_logging(tmp_path / "_logs")
        print("한글 출력")
        logging.getLogger("uvicorn.error").info("시작")
        sys.stdout.flush()
        assert "시작" in p.read_text(encoding="utf-8")
        assert "한글 출력" in (p.parent / "desktop.stdout.log").read_text(encoding="utf-8")
    finally:
        for h in (sys.stdout, ):
            if h and not isinstance(h, io.TextIOWrapper) or getattr(h, "name", "").endswith(".log"):
                h.close()
        for n, (hs, pr) in saved.items():
            lg = logging.getLogger(n)
            for h in lg.handlers:
                h.close()
            lg.handlers, lg.propagate = hs, pr


# ------------------------------------------------------------ 이 PC 전용 추가 탭(로컬 확장)
class _FakeTab:
    def __init__(self, tid="extra", state="on", busy=False):
        self.id, self.title = tid, "추가 탭"
        self._state, self._busy = state, busy
        self.started = self.stopped = self.relaunched = 0

    def tab(self):
        return {"id": self.id, "title": self.title, "url": "http://127.0.0.1:8010/auto",
                "probe": "http://127.0.0.1:8010/health"}

    def start(self):
        self.started += 1
        return "start"

    def stop(self):
        self.stopped += 1

    def state(self):
        return self._state

    def busy(self):
        return self._busy

    def relaunch(self):
        self.relaunched += 1
        return True


def test_local_tabs_absent_yields_empty(monkeypatch):
    """저장소 사본에는 로컬 확장 파일이 없다 — TypeError 없이 빈 목록.
    파일이 있는 PC 에서도 같은 상황이 되게 sys.modules 에 None 을 넣어 import 를 ImportError 로 만든다."""
    import sys
    monkeypatch.setitem(sys.modules, "recap_shorts.local_tabs", None)
    assert D.load_local_tabs() == []


def _fake_module(monkeypatch, tabs_fn):
    """저장소 사본에는 로컬 확장 파일이 없으므로 sys.modules 에 가짜 모듈을 끼워 시험한다."""
    import sys
    import types
    mod = types.ModuleType("recap_shorts.local_tabs")
    mod.tabs = tabs_fn
    monkeypatch.setitem(sys.modules, "recap_shorts.local_tabs", mod)
    return mod


def test_local_tabs_broken_module_skipped(monkeypatch):
    """로컬 모듈이 깨져 있어도 썰쇼츠는 뜬다(예외를 삼킨다)."""
    def boom(*_):
        raise RuntimeError("깨짐")
    _fake_module(monkeypatch, boom)
    assert D.load_local_tabs() == []


def test_local_tabs_loaded(monkeypatch):
    fake = [_FakeTab("extra")]
    _fake_module(monkeypatch, lambda log_dir=None: fake)
    assert D.load_local_tabs() == fake


def test_shell_api_reports_and_relaunches_tabs():
    api = D.ShellApi(1, [_FakeTab("extra", "on")])
    api._port = 0                       # is_our_server 가 항상 False 인 포트
    st = api.status()
    assert st == {"sul": "off", "extra": "on"}
    assert api.relaunch("extra") is True and api._tabs[0].relaunched == 1
    assert api.relaunch("nope") is False


def test_shell_html_has_sul_and_extra_tabs():
    from recap_shorts.shell import shell_html
    h = shell_html("http://127.0.0.1:8020/", [{"id": "extra", "title": "추가 탭", "url": "http://127.0.0.1:8010/auto",
                                               "probe": "http://127.0.0.1:8010/health"}])
    for s in ("썰쇼츠", "추가 탭", "http://127.0.0.1:8020/", "http://127.0.0.1:8010/auto", "iframe", "켜는 중"):
        assert s in h
    assert "__TABS__" not in h and 'target="_blank"' not in h


def test_shell_html_sul_only_when_no_extra_tabs():
    from recap_shorts.shell import shell_html
    h = shell_html("http://127.0.0.1:8020/")
    assert "썰쇼츠" in h and "추가 탭" not in h
