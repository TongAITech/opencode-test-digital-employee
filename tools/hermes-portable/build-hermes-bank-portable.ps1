$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version 2.0

$HermesTag = 'v2026.9.14'
$HermesVersion = '0.21.3'
$AgentBrowserVersion = '0.26.0'
$CamofoxVersion = '1.5.2'
$RipgrepVersion = '15.1.0'
$GitVersion = '2.54.0'
$GitTag = 'v2.54.0.windows.1'
$PackageName = "Hermes-Agent-Bank-Portable-$HermesTag-Win10-x64"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$OutDir = Join-Path $RepoRoot 'out'
$StageRoot = Join-Path $env:RUNNER_TEMP 'hermes-bank-portable-stage'
$Payload = Join-Path $StageRoot 'payload'
$HermesRootPhysical = Join-Path $Payload 'hermes'
$FinalZip = Join-Path $OutDir "$PackageName.zip"

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    Write-Host "> $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $FilePath $($Arguments -join ' ')"
    }
}

function Set-PortableEnvironment {
    $env:HERMES_HOME = 'R:\hermes'
    $env:PLAYWRIGHT_BROWSERS_PATH = 'R:\hermes\browser\ms-playwright'
    $env:HERMES_GIT_BASH_PATH = 'R:\hermes\git\bin\bash.exe'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $prefix = @(
        'R:\hermes\bin',
        'R:\hermes\node',
        'R:\hermes\node\node_modules\.bin',
        'R:\hermes\git\cmd',
        'R:\hermes\git\bin',
        'R:\hermes\git\usr\bin',
        'R:\hermes\tools\rg',
        'R:\hermes\tools\ffmpeg\bin'
    ) -join ';'
    $env:Path = "$prefix;$env:Path"
}

function Remove-RDrive {
    try {
        $subst = (& subst 2>$null) -join "`n"
        if ($subst -match '(?im)^R:\\:') { & subst R: /D | Out-Null }
    } catch { }
}

