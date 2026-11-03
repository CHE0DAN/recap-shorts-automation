"""데스크톱 실행기: pythonw -m recap_shorts.desktop [--port N] [--work DIR] [--no-extra-tabs]
기본 포트는 8020. 창(pywebview) 하나에 썰쇼츠를 띄우고, 이 PC 에만 있는 추가 탭(recap_shorts/local_tabs.py,
gitignore)이 있으면 같은 창에 탭으로 붙인다. 없으면 썰쇼츠만 뜬다. 콘솔 창은 어디에도 뜨지 않는다."""
import argparse
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .shell import shell_html

ROOT = Path(__file__).resolve().parent.parent
TITLE = "커뮤니티 쇼츠 자동 제작"
APP_ID = "recapshorts.app"
ICON = ROOT / "assets" / "app" / "icon.ico"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008
STARTF_USESHOWWINDOW = 0x00000001


# ------------------------------------------------------------ 자식 콘솔 숨기기
def hide_console_flags(kwargs: dict) -> dict:
    """Popen 인자에 CREATE_NO_WINDOW 와 SW_HIDE 를 덧붙인다 (새 콘솔·분리 요청은 존중)."""
    kw = dict(kwargs)
    flags = kw.get("creationflags", 0) or 0
    if not flags & (CREATE_NEW_CONSOLE | DETACHED_PROCESS):
        kw["creationflags"] = flags | CREATE_NO_WINDOW
    if kw.get("startupinfo") is None and hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kw["startupinfo"] = si
    return kw


def patch_popen() -> None:
    if os.name != "nt" or getattr(subprocess.Popen, "_recap_hidden", False):
        return
    orig = subprocess.Popen.__init__

    def init(self, *a, **kw):
        orig(self, *a, **hide_console_flags(kw))

    subprocess.Popen.__init__ = init
    subprocess.Popen._recap_hidden = True


# ------------------------------------------------------------ 로그
def setup_logging(log_dir: Path) -> Path:
    """pythonw 는 stdout/stderr 가 None → 파일로 돌리고 logging 에는 회전 핸들러를 건다.
    stdout 은 따로 둔다: 같은 파일을 열어 두면 윈도우에서 회전(이름 바꾸기)이 막힌다."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "desktop.log"
    out = log_dir / "desktop.stdout.log"
    try:
        if out.stat().st_size > 5 * 1024 * 1024:
            out.unlink()
    except OSError:
        pass
    stream = open(out, "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    h = logging.handlers.RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [h]
        lg.setLevel(logging.INFO)
        if name:
            lg.propagate = False
    return path


# ------------------------------------------------------------ 서버 확인
def fetch_json(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def is_our_server(port: int, fetch=None) -> bool:
    """이 포트에 이미 우리 앱이 떠 있는지 (/api/health 에 gemini_key)."""
    try:
        d = (fetch or fetch_json)(f"http://127.0.0.1:{port}/api/health")
        return isinstance(d, dict) and "gemini_key" in d
    except Exception:  # noqa: BLE001
        return False


def port_in_use(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_health(port: int, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if is_our_server(port):
            return True
        time.sleep(0.3)
    return False


def has_running_job(port: int, fetch=None) -> bool:
    try:
        jobs = (fetch or fetch_json)(f"http://127.0.0.1:{port}/api/jobs")
        return any(isinstance(j, dict) and j.get("status") == "running" for j in jobs)
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------ 윈도우 보조
def find_window(title: str = TITLE):
    try:
        import ctypes
        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p
        return u.FindWindowW(None, title) or None
    except Exception:  # noqa: BLE001
        return None


def focus_window(hwnd) -> None:
    """이미 열린 창을 앞으로 (최소화돼 있으면 되살림)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        if u.IsIconic(ctypes.c_void_p(hwnd)):
            u.ShowWindow(hwnd, 9)  # SW_RESTORE
        u.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


def message_box(text: str, flags: int = 0x10, owner=None) -> int:
    try:
        import ctypes
        u = ctypes.windll.user32
        u.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        return u.MessageBoxW(owner, text, TITLE, flags | 0x40000)  # MB_TOPMOST — 창 뒤에 숨지 않게
    except Exception:  # noqa: BLE001
        return 0


