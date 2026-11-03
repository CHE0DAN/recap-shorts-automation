# 커뮤니티 쇼츠 자동 제작 - 한 번에 설치하는 스크립트 (Windows 10/11)
#
# 실행 (저장소 폴더에서):
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# 다시 실행해도 됩니다. 이미 된 단계는 건너뜁니다.
# 옵션:
#   -DryRun      무엇을 할지만 보여 주고 아무것도 바꾸지 않습니다.
#   -NoModels    AI 모델 파일(받아쓰기 약 163 MB) 받기를 건너뜁니다.
#   -Supertonic  로컬 목소리 모델(약 129 MB)도 함께 받습니다.
#   -NoShortcut  바탕화면 바로가기 만들기를 건너뜁니다.
#   -RebuildWeb  화면(web/dist)이 이미 있어도 다시 만듭니다.

param(
    [switch]$DryRun,
    [switch]$NoModels,
    [switch]$Supertonic,
    [switch]$NoShortcut,
    [switch]$RebuildWeb
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Total = 7
$script:StepNo = 0

function Say {
    param([string]$Text)
    $script:StepNo++
    Write-Host ""
    Write-Host ("[" + $script:StepNo + "/" + $Total + "] " + $Text) -ForegroundColor Cyan
}

function Info {
    param([string]$Text)
    Write-Host ("    " + $Text)
}

function Hint {
    param([string]$Text)
    Write-Host ("    [미리보기] " + $Text) -ForegroundColor DarkGray
}

function Warn {
    param([string]$Text)
    Write-Host ("    주의: " + $Text) -ForegroundColor Yellow
}

function Fail {
    param([string]$Message, [string]$Fix = '')
    Write-Host ""
    Write-Host ("  실패: " + $Message) -ForegroundColor Red
    if ($Fix -ne '') {
        Write-Host ("  고치는 법: " + $Fix) -ForegroundColor Yellow
    }
    Write-Host ""
    exit 1
}

# 명령을 실행해 출력을 문자열로 받는다. 없거나 실패하면 빈 문자열.
function Probe {
    param([string]$Exe, [string[]]$ProbeArgs)
    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { return '' }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $cmd.Source @ProbeArgs 2>$null
        if ($LASTEXITCODE -ne 0) { return '' }
        return (($out | Out-String).Trim())
    } catch {
        return ''
    } finally {
        $ErrorActionPreference = $prev
    }
}

# 실제로 실행하고 종료 코드만 돌려준다 (출력은 화면에 그대로 보인다).
# 출력을 파이프라인으로 넘기면 호출한 쪽 변수에 섞이므로 Out-Host 로 화면에만 보낸다.
# pip·npm 은 진행 상황을 stderr 로 쓰는데, PowerShell 5.1 에서 ErrorActionPreference=Stop 이면
# 그것이 예외로 바뀌므로 실행하는 동안만 Continue 로 둔다.
function Invoke-Real {
    param([string]$Exe, [string[]]$CmdArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @CmdArgs | Out-Host
        $code = $LASTEXITCODE
        if ($null -eq $code) { return 1 }
        return $code
    } catch {
        Write-Host ("  실행 실패: " + $_.Exception.Message) -ForegroundColor Red
        return 1
    } finally {
        $ErrorActionPreference = $prev
    }
}

Write-Host "커뮤니티 쇼츠 자동 제작 - 설치 스크립트" -ForegroundColor Green
if ($DryRun) {
    Write-Host "미리보기 모드입니다. 무엇을 할지 보여만 주고 아무것도 바꾸지 않습니다." -ForegroundColor Yellow
}
Info ("저장소: " + $Root)

if (-not (Test-Path (Join-Path $Root 'requirements-app.txt'))) {
    Fail "setup.ps1 이 저장소 폴더 안에 없는 것 같습니다." "setup.ps1 을 저장소 최상위 폴더에 두고, 그 폴더에서 다시 실행하세요."
}

Push-Location -LiteralPath $Root