function Find-HermesLauncher {
    $candidates = @(
        'R:\hermes\bin\hermes.exe',
        'R:\hermes\bin\hermes.cmd',
        'R:\hermes\bin\hermes.bat',
        'R:\hermes\hermes-agent\.venv\Scripts\hermes.exe',
        'R:\hermes\hermes-agent\.venv\Scripts\hermes.cmd'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Hermes launcher not found. Checked: $($candidates -join ', ')"
}

if ([Environment]::Is64BitOperatingSystem -ne $true) {
    throw 'This package is Windows x64 only.'
}

Write-Step 'Prepare clean staging area at fixed portable drive R:'
Remove-RDrive
Remove-Item -Recurse -Force $StageRoot -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Payload, $HermesRootPhysical, $OutDir | Out-Null
& subst R: $Payload
if ($LASTEXITCODE -ne 0) { throw "subst R: failed for $Payload" }
Set-PortableEnvironment

try {
    Write-Step "Install Hermes Agent $HermesTag into portable payload"
    $installer = Join-Path $env:RUNNER_TEMP 'hermes-install.ps1'
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/NousResearch/hermes-agent/$HermesTag/scripts/install.ps1" -OutFile $installer
    $ps = (Get-Command powershell.exe).Source
    Invoke-Checked $ps '-NoProfile' '-ExecutionPolicy' 'Bypass' '-File' $installer `
        '-Tag' $HermesTag `
        '-SkipSetup' `
        '-SkipComputerUse' `
        '-NonInteractive' `
        '-HermesHome' 'R:\hermes' `
        '-InstallDir' 'R:\hermes\hermes-agent'

    Write-Step 'Bundle PortableGit x64 (do not depend on target PC Git)'
    $gitDir = 'R:\hermes\git'
    Remove-Item -Recurse -Force $gitDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $gitDir | Out-Null
    $gitAsset = "PortableGit-$GitVersion-64-bit.7z.exe"
    $gitArchive = Join-Path $env:RUNNER_TEMP $gitAsset
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/$GitTag/$gitAsset"
    Invoke-WebRequest -UseBasicParsing -Uri $gitUrl -OutFile $gitArchive
    $proc = Start-Process -FilePath $gitArchive -ArgumentList "-o`"$gitDir`"", '-y' -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -ne 0) { throw "PortableGit extraction failed: $($proc.ExitCode)" }
    if (-not (Test-Path "$gitDir\cmd\git.exe")) { throw 'PortableGit git.exe missing after extraction' }
    if (-not (Test-Path "$gitDir\bin\bash.exe")) { throw 'PortableGit bash.exe missing after extraction' }

    Write-Step 'Bundle portable Node.js 22 x64 + npm'
    $nodeDir = 'R:\hermes\node'
    Remove-Item -Recurse -Force $nodeDir -ErrorAction SilentlyContinue
    $nodeIndex = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json'
    $nodeEntry = $nodeIndex | Where-Object { $_.version -match '^v22\.' } | Select-Object -First 1
    if (-not $nodeEntry) { throw 'Could not resolve a Node.js v22 release' }
    $NodeVersion = [string]$nodeEntry.version
    $nodeZipName = "node-$NodeVersion-win-x64.zip"
    $nodeZip = Join-Path $env:RUNNER_TEMP $nodeZipName
    Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/$NodeVersion/$nodeZipName" -OutFile $nodeZip
    $nodeExtract = Join-Path $env:RUNNER_TEMP 'node-extract'
    Remove-Item -Recurse -Force $nodeExtract -ErrorAction SilentlyContinue
    Expand-Archive -Path $nodeZip -DestinationPath $nodeExtract -Force
    $nodeSource = Get-ChildItem -Path $nodeExtract -Directory | Select-Object -First 1
    if (-not $nodeSource) { throw 'Node archive did not contain a directory' }
    Move-Item -Path $nodeSource.FullName -Destination $nodeDir
    if (-not (Test-Path "$nodeDir\node.exe")) { throw 'Portable Node node.exe missing' }
    Set-PortableEnvironment

    Write-Step "Bundle ripgrep $RipgrepVersion"
    $rgDir = 'R:\hermes\tools\rg'
    New-Item -ItemType Directory -Force -Path $rgDir | Out-Null
    $rgZipName = "ripgrep-$RipgrepVersion-x86_64-pc-windows-msvc.zip"
    $rgZip = Join-Path $env:RUNNER_TEMP $rgZipName
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/BurntSushi/ripgrep/releases/download/$RipgrepVersion/$rgZipName" -OutFile $rgZip
    $rgExtract = Join-Path $env:RUNNER_TEMP 'rg-extract'
    Remove-Item -Recurse -Force $rgExtract -ErrorAction SilentlyContinue
    Expand-Archive -Path $rgZip -DestinationPath $rgExtract -Force
    $rgExe = Get-ChildItem -Path $rgExtract -Filter 'rg.exe' -Recurse | Select-Object -First 1
    if (-not $rgExe) { throw 'rg.exe missing from ripgrep archive' }
    Copy-Item -Path (Join-Path $rgExe.Directory.FullName '*') -Destination $rgDir -Recurse -Force

    Write-Step 'Bundle FFmpeg/FFprobe portable x64'
    $ffmpegDir = 'R:\hermes\tools\ffmpeg\bin'
    New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null
    $ffZip = Join-Path $env:RUNNER_TEMP 'ffmpeg-release-essentials.zip'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $ffZip
    $ffExtract = Join-Path $env:RUNNER_TEMP 'ffmpeg-extract'
    Remove-Item -Recurse -Force $ffExtract -ErrorAction SilentlyContinue
    Expand-Archive -Path $ffZip -DestinationPath $ffExtract -Force
    $ffmpegExe = Get-ChildItem -Path $ffExtract -Filter 'ffmpeg.exe' -Recurse | Select-Object -First 1
    if (-not $ffmpegExe) { throw 'ffmpeg.exe missing from FFmpeg archive' }
    Copy-Item -Path (Join-Path $ffmpegExe.Directory.FullName '*.exe') -Destination $ffmpegDir -Force

    Write-Step 'Bundle agent-browser, Camofox package, and local Chromium'
    Set-PortableEnvironment
    $npm = "$nodeDir\npm.cmd"
    Invoke-Checked $npm 'install' '-g' '--prefix' $nodeDir '--no-fund' '--no-audit' "agent-browser@$AgentBrowserVersion" "@askjo/camofox-browser@$CamofoxVersion"
    $agentBrowser = "$nodeDir\agent-browser.cmd"
    if (-not (Test-Path $agentBrowser)) {
        $agentBrowser = "$nodeDir\node_modules\.bin\agent-browser.cmd"
    }
    if (-not (Test-Path $agentBrowser)) { throw 'agent-browser command missing after npm install' }
    New-Item -ItemType Directory -Force -Path $env:PLAYWRIGHT_BROWSERS_PATH | Out-Null
    Invoke-Checked $agentBrowser 'install'
    $chromiumDir = Get-ChildItem -Path $env:PLAYWRIGHT_BROWSERS_PATH -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^chromium' } | Select-Object -First 1
    if (-not $chromiumDir) { throw "Chromium was not installed under $env:PLAYWRIGHT_BROWSERS_PATH" }

    Write-Step 'Write bank-safe Hermes profile and authentication adapter'
    New-Item -ItemType Directory -Force -Path 'R:\hermes\bank\auth', 'R:\hermes\bank\secrets', 'R:\hermes\logs' | Out-Null

    $config = @'
model:
  default: "aicoder-plus"
  provider: "wizard-bank"
  base_url: "https://wizard-ai.paic.com.cn/code_pilot/api/v1"
  context_length: 148000
  streaming: true

providers:
  wizard-bank:
    name: "Wizard Bank / aicoder-plus"
    base_url: "https://wizard-ai.paic.com.cn/code_pilot/api/v1"
    api_mode: "chat_completions"
    model: "aicoder-plus"
    key_cmd: 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "R:\hermes\bank\auth\get-wizard-token.ps1"'
    discover_models: false
    request_timeout_seconds: 1800

updates:
  check: false

security:
  allow_lazy_installs: false

agent:
  disabled_toolsets:
    - web
  environment_probe: true
  execution_guidance: true
  task_completion_guidance: true
  stall_guards: true

terminal:
  backend: local
  timeout: 300

browser:
  command_timeout: 60
  auto_local_for_private_urls: true
'@
    Set-Content -LiteralPath 'R:\hermes\config.yaml' -Value $config -Encoding UTF8

    $dotenv = @'
# No secrets are stored in this portable package.
PLAYWRIGHT_BROWSERS_PATH=R:\hermes\browser\ms-playwright
HERMES_GIT_BASH_PATH=R:\hermes\git\bin\bash.exe
'@
    Set-Content -LiteralPath 'R:\hermes\.env' -Value $dotenv -Encoding UTF8

    $authHelper = @'
$ErrorActionPreference = 'Stop'
function Fail([string]$Message) {
    [Console]::Error.WriteLine($Message)
    exit 41
}

# 1) Current process environment (best path when DSH/CAS has already exported it).
$token = [Environment]::GetEnvironmentVariable('AIMAX_AUTH_TOKEN', 'Process')
if (-not [string]::IsNullOrWhiteSpace($token)) {
    [Console]::Out.Write($token.Trim())
    exit 0
}

# 2) User/Machine environment (some enterprise login helpers persist the ticket there).
foreach ($scope in @('User', 'Machine')) {
    try {
        $token = [Environment]::GetEnvironmentVariable('AIMAX_AUTH_TOKEN', $scope)
        if (-not [string]::IsNullOrWhiteSpace($token)) {
            [Console]::Out.Write($token.Trim())
            exit 0
        }
    } catch { }
}

# 3) Optional enterprise auth command. It may print a bare token or OAuth-style JSON.
$authCmd = [Environment]::GetEnvironmentVariable('WIZARD_AUTH_CMD', 'Process')
if ([string]::IsNullOrWhiteSpace($authCmd)) {
    $authCmd = [Environment]::GetEnvironmentVariable('WIZARD_AUTH_CMD', 'User')
}
if (-not [string]::IsNullOrWhiteSpace($authCmd)) {
    $output = (& cmd.exe /d /s /c $authCmd 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) {
        Fail 'WIZARD_AUTH_CMD failed or returned an empty token.'
    }
    try {
        $obj = $output | ConvertFrom-Json -ErrorAction Stop
        if ($obj.access_token) {
            [Console]::Out.Write(([string]$obj.access_token).Trim())
            exit 0
        }
    } catch { }
    if ($output -match "[`r`n]") { Fail 'WIZARD_AUTH_CMD must print one bare token or JSON with access_token.' }
    [Console]::Out.Write($output)
    exit 0
}

# 4) Temporary smoke-test fallback. Do not commit/share real tickets.
$tokenFile = 'R:\hermes\bank\secrets\aimax-token.txt'
if (Test-Path -LiteralPath $tokenFile) {
    $token = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
    if (-not [string]::IsNullOrWhiteSpace($token)) {
        [Console]::Out.Write($token)
        exit 0
    }
}

Fail 'No Wizard credential available. Set AIMAX_AUTH_TOKEN or WIZARD_AUTH_CMD, or install the bank CAS hook after supplying the actual wizard-opencode-plugin package.'
'@
    Set-Content -LiteralPath 'R:\hermes\bank\auth\get-wizard-token.ps1' -Value $authHelper -Encoding UTF8

    $tokenTemplate = @'
DO_NOT_PUT_REAL_TOKEN_IN_THE_DISTRIBUTION
Delete this file before using file-token fallback. If used for a one-time smoke test, replace the entire file with only the short-lived token, test, then delete it.
'@
    Set-Content -LiteralPath 'R:\hermes\bank\secrets\README.txt' -Value $tokenTemplate -Encoding UTF8

    Write-Step 'Create portable launch/stop/verification scripts'
    $startPs = @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$HermesArgs)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$payload = Join-Path $root 'payload'
if (-not (Test-Path (Join-Path $payload 'hermes'))) { throw "payload\hermes not found under $root" }

$substLines = (& subst 2>$null) -join "`n"
$expected = [System.IO.Path]::GetFullPath($payload).TrimEnd('\')
$mapped = $null
if ($substLines -match '(?im)^R:\\:\s*=>\s*(.+)$') { $mapped = $Matches[1].Trim().TrimEnd('\') }
if ($mapped -and -not $mapped.Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "R: is already mapped to '$mapped'. This portable runtime requires R: -> '$expected'. Run STOP-HERMES-PORTABLE.cmd if it is an old Hermes mapping."
}
if (-not $mapped) {
    & subst R: $expected
    if ($LASTEXITCODE -ne 0) { throw "Could not map R: to $expected" }
}

$env:HERMES_HOME = 'R:\hermes'
$env:PLAYWRIGHT_BROWSERS_PATH = 'R:\hermes\browser\ms-playwright'
$env:HERMES_GIT_BASH_PATH = 'R:\hermes\git\bin\bash.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:Path = (@(
    'R:\hermes\bin',
    'R:\hermes\node',
    'R:\hermes\node\node_modules\.bin',
    'R:\hermes\git\cmd',
    'R:\hermes\git\bin',
    'R:\hermes\git\usr\bin',
    'R:\hermes\tools\rg',
    'R:\hermes\tools\ffmpeg\bin',
    $env:Path
) -join ';')

$launchers = @(
    'R:\hermes\bin\hermes.exe',
    'R:\hermes\bin\hermes.cmd',
    'R:\hermes\hermes-agent\.venv\Scripts\hermes.exe',
    'R:\hermes\hermes-agent\.venv\Scripts\hermes.cmd'
)
$hermes = $launchers | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $hermes) { throw 'Hermes launcher not found inside payload.' }

Write-Host "Hermes portable root: $root" -ForegroundColor Cyan
Write-Host "Model: wizard-bank/aicoder-plus (context 148000)" -ForegroundColor Cyan
Write-Host "No public update/web/lazy-install is enabled in this profile." -ForegroundColor DarkGray
& $hermes @HermesArgs
exit $LASTEXITCODE
'@
    Set-Content -LiteralPath (Join-Path $StageRoot 'START-HERMES.ps1') -Value $startPs -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $StageRoot 'START-HERMES.cmd') -Encoding ASCII -Value '@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START-HERMES.ps1" %*
exit /b %ERRORLEVEL%
'
    Set-Content -LiteralPath (Join-Path $StageRoot 'START-HERMES-TUI.cmd') -Encoding ASCII -Value '@echo off
call "%~dp0START-HERMES.cmd" --tui
exit /b %ERRORLEVEL%
'

    $stopPs = @'
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$payload = [System.IO.Path]::GetFullPath((Join-Path $root 'payload')).TrimEnd('\')
$substLines = (& subst 2>$null) -join "`n"
$mapped = $null
if ($substLines -match '(?im)^R:\\:\s*=>\s*(.+)$') { $mapped = $Matches[1].Trim().TrimEnd('\') }
if ($mapped -and $mapped.Equals($payload, [System.StringComparison]::OrdinalIgnoreCase)) {
    & subst R: /D | Out-Null
    Write-Host 'Portable R: mapping removed.' -ForegroundColor Green
} elseif ($mapped) {
    Write-Host "R: belongs to another path ($mapped); left unchanged." -ForegroundColor Yellow
} else {
    Write-Host 'No Hermes portable R: mapping exists.' -ForegroundColor DarkGray
}
'@
    Set-Content -LiteralPath (Join-Path $StageRoot 'STOP-HERMES-PORTABLE.ps1') -Value $stopPs -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $StageRoot 'STOP-HERMES-PORTABLE.cmd') -Encoding ASCII -Value '@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0STOP-HERMES-PORTABLE.ps1"
'

    $verifyPs = @'
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $root 'START-HERMES.ps1') '--version'
if ($LASTEXITCODE -ne 0) { throw 'Hermes --version failed' }

$checks = @(
    @{Name='Python private runtime'; Pattern='R:\hermes\hermes-agent\.hermes-runtime\python'; Type='dir'},
    @{Name='Node'; Path='R:\hermes\node\node.exe'},
    @{Name='npm'; Path='R:\hermes\node\npm.cmd'},
    @{Name='PortableGit'; Path='R:\hermes\git\cmd\git.exe'},
    @{Name='Git Bash'; Path='R:\hermes\git\bin\bash.exe'},
    @{Name='ripgrep'; Path='R:\hermes\tools\rg\rg.exe'},
    @{Name='ffmpeg'; Path='R:\hermes\tools\ffmpeg\bin\ffmpeg.exe'},
    @{Name='agent-browser'; Path='R:\hermes\node\agent-browser.cmd'},
    @{Name='Hermes config'; Path='R:\hermes\config.yaml'},
    @{Name='Wizard credential helper'; Path='R:\hermes\bank\auth\get-wizard-token.ps1'}
)
foreach ($c in $checks) {
    $ok = $false
    if ($c.Path) { $ok = Test-Path -LiteralPath $c.Path }
    elseif ($c.Pattern) { $ok = Test-Path -LiteralPath $c.Pattern }
    if (-not $ok) { throw "Missing: $($c.Name)" }
    Write-Host "[OK] $($c.Name)" -ForegroundColor Green
}
$browserRoot = 'R:\hermes\browser\ms-playwright'
$chromium = Get-ChildItem -Path $browserRoot -Directory -ErrorAction Stop | Where-Object { $_.Name -match '^chromium' } | Select-Object -First 1
if (-not $chromium) { throw 'Bundled Chromium not found' }
Write-Host "[OK] Chromium: $($chromium.Name)" -ForegroundColor Green

& 'R:\hermes\node\node.exe' --version
& 'R:\hermes\git\cmd\git.exe' --version
& 'R:\hermes\tools\rg\rg.exe' --version | Select-Object -First 1
& 'R:\hermes\tools\ffmpeg\bin\ffmpeg.exe' -version 2>&1 | Select-Object -First 1
& 'R:\hermes\node\agent-browser.cmd' --version
Write-Host 'PORTABLE_RUNTIME_OK' -ForegroundColor Green
'@
    Set-Content -LiteralPath (Join-Path $StageRoot 'VERIFY-PORTABLE.ps1') -Value $verifyPs -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $StageRoot 'VERIFY-PORTABLE.cmd') -Encoding ASCII -Value '@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0VERIFY-PORTABLE.ps1"
pause
'

    $verifyModelPs = @'
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
# Mount and bootstrap environment first.
& (Join-Path $root 'START-HERMES.ps1') 'chat' '-q' '请只回复：HERMES_BANK_OK'
exit $LASTEXITCODE
'@
    Set-Content -LiteralPath (Join-Path $StageRoot 'VERIFY-AICODER-PLUS.ps1') -Value $verifyModelPs -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $StageRoot 'VERIFY-AICODER-PLUS.cmd') -Encoding ASCII -Value '@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0VERIFY-AICODER-PLUS.ps1"