def set_window_icon(title: str, icon: Path) -> None:
    """pywebview 는 윈도우 아이콘을 안 바꾸므로 WM_SETICON 으로 직접 지정."""
    try:
        import ctypes
        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p
        u.LoadImageW.restype = ctypes.c_void_p
        u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        hwnd = u.FindWindowW(None, title)
        if not hwnd or not icon.exists():
            return
        for kind, size in ((0, 16), (1, 32)):  # ICON_SMALL, ICON_BIG
            h = u.LoadImageW(None, str(icon), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                u.SendMessageW(hwnd, 0x80, kind, h)  # WM_SETICON
    except Exception:  # noqa: BLE001
        logging.getLogger("desktop").exception("아이콘 지정 실패")


def find_edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return None


def open_fallback(url: str) -> None:
    edge = find_edge()
    if edge:
        subprocess.Popen([edge, f"--app={url}"])
    else:
        import webbrowser
        webbrowser.open(url)


# ------------------------------------------------------------ 탭 상태 (창 안 JS 가 부른다)
def load_local_tabs(log_dir: Path | None = None) -> list:
    """이 PC 전용 추가 탭 모듈(recap_shorts/local_tabs.py)이 있으면 그 탭들을, 없으면 빈 목록.
    모듈이 깨져 있어도 썰쇼츠는 뜨게 조용히 넘어간다."""
    import importlib
    try:
        mod = importlib.import_module(f"{__package__}.local_tabs")
    except ImportError:
        return []
    try:
        return list(mod.tabs(log_dir) or [])
    except Exception:  # noqa: BLE001
        logging.getLogger("desktop").exception("추가 탭 준비 실패 — 썰쇼츠만 띄움")
        return []


class ShellApi:
    """js_api: 탭 점 상태를 알려 주고 꺼진 탭을 다시 켠다. 속성은 _ 로 숨김(pywebview 가 훑지 않게)."""

    def __init__(self, port: int, tabs=()):
        self._port, self._tabs = port, list(tabs)

    def status(self):
        st = {"sul": "on" if is_our_server(self._port) else "off"}
        for t in self._tabs:
            st[t.id] = t.state()
        return st

    def relaunch(self, tab):
        for t in self._tabs:
            if t.id == tab:
                return bool(t.relaunch())
        return False


# ------------------------------------------------------------ 실행
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.desktop")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--work", default=None, help="작업 폴더 (기본 work/ 또는 RECAP_WORK_ROOT)")
    ap.add_argument("--no-extra-tabs", action="store_true", help="이 PC 전용 추가 탭 없이 썰쇼츠만")
    a = ap.parse_args(argv)

    patch_popen()
    work = Path(a.work or os.environ.get("RECAP_WORK_ROOT") or ROOT / "work")
    log_path = setup_logging(work / "_logs")
    log = logging.getLogger("desktop")
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        pass

    url = f"http://127.0.0.1:{a.port}/"
    server = thread = None
    tabs: list = []
    if is_our_server(a.port):
        hwnd = find_window()
        if hwnd:  # 아이콘을 두 번 눌렀을 때 — 창을 하나 더 만들지 않고 앞으로
            log.info("이미 열린 창을 앞으로")
            focus_window(hwnd)
            return 0

    def start_tabs():
        """이 PC 전용 추가 탭(있으면)을 시작. 이미 떠 있는 서버면 붙기만."""
        if a.no_extra_tabs:
            log.info("추가 탭 없이 썰쇼츠만 띄움(--no-extra-tabs)")
            return []
        found = load_local_tabs(work / "_logs")
        for t in found:
            log.info("추가 탭 %s: %s", t.id, t.start())
        return found

    if is_our_server(a.port):
        log.info("이미 떠 있는 서버에 연결: %s", url)
        tabs = start_tabs()
    elif port_in_use(a.port):
        message_box(f"포트 {a.port} 을(를) 다른 프로그램이 쓰고 있습니다.\n--port 로 다른 번호를 지정하세요.")
        return 1
    else:
        import uvicorn
        from .app import create_app
        server = uvicorn.Server(uvicorn.Config(create_app(work_root=a.work), host="127.0.0.1",
                                               port=a.port, log_config=None))
        thread = threading.Thread(target=server.run, daemon=True, name="uvicorn")
        thread.start()
        tabs = start_tabs()  # 두 서버가 동시에 켜지도록
        if not wait_health(a.port, 30):
            log.error("서버가 30초 안에 켜지지 않음")
            message_box(f"서버를 시작하지 못했습니다.\n로그: {log_path}")
            server.should_exit = True
            for t in tabs:
                t.stop()
            return 1

    try:
        import webview
    except Exception:  # noqa: BLE001
        log.warning("pywebview 없음 — 브라우저 앱 모드로 열고, 창 닫힘은 추적할 수 없음")
        open_fallback(url)
        if thread:
            thread.join()  # 서버를 계속 유지
        return 0

    size = dict(width=1440, height=900, min_size=(1100, 700))
    if tabs:  # 탭 껍데기 — 썰쇼츠 서버를 고치지 않으려고 HTML 을 직접 넘긴다
        html = shell_html(url, [t.tab() for t in tabs])
        window = webview.create_window(TITLE, html=html, js_api=ShellApi(a.port, tabs), **size)
    else:
        window = webview.create_window(TITLE, url, **size)

    def on_closing():
        # 서버를 이 창이 띄웠을 때만 묻는다 (남이 띄운 서버면 창을 닫아도 작업은 계속된다)
        names = []
        if server and has_running_job(a.port):
            names.append("썰쇼츠" if tabs else "이 창")      # 탭 이름은 확장 탭이 있을 때만 보인다
        for t in tabs:
            if t.busy():
                names.append(t.title)
        if names:
            ok = message_box(f"{', '.join(names)}에서 영상을 만드는 중입니다. 닫으면 작업이 멈춥니다. 닫을까요?", 0x24,
                             owner=find_window()) == 6  # YESNO|QUESTION, IDYES
            return ok  # False 면 닫기 취소
        return True

    window.events.closing += on_closing
    window.events.shown += lambda: set_window_icon(TITLE, ICON)
    webview.start()

    if server:
        server.should_exit = True
        thread.join(10)
    for t in tabs:
        t.stop()  # 우리가 띄운 것만 끈다
    log.info("종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
