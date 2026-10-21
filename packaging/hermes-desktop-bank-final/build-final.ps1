param(
  [string]$HermesTag = 'v2026.9.14',
  [string]$OutputDir = ''
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$RepoRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if(-not $OutputDir){$OutputDir=Join-Path $RepoRoot 'dist'}
New-Item -ItemType Directory -Force $OutputDir|Out-Null
$Work=Join-Path $env:RUNNER_TEMP ('hermes-desktop-bank-'+[guid]::NewGuid().ToString('N'))
$Payload=Join-Path $Work 'payload'
New-Item -ItemType Directory -Force (Join-Path $Payload 'hermes')|Out-Null

function Mount-R {
  $mapped=$null;foreach($line in (& subst 2>$null)){if($line -match '^R:\\:\s*=>\s*(.+)$'){$mapped=$Matches[1].Trim().TrimEnd('\\');break}}
  if($mapped){& subst R: /D|Out-Null}
  & subst R: $Payload|Out-Null
  if($LASTEXITCODE -ne 0){throw 'subst R failed'}
}
function HermesExe { return 'R:\hermes\bin\hermes.exe' }
function Assert-File([string]$P){if(-not(Test-Path $P)){throw "missing: $P"}}

try {
  Mount-R
  $env:HERMES_HOME='R:\hermes'
  $env:PYTHONPATH='R:\hermes\hermes-agent'
  $env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'

  Write-Host '=== 1. Official Hermes install: Desktop + Browser + Computer Use ===' -ForegroundColor Cyan
  $installer=Join-Path $Work 'install.ps1'
  Invoke-WebRequest "https://raw.githubusercontent.com/NousResearch/hermes-agent/$HermesTag/scripts/install.ps1" -OutFile $installer
  # Clone the release ref directly. Using -Tag makes the upstream installer clone main first,
  # run source-completion mutations, then checkout the tag; on hosted Windows that can leave
  # generated website files dirty and block checkout. `git clone -b <tag>` is immutable enough
  # for this one-shot package build and avoids that drift window entirely.
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -HermesHome 'R:\hermes' -InstallDir 'R:\hermes\hermes-agent' -Branch $HermesTag -NonInteractive -IncludeDesktop
  if($LASTEXITCODE -ne 0){throw "Hermes installer failed: $LASTEXITCODE"}
  Assert-File (HermesExe)
  Assert-File 'R:\hermes\hermes-agent\hermes_cli\main.py'
  & (HermesExe) --version
  if($LASTEXITCODE -ne 0){throw 'hermes --version failed'}

  Write-Host '=== 2. Ensure Browser and Computer Use packages ===' -ForegroundColor Cyan
  & (HermesExe) pm install agent-browser
  if($LASTEXITCODE -ne 0){throw 'hermes pm install agent-browser failed'}
  & (HermesExe) computer-use install
  if($LASTEXITCODE -ne 0){throw 'hermes computer-use install failed'}
  & (HermesExe) computer-use status
  if($LASTEXITCODE -ne 0){throw 'computer-use status failed on build host'}

  Write-Host '=== 3. Make cua-driver explicitly portable ===' -ForegroundColor Cyan
  $py=Get-ChildItem 'R:\hermes' -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue | Where-Object {$_.FullName -notmatch 'node_modules'} | Select-Object -First 1
  if(-not$py){throw 'Hermes private Python not found'}
  $cuaPath=(& $py.FullName -c "import sys;sys.path.insert(0,r'R:\hermes\hermes-agent');from tools.computer_use.cua_backend_driver import resolve_cua_driver_cmd;print(resolve_cua_driver_cmd() or '')" 2>$null|Out-String).Trim()
  if(-not$cuaPath -or -not(Test-Path $cuaPath)){throw "Cannot resolve installed cua-driver: $cuaPath"}
  $cuaBinDir=Split-Path $cuaPath -Parent
  $cuaRoot=Split-Path $cuaBinDir -Parent
  if(Test-Path 'R:\hermes\cua-driver'){Remove-Item 'R:\hermes\cua-driver' -Recurse -Force}
  Copy-Item $cuaRoot 'R:\hermes\cua-driver' -Recurse -Force
  Assert-File 'R:\hermes\cua-driver\bin\cua-driver.exe'
  $env:HERMES_CUA_DRIVER_CMD='R:\hermes\cua-driver\bin\cua-driver.exe'
  $manifest=& $env:HERMES_CUA_DRIVER_CMD manifest 2>&1
  if($LASTEXITCODE -ne 0 -or -not($manifest -match 'binary_version')){throw 'portable cua-driver manifest failed'}

  Write-Host '=== 4. Add known-compatible portable Node for bank wkey bridge ===' -ForegroundColor Cyan
  $nodeZip=Join-Path $Work 'node.zip';$nodeTmp=Join-Path $Work 'node-unpack'
  Invoke-WebRequest 'https://nodejs.org/dist/v20.11.1/node-v20.11.1-win-x64.zip' -OutFile $nodeZip
  Expand-Archive $nodeZip $nodeTmp -Force
  $nodeSrc=Get-ChildItem $nodeTmp -Directory|Select-Object -First 1
  if(Test-Path 'R:\hermes\node'){Remove-Item 'R:\hermes\node' -Recurse -Force}
  Copy-Item $nodeSrc.FullName 'R:\hermes\node' -Recurse -Force
  Assert-File 'R:\hermes\node\node.exe'
  & 'R:\hermes\node\node.exe' --version

  Write-Host '=== 5. Install bank integration overlay ===' -ForegroundColor Cyan
  New-Item -ItemType Directory -Force 'R:\hermes\bank'|Out-Null
  Copy-Item (Join-Path $PSScriptRoot 'bank-model-gateway.mjs') 'R:\hermes\bank\bank-model-gateway.mjs' -Force
  Copy-Item (Join-Path $PSScriptRoot 'probe-wkey.cjs') 'R:\hermes\bank\probe-wkey.cjs' -Force
  Copy-Item (Join-Path $PSScriptRoot 'config.yaml') 'R:\hermes\bank\config-aicoder.yaml' -Force
  Copy-Item (Join-Path $PSScriptRoot 'config-bankgpt.yaml') 'R:\hermes\bank\config-bankgpt.yaml' -Force
  Copy-Item 'R:\hermes\bank\config-aicoder.yaml' 'R:\hermes\config.yaml' -Force
  & 'R:\hermes\node\node.exe' --check 'R:\hermes\bank\bank-model-gateway.mjs'
  if($LASTEXITCODE -ne 0){throw 'bank-model-gateway syntax check failed'}

  New-Item -ItemType Directory -Force 'R:\hermes\skills\test-digital-employee'|Out-Null
  Copy-Item (Join-Path $PSScriptRoot 'skills\test-digital-employee\SKILL.md') 'R:\hermes\skills\test-digital-employee\SKILL.md' -Force
  New-Item -ItemType Directory -Force 'R:\hermes\runtime-state\r1','R:\hermes\missions'|Out-Null

  Write-Host '=== 6. Assert Desktop binary and tool assets ===' -ForegroundColor Cyan
  $desktop=Get-ChildItem 'R:\hermes\hermes-agent\apps\desktop\release' -Filter Hermes.exe -File -Recurse -ErrorAction SilentlyContinue|Select-Object -First 1
  if(-not$desktop){throw 'Hermes Desktop Hermes.exe missing after -IncludeDesktop'}
  $browserHits=Get-ChildItem 'R:\hermes' -Recurse -ErrorAction SilentlyContinue|Where-Object{$_.Name -match 'agent-browser|chromium|chrome.exe'}|Select-Object -First 3
  if(@($browserHits).Count -lt 2){throw 'Browser/Chromium portable assets not found'}

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

  $workspace=Join-Path $Work 'workspace';New-Item -ItemType Directory -Force $workspace|Out-Null
  @'
# PFC / Bank Test Workspace

Use the `test-digital-employee` skill for all formal testing.
R1 event stream is sole runtime truth. Do not claim PASS without real execution + assertion + evidence.
DSH owns localhost:3080; never bind Hermes services to 3080. Bank model gateway uses 127.0.0.1:17891.
'@ | Set-Content -Encoding UTF8 (Join-Path $workspace '.hermes.md')
  New-Item -ItemType Directory -Force (Join-Path $workspace 'evidence'),(Join-Path $workspace 'defects'),(Join-Path $workspace 'reports')|Out-Null

  @"
Hermes Test Digital Employee Desktop Final
=========================================

1. 不需要安装、不需要构建。
2. 保持行内 deepseek-harness\wizard-opencode-plugin 原目录不变。
3. 首次运行 VERIFY-ALL.cmd；会打开 fresh CAS 并真实验证 aicoder-plus。
4. 日常运行 START-TEST-DIGITAL-EMPLOYEE.cmd。
5. BankGPT 已在 OpenCode 配置好时，可运行 START-BANKGPT-DIRECTOR.cmd；密钥不会写入本包。
6. DSH 3080 保留；Hermes Bank Model Gateway 使用 127.0.0.1:17891。
7. Computer Use 已包含 cua-driver；网页优先 browser，文本模型桌面控制优先 Accessibility/AX 模式。
8. 模型限制：10分钟100请求；本包安全阈值90。09-18 40,000,000 tokens；18-21 独立40,000,000；21-09额度不限。

外部构建只能证明包结构/依赖/桌面/cua/browser完整。CAS、wkey、BankGPT、业务系统必须由 VERIFY-ALL.cmd 在行内真实验收，禁止外部伪报 PASS。
"@ | Set-Content -Encoding UTF8 (Join-Path $Work 'README-行内直接使用.txt')

  Write-Host '=== 8. External relocation smoke ===' -ForegroundColor Cyan
  & (HermesExe) config check|Out-Host
  if($LASTEXITCODE -ne 0){throw 'Hermes config check failed'}
  & 'R:\hermes\cua-driver\bin\cua-driver.exe' manifest|Out-Null
  if($LASTEXITCODE -ne 0){throw 'cua portable manifest failed'}
  & 'R:\hermes\node\node.exe' --check 'R:\hermes\bank\bank-model-gateway.mjs'
  if($LASTEXITCODE -ne 0){throw 'gateway syntax failed'}

  Write-Host '=== 9. Create final ZIP ===' -ForegroundColor Cyan
  $final=Join-Path $OutputDir 'Hermes-Test-Digital-Employee-Desktop-Final-Win10-x64.zip'
  if(Test-Path $final){Remove-Item $final -Force}
  Push-Location $Work
  try { & 7z a -tzip -mx=5 $final '.\*'; if($LASTEXITCODE -ne 0){throw '7z create failed'} } finally { Pop-Location }
  & 7z t $final
  if($LASTEXITCODE -ne 0){throw '7z integrity test failed'}
  $sha=(Get-FileHash $final -Algorithm SHA256).Hash.ToUpperInvariant()
  "$sha  $(Split-Path $final -Leaf)"|Set-Content -Encoding ASCII ($final+'.sha256.txt')
  Write-Host "FINAL=$final" -ForegroundColor Green
  Write-Host "SHA256=$sha" -ForegroundColor Green
} finally {
  try { & subst R: /D|Out-Null } catch {}
}