pause
'

    $readme = @'
# Hermes Agent 行内免安装便携包

## 直接使用

1. 将整个 ZIP 搬进行内 Windows 10/11 x64 办公 PC。
2. 解压到任意本地目录（路径可变化）。
3. 双击 `VERIFY-PORTABLE.cmd`，应看到 `PORTABLE_RUNTIME_OK`。
4. 双击 `START-HERMES.cmd` 进入 Hermes；或双击 `START-HERMES-TUI.cmd`。
5. 模型已预设为行内 `aicoder-plus`，端点为 `https://wizard-ai.paic.com.cn/code_pilot/api/v1`，上下文按 OpenCode 已验证配置设为 148000。

目标 PC 不需要安装 Python、Node、npm、Git、ripgrep、FFmpeg、浏览器或 Hermes，也不需要执行 pip/npm/build。

## 包内已包含

- Hermes Agent v0.21.3 / tag v2026.9.14 源运行时与全部核心 Python 依赖
- Hermes checkout-private Python runtime + venv + uv
- Portable Node.js 22 x64 + npm
- PortableGit 2.54.0 x64 + Git Bash/coreutils/curl/ssh
- ripgrep 15.1.0
- FFmpeg + ffprobe/ffplay（Gyan essentials build）
- agent-browser 0.26.0
- Camofox browser package 1.5.2
- Chromium browser binary
- Hermes 内置 tools、skills、memory、delegation、execute_code、terminal/browser 等源码能力
- 行内 aicoder-plus provider 配置、短期 ticket 适配器、启动/停止/验证脚本

