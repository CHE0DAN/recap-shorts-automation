"""이 컴퓨터에 Windows 폴더 고르기 창을 띄운다(설정 화면 '효과음 폴더 → 폴더 고르기').

앱 화면은 바탕화면 창(pywebview) 안의 페이지라 브라우저 폴더 창으로는 실제 경로를 못 받는다. 그래서 서버가
PowerShell(System.Windows.Forms.FolderBrowserDialog)을 따로 띄워 고른 경로를 받는다 — 서버와 같은 프로세스에서
창을 만들지 않으므로 서버 스레드와 섞이지 않는다. 맨 앞에 뜨도록 보이지 않는 TopMost 창을 주인으로 준다.
"""
from __future__ import annotations

import os
import subprocess
import sys

TIMEOUT_S = 600   # 사람이 고르는 동안 기다리는 시간

_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.WindowState = 'Minimized'
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = $env:RECAP_PICK_TITLE
$d.ShowNewFolderButton = $false
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.SelectedPath) }
$owner.Dispose()
"""


class PickError(Exception):
    """폴더 고르기 창을 띄우지 못함(Windows 가 아님, PowerShell 없음, 시간 초과)."""


def pick(title: str) -> str | None:
    """고른 폴더의 절대 경로. 취소하면 None."""
    if sys.platform != "win32":
        raise PickError("폴더 고르기 창은 Windows 에서만 됩니다 — 경로를 직접 붙여 넣으세요")
    env ={**os.environ, "RECAP_PICK_TITLE": title}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
                            "-Command", _SCRIPT],
                           capture_output=True, timeout=TIMEOUT_S, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise PickError("PowerShell 을 찾지 못해 폴더 고르기 창을 띄울 수 없습니다 — 경로를 직접 붙여 넣으세요")
    except subprocess.TimeoutExpired:
        raise PickError("폴더 고르기 창이 너무 오래 열려 있어 닫았습니다 — 다시 누르거나 경로를 직접 붙여 넣으세요")
    if r.returncode != 0:
        raise PickError("폴더 고르기 창을 띄우지 못했습니다 — 경로를 직접 붙여 넣으세요")
    path = r.stdout.decode("utf-8", errors="replace").strip().lstrip("﻿")
    return path or None