# ---------------------------------------------------------------- 1. 파이썬
Say "파이썬을 찾습니다 (3.11 이상 필요)."
$py = $null
$pyOld = ''
$cands = @(
    @{ Exe = 'py'; Args = @('-3.11') },
    @{ Exe = 'py'; Args = @('-3') },
    @{ Exe = 'python'; Args = @() }
)
foreach ($c in $cands) {
    if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
    $probeArgs = @($c.Args) + @('-c', 'import sys; print(sys.version_info[0]); print(sys.version_info[1])')
    $v = Probe $c.Exe $probeArgs
    if ($v -eq '') { continue }
    $nums = @($v -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^\d+$' })
    if ($nums.Count -lt 2) { continue }
    $major = [int]$nums[0]
    $minor = [int]$nums[1]
    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
        $py = @{ Exe = $c.Exe; Args = @($c.Args); Ver = ($major.ToString() + '.' + $minor.ToString()) }
        break
    }
    $pyOld = $major.ToString() + '.' + $minor.ToString()
}
if ($null -eq $py) {
    if ($pyOld -ne '') {
        Fail ("파이썬 " + $pyOld + " 은(는) 너무 오래되었습니다 (3.11 이상 필요).") "https://www.python.org/downloads/ 에서 3.11 이상을 설치하고, 설치 화면에서 'Add python.exe to PATH' 를 체크한 뒤 창을 새로 열어 다시 실행하세요."
    }
    Fail "파이썬을 찾지 못했습니다 (3.11 이상 필요)." "https://www.python.org/downloads/ 에서 설치하고, 설치 화면에서 'Add python.exe to PATH' 를 체크한 뒤 창을 새로 열어 다시 실행하세요."
}
Info ("파이썬 " + $py.Ver + " 을(를) 씁니다 (" + $py.Exe + " " + ($py.Args -join ' ') + ").")

$venvDir = Join-Path $Root '.venv'
$venvPy = Join-Path $venvDir 'Scripts\python.exe'
if (Test-Path $venvPy) {
    Info "이미 만든 전용 파이썬 환경(.venv)이 있습니다 - 그대로 씁니다."
} else {
    Info "전용 파이썬 환경(.venv)을 만듭니다 - 1~2분 걸립니다."
    if ($DryRun) {
        Hint (($py.Exe + ' ' + ($py.Args -join ' ') + ' -m venv .venv').Trim())
    } else {
        $code = Invoke-Real $py.Exe (@($py.Args) + @('-m', 'venv', $venvDir))
        if ($code -ne 0 -or -not (Test-Path $venvPy)) {
            Fail "전용 파이썬 환경(.venv)을 만들지 못했습니다." ("창을 닫았다가 다시 실행해 보세요. 계속 안 되면 직접 실행해 보세요: " + $py.Exe + " " + ($py.Args -join ' ') + " -m venv .venv")
        }
        Info "만들었습니다: .venv"
    }
}

# ---------------------------------------------------------------- 2. 파이썬 패키지
Say "앱에 필요한 파이썬 패키지를 설치합니다 (몇 분 걸릴 수 있습니다)."
$reqFiles = @('requirements-app.txt', 'requirements-render.txt', 'requirements-voice.txt')
foreach ($rf in $reqFiles) {
    if (-not (Test-Path (Join-Path $Root $rf))) {
        Fail ($rf + " 파일이 없습니다.") "저장소를 다시 받거나, 받은 압축을 풀 때 일부 파일이 빠지지 않았는지 확인하세요."
    }
}
if ($DryRun) {
    Hint ".venv\Scripts\python -m pip install -r requirements-app.txt -r requirements-render.txt -r requirements-voice.txt"
} else {
    $code = Invoke-Real $venvPy @('-m', 'pip', 'install', '-r', 'requirements-app.txt', '-r', 'requirements-render.txt', '-r', 'requirements-voice.txt')
    if ($code -ne 0) {
        Fail "파이썬 패키지 설치에 실패했습니다." "인터넷 연결을 확인하고 창을 닫았다가 다시 실행하세요. 계속 안 되면 같은 폴더에서 '.venv\Scripts\python -m pip install -r requirements-app.txt -r requirements-render.txt -r requirements-voice.txt' 를 직접 실행해 오류 메시지를 확인하세요."
    }
    Info "패키지 설치 끝."
}