## 行内安全默认

- `updates.check: false`：不检查公网更新
- `security.allow_lazy_installs: false`：运行中禁止临时公网安装依赖
- `agent.disabled_toolsets: [web]`：禁用 Hermes 公网 web toolset
- 包内不保存任何真实 API Key/CAS ticket

## Wizard / CAS 凭据

Hermes 使用 `key_cmd` 调用 `payload\hermes\bank\auth\get-wizard-token.ps1`。该 helper 按顺序读取：

1. 当前进程的 `AIMAX_AUTH_TOKEN`
2. Windows User/Machine 级 `AIMAX_AUTH_TOKEN`
3. `WIZARD_AUTH_CMD`（可接企业 CAS/ticket 命令，stdout 只能输出 token 或 `{ "access_token": "..." }`）
4. 仅供一次性 smoke test 的 `payload\hermes\bank\secrets\aimax-token.txt`

注意：你之前截图里的 `wizard-opencode-plugin` 包含原生 `wkey.*.node`，但实际 ZIP 尚未提供。因此本包不能伪造它的 CAS/wkey 协议。若行内 DSH 登录后已导出 `AIMAX_AUTH_TOKEN`，本包可以直接复用；若需要 Hermes 自己完成 CAS 登录，请提供实际 `wizard-opencode-plugin-share.zip`，届时只需补 `bank\auth` 适配层，无需重建 Hermes/依赖/Chromium 大包。

