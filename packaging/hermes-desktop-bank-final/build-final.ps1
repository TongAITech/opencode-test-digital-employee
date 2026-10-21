param(
  [string]$HermesTag = 'v2026.9.14',
  [string]$OutputDir = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $OutputDir) { $OutputDir = Join-Path $RepoRoot 'dist' }
New-Item -ItemType Directory -Force $OutputDir | Out-Null

$Work = Join-Path $env:RUNNER_TEMP ('hermes-desktop-bank-' + [guid]::NewGuid().ToString('N'))
$Payload = Join-Path $Work 'payload'
New-Item -ItemType Directory -Force (Join-Path $Payload 'hermes') | Out-Null

function Mount-R {
  $mapped = $null
  foreach ($line in (& subst 2>$null)) {
    if ($line -match '^R:\\:\s*=>\s*(.+)$') { $mapped = $Matches[1].Trim().TrimEnd('\'); break }
  }
  if ($mapped) { & subst R: /D | Out-Null }
  & subst R: $Payload | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'subst R failed' }
}

function HermesExe { return 'R:\hermes\bin\hermes.exe' }
function Assert-File([string]$Path) { if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "missing file: $Path" } }
function Assert-Dir([string]$Path) { if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "missing dir: $Path" } }

try {
  Mount-R

  $env:HERMES_HOME = 'R:\hermes'
  $env:PYTHONPATH = 'R:\hermes\hermes-agent'
  $env:PYTHONUTF8 = '1'
  $env:PYTHONIOENCODING = 'utf-8'
  $env:PLAYWRIGHT_BROWSERS_PATH = 'R:\hermes\browser\ms-playwright'
  $env:CUA_TELEMETRY = '0'
  $env:DO_NOT_TRACK = '1'

  Write-Host '=== 1. Official Hermes install: Desktop + base runtime + Computer Use bootstrap ===' -ForegroundColor Cyan
  $installer = Join-Path $Work 'install.ps1'
  Invoke-WebRequest "https://raw.githubusercontent.com/NousResearch/hermes-agent/$HermesTag/scripts/install.ps1" -OutFile $installer

  # Clone the release ref directly. This avoids main->tag checkout drift on hosted Windows.
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer `
      -HermesHome 'R:\hermes' `
      -InstallDir 'R:\hermes\hermes-agent' `
      -Branch $HermesTag `
      -NonInteractive `
      -IncludeDesktop
  if ($LASTEXITCODE -ne 0) { throw "Hermes installer failed: $LASTEXITCODE" }

  Assert-File (HermesExe)
  Assert-File 'R:\hermes\hermes-agent\hermes_cli\main.py'
  & (HermesExe) --version
  if ($LASTEXITCODE -ne 0) { throw 'hermes --version failed' }

  $desktop = Get-ChildItem 'R:\hermes\hermes-agent\apps\desktop\release' -Filter Hermes.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $desktop) { throw 'Hermes Desktop Hermes.exe missing after -IncludeDesktop' }
  Write-Host "[OK] Desktop: $($desktop.FullName)" -ForegroundColor Green

  Write-Host '=== 2. Add known-compatible portable Node for bank wkey + browser runtime ===' -ForegroundColor Cyan
  $nodeZip = Join-Path $Work 'node.zip'
  $nodeTmp = Join-Path $Work 'node-unpack'
  Invoke-WebRequest 'https://nodejs.org/dist/v20.11.1/node-v20.11.1-win-x64.zip' -OutFile $nodeZip
  Expand-Archive $nodeZip $nodeTmp -Force
  $nodeSrc = Get-ChildItem $nodeTmp -Directory | Select-Object -First 1
  if (-not $nodeSrc) { throw 'portable Node archive did not contain a directory' }
  if (Test-Path 'R:\hermes\node') { Remove-Item 'R:\hermes\node' -Recurse -Force }
  Copy-Item $nodeSrc.FullName 'R:\hermes\node' -Recurse -Force
  Assert-File 'R:\hermes\node\node.exe'
  Assert-File 'R:\hermes\node\npm.cmd'
  & 'R:\hermes\node\node.exe' --version
  if ($LASTEXITCODE -ne 0) { throw 'portable node failed' }

  $env:PATH = 'R:\hermes\node;R:\hermes\node\node_modules\.bin;' + $env:PATH

  Write-Host '=== 3. Make agent-browser + Chrome explicitly portable/offline ===' -ForegroundColor Cyan
  New-Item -ItemType Directory -Force 'R:\hermes\browser\agent-browser' | Out-Null

  # Hermes v0.21.3 resolves agent-browser lazily via npx. For a bank/offline package we install
  # the same supported range into the portable Node prefix so first use never needs npm/network.
  & 'R:\hermes\node\npm.cmd' install --global --prefix 'R:\hermes\node' --ignore-scripts --no-audit --no-fund 'agent-browser@^0.26.0'
  if ($LASTEXITCODE -ne 0) { throw 'portable agent-browser npm install failed' }

  $agentBrowser = 'R:\hermes\node\agent-browser.cmd'
  if (-not (Test-Path $agentBrowser)) {
    $hit = Get-ChildItem 'R:\hermes\node' -Filter 'agent-browser.cmd' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { $agentBrowser = $hit.FullName }
  }
  Assert-File $agentBrowser
  & $agentBrowser --version
  if ($LASTEXITCODE -ne 0) { throw 'agent-browser --version failed' }

  # agent-browser 0.26 installs Chrome under ~/.agent-browser/browsers rather than PLAYWRIGHT_BROWSERS_PATH.
  # Build online, then copy that exact browser tree into the portable payload and force Hermes to use it.
  & $agentBrowser install
  if ($LASTEXITCODE -ne 0) { throw 'agent-browser Chrome install failed' }

  $agentBrowserCache = Join-Path $env:USERPROFILE '.agent-browser\browsers'
  $chromeSource = Get-ChildItem $agentBrowserCache -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^chrome-' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if (-not $chromeSource) { throw "agent-browser installed Chrome but no chrome-* directory was found under $agentBrowserCache" }

  $portableChromeDir = Join-Path 'R:\hermes\browser\agent-browser' $chromeSource.Name
  if (Test-Path $portableChromeDir) { Remove-Item $portableChromeDir -Recurse -Force }
  Copy-Item -LiteralPath $chromeSource.FullName -Destination $portableChromeDir -Recurse -Force

  $portableChromeExe = Get-ChildItem $portableChromeDir -Filter chrome.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $portableChromeExe) { throw "portable Chrome copy does not contain chrome.exe: $portableChromeDir" }
  $env:AGENT_BROWSER_EXECUTABLE_PATH = $portableChromeExe.FullName
  Write-Host "[OK] Portable Chrome: $env:AGENT_BROWSER_EXECUTABLE_PATH" -ForegroundColor Green

  # Keep Hermes' supported bookkeeping hook, but no bank runtime may depend on it downloading anything.
  & (HermesExe) tools post-setup agent_browser
  if ($LASTEXITCODE -ne 0) { throw 'hermes tools post-setup agent_browser failed' }

  Write-Host '=== 4. Extract cua-driver into the portable payload and validate Hermes contract ===' -ForegroundColor Cyan
  $cuaCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Cua\cua-driver\bin\cua-driver.exe'),
    (Join-Path $env:USERPROFILE '.cua-driver\packages\current\cua-driver.exe'),
    (Join-Path $env:USERPROFILE '.local\bin\cua-driver.exe')
  )
  try { $cmd = (Get-Command cua-driver.exe -ErrorAction Stop).Source; if ($cmd) { $cuaCandidates = @($cmd) + $cuaCandidates } } catch {}

  $cuaSource = $cuaCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
  if (-not $cuaSource) {
    Write-Host '[INFO] cua-driver not found after installer bootstrap; retrying Hermes install hook once.' -ForegroundColor Yellow
    & (HermesExe) computer-use install
    $cuaSource = $cuaCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
  }
  if (-not $cuaSource) { throw 'cannot locate installed cua-driver.exe to make portable' }

  $cuaSourceDir = Split-Path $cuaSource -Parent
  if (Test-Path 'R:\hermes\cua-driver') { Remove-Item 'R:\hermes\cua-driver' -Recurse -Force }
  New-Item -ItemType Directory -Force 'R:\hermes\cua-driver\bin' | Out-Null
  Copy-Item -LiteralPath $cuaSource -Destination 'R:\hermes\cua-driver\bin\cua-driver.exe' -Force

  $uiaSource = Join-Path $cuaSourceDir 'cua-driver-uia.exe'
  if (Test-Path -LiteralPath $uiaSource -PathType Leaf) {
    Copy-Item -LiteralPath $uiaSource -Destination 'R:\hermes\cua-driver\bin\cua-driver-uia.exe' -Force
  }

  Assert-File 'R:\hermes\cua-driver\bin\cua-driver.exe'
  $env:HERMES_CUA_DRIVER_CMD = 'R:\hermes\cua-driver\bin\cua-driver.exe'

  $manifestText = (& $env:HERMES_CUA_DRIVER_CMD manifest 2>&1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) { throw "portable cua-driver manifest failed: $manifestText" }
  try { $manifest = $manifestText | ConvertFrom-Json } catch { throw "cua-driver manifest is not JSON: $manifestText" }
  if (-not $manifest.binary_version) { throw 'cua-driver manifest missing binary_version' }
  Write-Host "[OK] cua-driver $($manifest.binary_version)" -ForegroundColor Green

  & (HermesExe) computer-use status
  if ($LASTEXITCODE -ne 0) { throw 'portable cua-driver does not satisfy Hermes computer-use runtime contract' }

  Write-Host '=== 5. Install bank integration overlay ===' -ForegroundColor Cyan
  New-Item -ItemType Directory -Force 'R:\hermes\bank' | Out-Null
  Copy-Item (Join-Path $PSScriptRoot 'bank-model-gateway.mjs') 'R:\hermes\bank\bank-model-gateway.mjs' -Force
  Copy-Item (Join-Path $PSScriptRoot 'probe-wkey.cjs') 'R:\hermes\bank\probe-wkey.cjs' -Force
  Copy-Item (Join-Path $PSScriptRoot 'config.yaml') 'R:\hermes\bank\config-aicoder.yaml' -Force
  Copy-Item (Join-Path $PSScriptRoot 'config-bankgpt.yaml') 'R:\hermes\bank\config-bankgpt.yaml' -Force
  Copy-Item 'R:\hermes\bank\config-aicoder.yaml' 'R:\hermes\config.yaml' -Force

  & 'R:\hermes\node\node.exe' --check 'R:\hermes\bank\bank-model-gateway.mjs'
  if ($LASTEXITCODE -ne 0) { throw 'bank-model-gateway syntax check failed' }

  New-Item -ItemType Directory -Force 'R:\hermes\skills\test-digital-employee' | Out-Null
  Copy-Item (Join-Path $PSScriptRoot 'skills\test-digital-employee\SKILL.md') 'R:\hermes\skills\test-digital-employee\SKILL.md' -Force
  New-Item -ItemType Directory -Force 'R:\hermes\runtime-state\r1','R:\hermes\missions' | Out-Null

  Write-Host '=== 6. Assert Desktop/browser/CUA/test assets ===' -ForegroundColor Cyan
  Assert-File $desktop.FullName
  Assert-File $agentBrowser
  Assert-File $env:AGENT_BROWSER_EXECUTABLE_PATH
  Assert-File 'R:\hermes\cua-driver\bin\cua-driver.exe'
  Assert-File 'R:\hermes\skills\test-digital-employee\SKILL.md'

  Write-Host '=== 7. Package root launchers/workspace ===' -ForegroundColor Cyan
  Copy-Item (Join-Path $PSScriptRoot 'START-TEST-DIGITAL-EMPLOYEE.ps1') (Join-Path $Work 'START-TEST-DIGITAL-EMPLOYEE.ps1') -Force
  Copy-Item (Join-Path $PSScriptRoot 'VERIFY-ALL.ps1') (Join-Path $Work 'VERIFY-ALL.ps1') -Force

  @'
@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START-TEST-DIGITAL-EMPLOYEE.ps1" -Model aicoder-plus
'@ | Set-Content -Encoding ASCII (Join-Path $Work 'START-TEST-DIGITAL-EMPLOYEE.cmd')

  @'
@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START-TEST-DIGITAL-EMPLOYEE.ps1" -Model bankgpt
'@ | Set-Content -Encoding ASCII (Join-Path $Work 'START-BANKGPT-DIRECTOR.cmd')

  @'
@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0VERIFY-ALL.ps1"
pause
'@ | Set-Content -Encoding ASCII (Join-Path $Work 'VERIFY-ALL.cmd')

  @'
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p='%~dp0logs\bank-model-gateway.pid'; if(Test-Path $p){$id=[int](Get-Content $p -Raw); Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; Remove-Item $p -Force}; subst R: /D 2>$null"
'@ | Set-Content -Encoding ASCII (Join-Path $Work 'STOP-ALL.cmd')

  $workspace = Join-Path $Work 'workspace'
  New-Item -ItemType Directory -Force $workspace | Out-Null
  @'
# PFC / Bank Test Workspace

Use the `test-digital-employee` skill for all formal testing.
R1 event stream is sole runtime truth. Do not claim PASS without real execution + assertion + evidence.
DSH owns localhost:3080; never bind Hermes services to 3080. Bank model gateway uses 127.0.0.1:17891.
'@ | Set-Content -Encoding UTF8 (Join-Path $workspace '.hermes.md')
  New-Item -ItemType Directory -Force (Join-Path $workspace 'evidence'),(Join-Path $workspace 'defects'),(Join-Path $workspace 'reports') | Out-Null

  @"
Hermes Test Digital Employee Desktop Final
=========================================

1. 行内免安装、免构建：解压后先运行 VERIFY-ALL.cmd，再运行 START-TEST-DIGITAL-EMPLOYEE.cmd。
2. 保持行内 deepseek-harness\wizard-opencode-plugin 原目录不变。
3. 本包自带 Hermes Desktop、Python、Node、agent-browser、Chrome、cua-driver 和测试数字员工 Skill。
4. 行内不会执行 pip/npm/browser/cua 安装器；security.allow_lazy_installs=false。
5. BankGPT 已在 OpenCode 配置好时，可运行 START-BANKGPT-DIRECTOR.cmd；密钥不会写入本包。
6. DSH 3080 保留；Hermes Bank Model Gateway 使用 127.0.0.1:17891。
7. Computer Use 使用包内 cua-driver；CUA_TELEMETRY=0、DO_NOT_TRACK=1。
8. Browser 使用包内 Chrome，通过 AGENT_BROWSER_EXECUTABLE_PATH 固定，不依赖用户缓存或在线下载。
9. 网页测试优先 DOM/browser；Computer Use 用于桌面客户端、系统弹窗、文件选择框等补充场景。
10. 模型限制：10分钟100请求；本包安全阈值90。09-18 40,000,000 tokens；18-21 独立40,000,000；21-09额度不限。

外部构建只能证明包结构/依赖/桌面/CUA contract/browser资产完整。
CAS、wkey、BankGPT、PFC 业务执行必须由 VERIFY-ALL.cmd 和真实 Agent Loop 在行内验收，禁止伪报 PASS。
"@ | Set-Content -Encoding UTF8 (Join-Path $Work 'README-行内直接使用.txt')

  Write-Host '=== 8. External relocation/runtime smoke ===' -ForegroundColor Cyan
  & (HermesExe) config check | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'Hermes config check failed' }

  & $agentBrowser --version | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'portable agent-browser smoke failed' }
  if (-not (Test-Path -LiteralPath $env:AGENT_BROWSER_EXECUTABLE_PATH -PathType Leaf)) { throw 'portable Chrome executable smoke failed' }

  & 'R:\hermes\cua-driver\bin\cua-driver.exe' manifest | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'portable cua-driver manifest smoke failed' }

  & (HermesExe) computer-use status | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'portable computer-use status smoke failed' }

  & 'R:\hermes\node\node.exe' --check 'R:\hermes\bank\bank-model-gateway.mjs'
  if ($LASTEXITCODE -ne 0) { throw 'gateway syntax smoke failed' }

  Write-Host '=== 9. Create final ZIP ===' -ForegroundColor Cyan
  $final = Join-Path $OutputDir 'Hermes-Test-Digital-Employee-Desktop-Final-Win10-x64.zip'
  if (Test-Path $final) { Remove-Item $final -Force }
  Push-Location $Work
  try {
    & 7z a -tzip -mx=5 $final '.\*'
    if ($LASTEXITCODE -ne 0) { throw '7z create failed' }
  } finally { Pop-Location }

  & 7z t $final
  if ($LASTEXITCODE -ne 0) { throw '7z integrity test failed' }

  $sha = (Get-FileHash $final -Algorithm SHA256).Hash.ToUpperInvariant()
  "$sha  $(Split-Path $final -Leaf)" | Set-Content -Encoding ASCII ($final + '.sha256.txt')
  Write-Host "FINAL=$final" -ForegroundColor Green
  Write-Host "SHA256=$sha" -ForegroundColor Green
}
finally {
  try { & subst R: /D | Out-Null } catch {}
}