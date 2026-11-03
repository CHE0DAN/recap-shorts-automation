"""agy(Antigravity CLI) 어댑터.

- 호출: agy --print "<프롬프트>" --model <모델> --output-format json --sandbox   (프롬프트는 인자로만, stdin 안 씀)
- 응답은 {"status": "SUCCESS", "response": "..."} 봉투. response 안의 JSON 객체를 꺼낸다.
- Windows 명령줄 한계는 약 32,767자(CreateProcess). 인자 하나가 ARG_MAX 를 넘으면 작업 폴더에 prompt.txt 로 두고
  "이 파일을 읽어라"만 전달한다.
- 이 CLI 는 실행 계정의 한도를 쓴다. 호출마다 calls 에 기록하고, max_calls 를 넘으면 호출하지 않고 예외를 낸다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

DEFAULT_MODEL = "gemini-3.8-flash-high"
ARG_MAX = 20000          # 명령줄 한계(~32k)에 넉넉한 여유. 넘으면 파일로 전달
RULES = ("Do not run commands. Do not create, edit or delete any file. "
         "Reply with ONLY one JSON object: no prose, no code fence.")


class AgyUnavailable(RuntimeError):
    pass


class AgyCallLimit(RuntimeError):
    pass


_ESCAPE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def _first_object(text: str, strict: bool = True) -> dict | None:
    dec = json.JSONDecoder(strict=strict)
    for i in [i for i, ch in enumerate(text) if ch == "{"]:
        try:
            obj, _ = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def parse_json_loose(text: str) -> dict:
    """모델 답에서 JSON 객체 하나를 꺼낸다 (```json 울타리, <think> 앞말, 앞뒤 글 허용).
    그대로 못 읽으면 한 번 더 너그럽게 읽는다 — 긴 글을 옮겨 적은 답에서 가끔 나오는 문자열 속 날 탭·줄바꿈과
    JSON 에 없는 이스케이프(\\' \\[ 같은 것, 백슬래시를 글자로 둔다)."""
    text = re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    obj = _first_object(text)
    if obj is None:
        fixed = _ESCAPE.sub(lambda m: m.group(0) if m.group(1) else "\\\\", text)
        obj = _first_object(fixed, strict=False)
    if obj is None:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return obj


def find_agy() -> str:
    env = os.environ.get("RECAP_AGY_PATH")
    default = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    exe = env or shutil.which("agy") or (str(default) if default.is_file() else "")
    if not exe or not Path(exe).is_file():
        raise AgyUnavailable("agy 를 찾을 수 없음 (RECAP_AGY_PATH 로 지정)")
    return exe


class AgyLLM:
    def __init__(self, model: str = DEFAULT_MODEL, *, timeout: float = 300.0, retries: int = 1,
                 max_calls: int | None = None, exe: str | None = None, retry_sleep: float = 2.0):
        self.exe = exe or find_agy()
        self.model, self.timeout, self.retries = model, timeout, retries
        self.max_calls = max_calls
        self.retry_sleep = retry_sleep
        self.calls: list[dict] = []          # {"seconds", "ok", "error", "via_file", "prompt_chars"}
        self.last_usage: dict = {}

    def _run(self, arg: str, work: Path) -> dict:
        cmd = [self.exe, "--print", arg, "--model", self.model, "--output-format", "json", "--sandbox",
               "--print-timeout", f"{int(self.timeout)}s"]
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=self.timeout + 30, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            env = parse_json_loose(r.stdout)
        except ValueError:
            raise RuntimeError(f"agy 결과 없음 (exit {r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}") from None
        if env.get("status") != "SUCCESS":
            raise RuntimeError(f"agy: {env.get('status')} {str(env.get('error') or env.get('response') or '')[:300]}")
        self.last_usage = env.get("usage") or {}
        return parse_json_loose(str(env.get("response") or ""))

    def complete_json(self, prompt: str) -> dict:
        work = Path(tempfile.mkdtemp(prefix="recap_agy_"))
        try:
            full = f"{prompt}\n\n{RULES}"
            via_file = len(full) > ARG_MAX
            if via_file:
                (work / "prompt.txt").write_text(full, encoding="utf-8")
                full = "Read the file prompt.txt in the current folder completely and do exactly what it says. " + RULES
            err: Exception | None = None
            for attempt in range(self.retries + 1):
                if self.max_calls is not None and len(self.calls) >= self.max_calls:
                    raise AgyCallLimit(f"agy 호출 한도 {self.max_calls}회 도달")
                t0 = time.time()
                try:
                    out = self._run(full, work)
                    self.calls.append({"seconds": round(time.time() - t0, 1), "ok": True, "via_file": via_file,
                                       "prompt_chars": len(prompt)})
                    return out
                except (RuntimeError, ValueError, subprocess.TimeoutExpired, OSError) as e:
                    err = RuntimeError(f"agy 시간 초과 {int(self.timeout)}초") if isinstance(e, subprocess.TimeoutExpired) else e
                    self.calls.append({"seconds": round(time.time() - t0, 1), "ok": False, "error": str(err)[:300],
                                       "via_file": via_file, "prompt_chars": len(prompt)})
                    if attempt < self.retries:
                        time.sleep(self.retry_sleep)
            raise err or RuntimeError("agy 요청 실패")
        finally:
            shutil.rmtree(work, ignore_errors=True)