## 为什么使用 R: 映射

Hermes 的 Python venv/launcher 会携带构建时绝对路径。便携包启动脚本将当前 `payload` 临时映射为 `R:`，因此无论 ZIP 解压到 C:/D:/E: 哪个目录，运行时内部路径始终是 `R:\hermes`。不要把 R: 占用于其他业务盘；如已有其它 R: 映射，启动脚本会拒绝覆盖。

`STOP-HERMES-PORTABLE.cmd` 只会删除指向本包 payload 的 R: 映射，不会碰其他 R: 驱动器。

## 验证模型

凭据已经可用后，双击 `VERIFY-AICODER-PLUS.cmd`。成功应返回 `HERMES_BANK_OK`。

若 portable runtime 验证通过但模型验证失败，优先检查：
- `AIMAX_AUTH_TOKEN` 是否存在/是否过期
- Wizard endpoint 是否从当前办公 PC 可访问
- 行内网关是否还要求 `wizard-opencode-plugin` 注入额外 header/cookie/wkey（这必须以实际插件代码为准，不能从截图猜）

## 版本冻结

此包冻结 Hermes v2026.9.14，不跟随 main 自动升级。`BUILD-MANIFEST.json` 记录构建时实际 Node/npm/FFmpeg 等版本。
'@
    Set-Content -LiteralPath (Join-Path $StageRoot 'README-行内直接使用.md') -Value $readme -Encoding UTF8

    Write-Step 'Run build-time verification against fixed R: runtime'
    Set-PortableEnvironment
    $hermes = Find-HermesLauncher
    Invoke-Checked $hermes '--version'
    Invoke-Checked "$nodeDir\node.exe" '--version'
    Invoke-Checked "$nodeDir\npm.cmd" '--version'
    Invoke-Checked "$gitDir\cmd\git.exe" '--version'
    Invoke-Checked "$rgDir\rg.exe" '--version'
    Invoke-Checked "$ffmpegDir\ffmpeg.exe" '-version'
    Invoke-Checked $agentBrowser '--version'

    $pythonRoot = 'R:\hermes\hermes-agent\.hermes-runtime\python'
    if (-not (Test-Path $pythonRoot)) { throw "Hermes private Python runtime missing at $pythonRoot" }

    $manifest = [ordered]@{
        package = $PackageName
        built_utc = (Get-Date).ToUniversalTime().ToString('o')
        target = 'Windows 10/11 x64, no admin, no install/build required'
        fixed_runtime_root = 'R:\hermes'
        hermes_tag = $HermesTag
        hermes_version = $HermesVersion
        wizard_provider = 'wizard-bank'
        wizard_model = 'aicoder-plus'
        wizard_base_url = 'https://wizard-ai.paic.com.cn/code_pilot/api/v1'
        wizard_context_length = 148000
        node = (& "$nodeDir\node.exe" --version | Select-Object -First 1)
        npm = (& "$nodeDir\npm.cmd" --version | Select-Object -First 1)
        git = (& "$gitDir\cmd\git.exe" --version | Select-Object -First 1)
        ripgrep = (& "$rgDir\rg.exe" --version | Select-Object -First 1)
        ffmpeg = ((& "$ffmpegDir\ffmpeg.exe" -version 2>&1 | Select-Object -First 1) -join '')
        agent_browser = (& $agentBrowser --version | Select-Object -First 1)
        chromium_dir = $chromiumDir.Name
        lazy_installs = $false
        public_update_check = $false
        public_web_toolset = $false
        cas_plugin_embedded = $false
        cas_note = 'Actual wizard-opencode-plugin-share.zip was not supplied; token helper reuses AIMAX_AUTH_TOKEN/WIZARD_AUTH_CMD without fabricating proprietary CAS logic.'
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $StageRoot 'BUILD-MANIFEST.json') -Encoding UTF8

    $critical = @(
        'R:\hermes\config.yaml',
        'R:\hermes\bank\auth\get-wizard-token.ps1',
        'R:\hermes\node\node.exe',
        'R:\hermes\git\cmd\git.exe',
        'R:\hermes\git\bin\bash.exe',
        'R:\hermes\tools\rg\rg.exe',
        'R:\hermes\tools\ffmpeg\bin\ffmpeg.exe'
    )
    $hashLines = foreach ($file in $critical) {
        if (Test-Path $file) {
            $h = Get-FileHash -Algorithm SHA256 -LiteralPath $file
            "$($h.Hash)  $file"
        }
    }
    $hashLines | Set-Content -LiteralPath (Join-Path $StageRoot 'SHA256-CRITICAL.txt') -Encoding ASCII

    Write-Step 'Package final portable ZIP'
    if (Test-Path $FinalZip) { Remove-Item -Force $FinalZip }
    Push-Location $StageRoot
    try {
        $sevenZip = (Get-Command 7z.exe -ErrorAction Stop).Source
        Invoke-Checked $sevenZip 'a' '-tzip' '-mx=1' '-mmt=on' $FinalZip '.\*'
    } finally {
        Pop-Location
    }

    Write-Step 'Relocation smoke test: extract ZIP to a different directory and remap R:'
    Remove-RDrive
    $verifyExtract = Join-Path $env:RUNNER_TEMP 'hermes-portable-relocation-test'
    Remove-Item -Recurse -Force $verifyExtract -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $verifyExtract | Out-Null
    $sevenZip = (Get-Command 7z.exe -ErrorAction Stop).Source
    Invoke-Checked $sevenZip 'x' '-y' "-o$verifyExtract" $FinalZip
    & subst R: (Join-Path $verifyExtract 'payload')
    if ($LASTEXITCODE -ne 0) { throw 'Relocation test could not map R:' }
    Set-PortableEnvironment
    $relocatedLauncher = Find-HermesLauncher
    Invoke-Checked $relocatedLauncher '--version'
    Invoke-Checked 'R:\hermes\node\node.exe' '--version'
    Invoke-Checked 'R:\hermes\git\cmd\git.exe' '--version'
    if (-not (Get-ChildItem 'R:\hermes\browser\ms-playwright' -Directory | Where-Object { $_.Name -match '^chromium' } | Select-Object -First 1)) {
        throw 'Relocated Chromium check failed'
    }
    Write-Host 'RELOCATION_SMOKE_OK' -ForegroundColor Green

    Remove-RDrive
    $zipHash = Get-FileHash -Algorithm SHA256 -LiteralPath $FinalZip
    Set-Content -LiteralPath (Join-Path $OutDir "$PackageName.sha256.txt") -Encoding ASCII -Value "$($zipHash.Hash)  $PackageName.zip"
    Write-Host "`nFINAL_PACKAGE=$FinalZip" -ForegroundColor Green
    Write-Host "FINAL_SHA256=$($zipHash.Hash)" -ForegroundColor Green
} finally {
    Remove-RDrive
}