# ---------------------------------------------------------------- 3. 화면(web)
Say "화면(web/dist)을 준비합니다."
$distIndex = Join-Path $Root 'web\dist\index.html'
if ((Test-Path $distIndex) -and (-not $RebuildWeb)) {
    Info "화면이 이미 만들어져 있습니다 - 건너뜁니다. 다시 만들려면 -RebuildWeb 을 붙여 실행하세요."
} else {
    if (-not (Test-Path (Join-Path $Root 'web\package.json'))) {
        Fail "web 폴더가 없습니다." "저장소를 다시 받으세요(web 폴더가 빠졌습니다)."
    }
    $nodeVer = Probe 'node' @('--version')
    if ($nodeVer -eq '') {
        Fail "화면을 만들 Node.js 가 없습니다 (20 이상 필요)." "https://nodejs.org/ 에서 LTS 를 설치한 뒤, 창을 닫았다가 새로 열어 다시 실행하세요."
    }
    $nodeVer = $nodeVer.Trim().TrimStart('v')
    $nodeParts = @($nodeVer -split '\.')
    $nodeMajor = 0
    if ($nodeParts.Count -ge 1 -and $nodeParts[0] -match '^\d+$') {
        $nodeMajor = [int]$nodeParts[0]
    }
    if ($nodeMajor -lt 20) {
        Fail ("Node.js 20 이상이 필요합니다 (지금 v" + $nodeVer + ").") "https://nodejs.org/ 에서 LTS 를 설치한 뒤, 창을 닫았다가 새로 열어 다시 실행하세요."
    }
    Info ("Node.js v" + $nodeVer + " 있습니다.")
    $npm = 'npm'
    $npmCmd = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
    if ($npmCmd) { $npm = $npmCmd.Source }

    $installArgs = @('install')
    if (Test-Path (Join-Path $Root 'web\package-lock.json')) {
        $installArgs = @('ci')
    }
    if ($DryRun) {
        Hint ("cd web; " + $npm + " " + ($installArgs -join ' '))
        Hint "cd web; npm run build"
    } else {
        Push-Location -LiteralPath (Join-Path $Root 'web')
        try {
            Info ("화면 패키지를 설치합니다: npm " + ($installArgs -join ' '))
            $code = Invoke-Real $npm $installArgs
            if ($code -ne 0) {
                Fail "화면 패키지 설치에 실패했습니다 (npm)." "인터넷 연결을 확인하세요. 계속 안 되면 web 폴더에서 'npm install' 을 직접 실행해 오류 메시지를 확인하세요."
            }
            Info "화면을 만듭니다: npm run build (1~2분)."
            $code = Invoke-Real $npm @('run', 'build')
            if ($code -ne 0) {
                Fail "화면 만들기(npm run build)에 실패했습니다." "web 폴더에서 'npm run build' 를 직접 실행해 오류 메시지를 확인하세요."
            }
        } finally {
            Pop-Location
        }
        if (-not (Test-Path $distIndex)) {
            Fail "화면 파일(web\dist\index.html)이 만들어지지 않았습니다." "web 폴더에서 'npm run build' 를 직접 실행해 오류 메시지를 확인하세요."
        }
        Info "화면 준비 끝."
    }
}

# ---------------------------------------------------------------- 4. ffmpeg
Say "ffmpeg(영상 인코딩 도구)가 있는지 봅니다."
$ffmpeg = Get-Command 'ffmpeg' -ErrorAction SilentlyContinue
if ($ffmpeg) {
    Info "ffmpeg 있음: $($ffmpeg.Source)"
} else {
    Warn "ffmpeg 가 PATH 에 없습니다. 없으면 영상을 만들 수 없습니다."
    Info "PowerShell 창에서 한 줄로 설치할 수 있습니다: winget install --id Gyan.FFmpeg -e"
    Info "설치한 뒤 이 창을 닫고 새로 열어 setup.ps1 을 다시 실행하세요."
}

# ---------------------------------------------------------------- 5. Microsoft Edge
Say "Microsoft Edge 가 있는지 봅니다 (글 화면을 찍을 때 씁니다)."
$edge = $null
if (${env:ProgramFiles(x86)}) {
    $p = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
    if (Test-Path $p) { $edge = $p }
}
if ($null -eq $edge) {
    if ($env:ProgramFiles) {
        $p = Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'
        if (Test-Path $p) { $edge = $p }
    }
}
if ($null -eq $edge) {
    $edgeCmd = Get-Command 'msedge' -ErrorAction SilentlyContinue
    if ($edgeCmd) { $edge = $edgeCmd.Source }
}
if ($null -eq $edge) {
    Warn "Microsoft Edge 가 없습니다. 글 화면 캡처가 안 될 수 있습니다."
    Info "https://www.microsoft.com/edge 에서 설치하세요 (Windows 10/11 에는 보통 들어 있습니다)."
} else {
    Info "Edge 있음: $edge"
}

