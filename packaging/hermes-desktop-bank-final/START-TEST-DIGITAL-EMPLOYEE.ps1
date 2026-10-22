param(
  [ValidateSet('aicoder-plus','bankgpt')][string]$Model = 'aicoder-plus',
  [switch]$SkipFreshCas
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload = [IO.Path]::GetFullPath((Join-Path $Root 'payload')).TrimEnd('\')

function Mount-PortableRoot {
  $mapped = $null
  foreach ($line in (& subst 2>$null)) {
    if ($line -match '^R:\\:\s*=>\s*(.+)$') {
      $mapped = $Matches[1].Trim().TrimEnd('\')
      break
    }
  }
  if ($mapped -and -not $mapped.Equals($Payload,[StringComparison]::OrdinalIgnoreCase)) {
    throw "R: is already mapped to $mapped. Release R: before starting Hermes."
  }
  if (-not $mapped) {
    & subst R: $Payload | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the R: portable mapping.' }
  }
}

function Find-WizardPlugin {
  $candidates = @()
  if ($env:WIZARD_PLUGIN_DIR) { $candidates += $env:WIZARD_PLUGIN_DIR }
  $candidates += @(
    'D:\deepseek-harness\wizard-opencode-plugin',
    'C:\deepseek-harness\wizard-opencode-plugin',
    'E:\deepseek-harness\wizard-opencode-plugin'
  )
  foreach ($d in Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue) {
    $candidates += (Join-Path ($d.Name + ':\') 'deepseek-harness\wizard-opencode-plugin')
  }
  foreach ($p in $candidates | Select-Object -Unique) {
    if ($p -and (Test-Path (Join-Path $p 'lib\login.js')) -and (Test-Path (Join-Path $p 'wkey.x86_64-pc-windows-msvc.node'))) {
      return [IO.Path]::GetFullPath($p)
    }
  }
  throw 'wizard-opencode-plugin was not found. Set WIZARD_PLUGIN_DIR to the DSH plugin directory.'
}

function Find-CompatibleNode([string]$Plugin) {
  $addon = Join-Path $Plugin 'wkey.x86_64-pc-windows-msvc.node'
  $login = Join-Path $Plugin 'lib\login.js'
  $probe = 'R:\hermes\bank\probe-wkey.cjs'
  $candidates = @()
  if ($env:WIZARD_NODE_EXE) { $candidates += $env:WIZARD_NODE_EXE }
  $candidates += @(
    'R:\hermes\node\node.exe',
    'D:\deepseek-harness\node\node.exe',
    'D:\deepseek-harness\runtime\node.exe'
  )
  try { $candidates += (Get-Command node.exe -ErrorAction Stop).Source } catch {}
  foreach ($n in $candidates | Select-Object -Unique) {
    if (-not $n -or -not (Test-Path $n)) { continue }
    try {
      $out = (& $n $probe $addon $login 2>$null | Out-String).Trim()
      if ($LASTEXITCODE -eq 0 -and $out -match 'WKEY_NODE_COMPATIBLE') { return [IO.Path]::GetFullPath($n) }
    } catch {}
  }
  throw 'No Node runtime can load wkey, login.js, and fetch. Set WIZARD_NODE_EXE to a compatible Node executable.'
}

function Import-BankGptFromOpenCode {
  $paths = @(
    (Join-Path $env:USERPROFILE '.config\opencode\opencode.json'),
    (Join-Path $env:USERPROFILE '.config\opencode\config.json')
  )
  foreach ($p in $paths) {
    if (-not (Test-Path $p)) { continue }
    try {
      $cfg = Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
      $provider = $cfg.provider.'wizard-bankgpt'
      if (-not $provider) { continue }
      $base = [string]$provider.options.baseURL
      $key = [string]$provider.options.apiKey
      if ($base) { $env:BANKGPT_BASE_URL = $base }
      if ($key) { $env:BANKGPT_API_KEY = $key }
      if ($provider.models.'wizard-bankgpt') { $env:BANKGPT_MODEL = 'wizard-bankgpt' }
      return $true
    } catch {}
  }
  return $false
}

function Find-DesktopExe {
  $preferred = @(
    'R:\hermes\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe',
    'R:\hermes\hermes-agent\apps\desktop\release\win-ia32-unpacked\Hermes.exe'
  )
  foreach ($p in $preferred) {
    if (Test-Path $p) { return $p }
  }
  $release = 'R:\hermes\hermes-agent\apps\desktop\release'
  if (Test-Path $release) {
    $hit = Get-ChildItem -Path $release -Filter Hermes.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  throw 'Hermes Desktop Hermes.exe was not found in the portable package.'
}

function Find-PortableChrome {
  $root = 'R:\hermes\browser\agent-browser'
  if (-not (Test-Path $root)) { throw 'Portable browser directory is missing.' }
  $hit = Get-ChildItem $root -Filter chrome.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $hit) { throw 'Portable Chrome is missing.' }
  return $hit.FullName
}

Mount-PortableRoot
$env:HERMES_HOME = 'R:\hermes'
$env:PYTHONPATH = 'R:\hermes\hermes-agent'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PATH = 'R:\hermes\node;R:\hermes\node\node_modules\.bin;' + $env:PATH
$env:NPM_CONFIG_OFFLINE = 'true'
$env:CUA_TELEMETRY = '0'
$env:DO_NOT_TRACK = '1'
$env:BANK_TZ_OFFSET_MINUTES = '480'
$env:BANK_MODEL_REQUEST_LIMIT_10MIN = '100'
$env:BANK_MODEL_REQUEST_SAFETY_LIMIT_10MIN = '90'
$env:BANK_MODEL_QUOTA_09_18 = '40000000'
$env:BANK_MODEL_QUOTA_18_21 = '40000000'
$env:WIZARD_UPSTREAM_BASE_URL = 'https://wizard-ai.paic.com.cn/code_pilot/api/v1'
$env:WIZARD_MODEL = 'aicoder-plus'

if (-not (Test-Path 'R:\hermes\node\agent-browser.cmd')) { throw 'Portable agent-browser is missing.' }
$env:AGENT_BROWSER_EXECUTABLE_PATH = Find-PortableChrome

$cua = 'R:\hermes\cua-driver\bin\cua-driver.exe'
if (-not (Test-Path $cua)) { throw 'Portable cua-driver is missing.' }
$env:HERMES_CUA_DRIVER_CMD = $cua

$plugin = Find-WizardPlugin
$env:WIZARD_PLUGIN_DIR = $plugin
$node = Find-CompatibleNode $plugin
$bankgpt = Import-BankGptFromOpenCode

$configTemplate = if ($Model -eq 'bankgpt') { 'R:\hermes\bank\config-bankgpt.yaml' } else { 'R:\hermes\bank\config-aicoder.yaml' }
if ($Model -eq 'bankgpt' -and -not $bankgpt) {
  throw 'BankGPT was selected, but wizard-bankgpt baseURL/apiKey was not found in the OpenCode configuration.'
}
Copy-Item -LiteralPath $configTemplate -Destination 'R:\hermes\config.yaml' -Force

$logs = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$outLog = Join-Path $logs 'bank-model-gateway.out.log'
$errLog = Join-Path $logs 'bank-model-gateway.err.log'
Remove-Item $outLog,$errLog -Force -ErrorAction SilentlyContinue
$gateway = Start-Process -FilePath $node -ArgumentList @('R:\hermes\bank\bank-model-gateway.mjs') -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Set-Content -LiteralPath (Join-Path $logs 'bank-model-gateway.pid') -Value $gateway.Id -Encoding ASCII

try {
  for ($i=0; $i -lt 120; $i++) {
    if ($gateway.HasExited) { throw "Bank model gateway exited early. Check $errLog" }
    try {
      $h = Invoke-RestMethod 'http://127.0.0.1:17891/health' -TimeoutSec 2
      if ($h.status -eq 'UP') { break }
    } catch {}
    Start-Sleep -Milliseconds 250
  }

  if (-not $SkipFreshCas -and $Model -eq 'aicoder-plus') {
    Write-Host 'Opening a fresh Wizard CAS login...' -ForegroundColor Yellow
    $a = Invoke-RestMethod 'http://127.0.0.1:17891/auth/login' -Method Post -TimeoutSec 1800
    if ($a.cas -ne 'READY' -or $a.apiKey -ne 'READY') { throw 'Wizard CAS did not reach READY.' }
  }

  $budget = Invoke-RestMethod 'http://127.0.0.1:17891/budget/status' -TimeoutSec 3
  Write-Host ("Model budget: requests {0}/{1} in 10 min; window {2}; remaining tokens {3}" -f $budget.requests_last_10min,$budget.safety_limit_10min,$budget.quota_window,$budget.quota_remaining_tokens) -ForegroundColor Cyan
  Write-Host "Wizard plugin: $plugin" -ForegroundColor DarkGray
  Write-Host "Node: $node" -ForegroundColor DarkGray
  Write-Host 'agent-browser: R:\hermes\node\agent-browser.cmd' -ForegroundColor DarkGray
  Write-Host "Chrome: $env:AGENT_BROWSER_EXECUTABLE_PATH" -ForegroundColor DarkGray
  Write-Host "Computer Use driver: $env:HERMES_CUA_DRIVER_CMD" -ForegroundColor DarkGray

  $desktop = Find-DesktopExe
  $workspace = Join-Path $Root 'workspace'
  New-Item -ItemType Directory -Force -Path $workspace | Out-Null
  Push-Location $workspace
  try {
    Write-Host "Starting Hermes Desktop: $desktop" -ForegroundColor Green
    $p = Start-Process -FilePath $desktop -PassThru -WorkingDirectory $workspace
    $p.WaitForExit()
  } finally {
    Pop-Location
  }
}
finally {
  try {
    if ($gateway -and -not $gateway.HasExited) {
      Stop-Process -Id $gateway.Id -Force -ErrorAction SilentlyContinue
    }
  } catch {}
  Remove-Item (Join-Path $logs 'bank-model-gateway.pid') -Force -ErrorAction SilentlyContinue
}
