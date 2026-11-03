# 바탕화면·시작 메뉴 바로가기 설치 (다시 실행하면 덮어씀)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\pythonw.exe'
$ico = Join-Path $root 'assets\app\icon.ico'
$name = '커뮤니티 쇼츠 자동 제작.lnk'
$oldName = '쇼츠 자동 제작.lnk'   # 예전 이름의 바로가기 — 이 설치를 가리킬 때만 지운다
$dirs = @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('Programs')) ''))
$sh = New-Object -ComObject WScript.Shell
foreach ($d in $dirs) {
    $o = Join-Path $d $oldName
    if ((Test-Path -LiteralPath $o) -and ($sh.CreateShortcut($o).TargetPath -eq $py)) {
        Remove-Item -LiteralPath $o
    }
    $p = Join-Path $d $name
    $l = $sh.CreateShortcut($p)
    $l.TargetPath = $py
    $l.Arguments = '-m recap_shorts.desktop'
    $l.WorkingDirectory = $root
    $l.IconLocation = "$ico,0"
    $l.Description = '커뮤니티 쇼츠 자동 제작'
    $l.Save()
    Write-Output $p
}