# ---------------------------------------------------------------- 6. AI 모델 파일
Say "AI 모델 파일을 받습니다."
$setupModels = Join-Path $Root 'scripts\setup_models.py'
if ($NoModels) {
    Info "-NoModels: 모델 파일 받기를 건너뜁니다."
    Info "나중에 받으려면: .venv\Scripts\python scripts\setup_models.py"
} elseif (-not (Test-Path $setupModels)) {
    Warn "scripts\setup_models.py 가 없어 모델을 받지 못했습니다."
    Info "나중에 저장소를 다시 받은 뒤 받으세요. 모델이 없어도 영상은 만들 수 있습니다(발음 확인·로컬 목소리만 건너뜀)."
} else {
    $mArgs = @('scripts\setup_models.py')
    Info "받아쓰기 모델을 받습니다 - 약 163 MB, 몇 분 걸립니다."
    if ($Supertonic) {
        $mArgs += '--supertonic'
        Info "-Supertonic: 로컬 목소리 모델(약 129 MB)도 함께 받습니다."
    }
    if ($DryRun) {
        Hint (".venv\Scripts\python " + ($mArgs -join ' '))
    } else {
        $code = Invoke-Real $venvPy $mArgs
        if ($code -ne 0) {
            Warn "모델을 다 받지 못했습니다. 그래도 앱은 열립니다(발음 확인·로컬 목소리만 건너뜀)."
            Info "나중에 다시 받으려면: .venv\Scripts\python scripts\setup_models.py"
        }
    }
}

# ---------------------------------------------------------------- 7. 바로가기
if ($NoShortcut) {
    Say "바탕화면 바로가기를 건너뜁니다 (-NoShortcut)."
    Info "나중에 만들려면: .venv\Scripts\python scripts\make_app_icon.py  다음  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1"
} else {
    Say "바탕화면 바로가기를 만듭니다."
    $makeIcon = Join-Path $Root 'scripts\make_app_icon.py'
    $installShortcut = Join-Path $Root 'scripts\install_shortcut.ps1'
    if ($DryRun) {
        Hint ".venv\Scripts\python scripts\make_app_icon.py"
        Hint "powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1"
    } else {
        if (Test-Path $makeIcon) {
            $code = Invoke-Real $venvPy @('scripts\make_app_icon.py')
            if ($code -ne 0) { Warn "앱 아이콘을 만들지 못했습니다(바로가기는 계속 만듭니다)." }
        }
        if (-not (Test-Path $installShortcut)) {
            Warn "scripts\install_shortcut.ps1 이 없습니다. 바로가기를 만들지 못했습니다."
        } else {
            $code = Invoke-Real 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installShortcut)
            if ($code -ne 0) {
                Warn "바로가기를 만들지 못했습니다. 직접 실행해 보세요: powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1"
            } else {
                Info "바탕화면·시작 메뉴에 '커뮤니티 쇼츠 자동 제작' 바로가기를 만들었습니다."
            }
        }
    }
}

# ---------------------------------------------------------------- 안내
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
if ($DryRun) {
    Write-Host "미리보기 끝. 실제로는 아무것도 바꾸지 않았습니다." -ForegroundColor Yellow
    Write-Host "설치하려면 -DryRun 을 빼고 다시 실행하세요." -ForegroundColor Yellow
    Write-Host "------------------------------------------------" -ForegroundColor Green
    Write-Host "[설치가 끝나면 이렇게 안내합니다]" -ForegroundColor Yellow
}
if ($NoShortcut) {
    Write-Host "바로가기를 안 만들었으므로 아래 '개발용으로 직접 켜기' 로 앱을 켜고,"
    Write-Host "그 화면의 오른쪽 위 '설정'에서 Gemini API 키를 넣으세요."
} else {
    Write-Host "바탕화면의 '커뮤니티 쇼츠 자동 제작'을 열고, 오른쪽 위 '설정'에서 Gemini API 키를 넣으세요."
}
Write-Host "(키를 넣고 저장하면 연결을 한 번 확인합니다.)"
Write-Host ""
Write-Host "Gemini API 키 만들기: https://aistudio.google.com/apikey"
Write-Host "개발용으로 직접 켜기: .venv\Scripts\python -m recap_shorts.app"
Write-Host "                      -> http://127.0.0.1:8020 (다른 번호는 --port)"
if (-not $DryRun) {
    Write-Host ""
    Write-Host "다시 실행해도 됩니다(이미 된 단계는 건너뜀)." -ForegroundColor DarkGray
}
Write-Host "================================================" -ForegroundColor Green

Pop-Location
exit 0
