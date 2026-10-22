$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload = [IO.Path]::GetFullPath((Join-Path $Root 'payload')).TrimEnd('\')
$results = [ordered]@{}

function Step([string]$Name,[scriptblock]$Body) {
  try {
    & $Body
    $results[$Name] = 'PASS'
    Write-Host "[PASS] $Name" -ForegroundColor Green
  } catch {
    $results[$Name] = 'FAIL'
    Write-Host "[FAIL] $Name :: $($_.Exception.Message)" -ForegroundColor Red
    throw
  }
}

function Mount-Root {
  $mapped = $null
  foreach($line in (& subst 2>$null)) {
    if($line -match '^R:\\:\s*=>\s*(.+)$') {
      $mapped = $Matches[1].Trim().TrimEnd('\')
      break
    }
  }
  if($mapped -and -not $mapped.Equals($Payload,[StringComparison]::OrdinalIgnoreCase)) {
    throw "R: occupied by $mapped"
  }
  if(-not $mapped) {
    & subst R: $Payload | Out-Null
    if($LASTEXITCODE -ne 0) { throw 'subst R failed' }
  }
}

function Find-Plugin {
  $c = @()
  if($env:WIZARD_PLUGIN_DIR) { $c += $env:WIZARD_PLUGIN_DIR }
  $c += @(
    'D:\deepseek-harness\wizard-opencode-plugin',
    'C:\deepseek-harness\wizard-opencode-plugin',
    'E:\deepseek-harness\wizard-opencode-plugin'
  )
  foreach($d in Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue) {
    $c += (Join-Path ($d.Name + ':\') 'deepseek-harness\wizard-opencode-plugin')
  }
  foreach($p in $c | Select-Object -Unique) {
    if($p -and (Test-Path (Join-Path $p 'lib\login.js')) -and (Test-Path (Join-Path $p 'wkey.x86_64-pc-windows-msvc.node'))) {
      return [IO.Path]::GetFullPath($p)
    }
  }
  throw 'wizard-opencode-plugin not found'
}

function Import-BankGpt {
  $paths = @(
    (Join-Path $env:USERPROFILE '.config\opencode\opencode.json'),
    (Join-Path $env:USERPROFILE '.config\opencode\config.json')
  )
  foreach($p in $paths) {
    if(-not(Test-Path $p)) { continue }
    try {
      $cfg = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json
      $x = $cfg.provider.'wizard-bankgpt'.options
      if($x.baseURL) { $env:BANKGPT_BASE_URL = [string]$x.baseURL }
      if($x.apiKey) { $env:BANKGPT_API_KEY = [string]$x.apiKey }
      if($env:BANKGPT_BASE_URL -and $env:BANKGPT_API_KEY) { return $true }
    } catch {}
  }
  return $false
}

function Find-PortableChrome {
  $root = 'R:\hermes\browser\agent-browser'
  if(-not(Test-Path $root)) { throw 'portable browser root missing' }
  $hit = Get-ChildItem $root -Filter chrome.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if(-not $hit) { throw 'portable chrome.exe missing' }
  return $hit.FullName
}

Mount-Root
$env:HERMES_HOME = 'R:\hermes'
$env:PYTHONPATH = 'R:\hermes\hermes-agent'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:BANK_TZ_OFFSET_MINUTES = '480'
$env:BANK_MODEL_REQUEST_LIMIT_10MIN = '100'
$env:BANK_MODEL_REQUEST_SAFETY_LIMIT_10MIN = '90'
$env:BANK_MODEL_QUOTA_09_18 = '40000000'
$env:BANK_MODEL_QUOTA_18_21 = '40000000'
$env:WIZARD_UPSTREAM_BASE_URL = 'https://wizard-ai.paic.com.cn/code_pilot/api/v1'
$env:WIZARD_MODEL = 'aicoder-plus'
$env:NPM_CONFIG_OFFLINE = 'true'
$env:CUA_TELEMETRY = '0'
$env:DO_NOT_TRACK = '1'
$env:PATH = 'R:\hermes\node;R:\hermes\node\node_modules\.bin;' + $env:PATH

if(Test-Path 'R:\hermes\cua-driver\bin\cua-driver.exe') {
  $env:HERMES_CUA_DRIVER_CMD = 'R:\hermes\cua-driver\bin\cua-driver.exe'
}
$env:AGENT_BROWSER_EXECUTABLE_PATH = Find-PortableChrome

Step 'P01_HERMES_CLI' {
  $v = & 'R:\hermes\bin\hermes.exe' --version 2>&1
  if($LASTEXITCODE -ne 0 -or -not($v -match 'Hermes')) { throw "hermes --version failed: $v" }
}

Step 'P02_DESKTOP' {
  $d = Get-ChildItem 'R:\hermes\hermes-agent\apps\desktop\release' -Filter Hermes.exe -File -Recurse -ErrorAction Stop | Select-Object -First 1
  if(-not $d) { throw 'Hermes.exe missing' }
}

Step 'P03_CONFIG' {
  & 'R:\hermes\bin\hermes.exe' config check | Out-Host
  if($LASTEXITCODE -ne 0) { throw 'config check failed' }
}

Step 'P04_CUA_DRIVER' {
  if(-not $env:HERMES_CUA_DRIVER_CMD -or -not(Test-Path $env:HERMES_CUA_DRIVER_CMD)) { throw 'portable cua-driver missing' }
  $m = & $env:HERMES_CUA_DRIVER_CMD manifest 2>&1
  if($LASTEXITCODE -ne 0 -or -not($m -match 'binary_version')) { throw "cua manifest failed: $m" }
}

Step 'P05_COMPUTER_USE_STATUS' {
  & 'R:\hermes\bin\hermes.exe' computer-use status | Out-Host
  if($LASTEXITCODE -ne 0) { throw 'computer-use status failed' }
}

Step 'P06_BROWSER_ASSETS' {
  $ab = 'R:\hermes\node\agent-browser.cmd'
  if(-not(Test-Path $ab)) { throw 'agent-browser missing' }
  if(-not(Test-Path $env:AGENT_BROWSER_EXECUTABLE_PATH)) { throw 'bundled chrome missing' }
  $v = & $ab --version 2>&1
  if($LASTEXITCODE -ne 0 -or -not($v -match 'agent-browser')) { throw "agent-browser failed: $v" }
  Write-Host "Browser executable: $env:AGENT_BROWSER_EXECUTABLE_PATH"
}

Step 'P07_TEST_SKILL' {
  if(-not(Test-Path 'R:\hermes\skills\test-digital-employee\SKILL.md')) { throw 'test digital employee skill missing' }
}

Step 'P08_GATEWAY_SYNTAX' {
  $node = 'R:\hermes\node\node.exe'
  if(-not(Test-Path $node)) { throw 'portable node missing' }
  & $node --check 'R:\hermes\bank\bank-model-gateway.mjs' | Out-Null
  if($LASTEXITCODE -ne 0) { throw 'gateway syntax invalid' }
}

$plugin = Find-Plugin
$env:WIZARD_PLUGIN_DIR = $plugin
$node = 'R:\hermes\node\node.exe'
$addon = Join-Path $plugin 'wkey.x86_64-pc-windows-msvc.node'
$login = Join-Path $plugin 'lib\login.js'

Step 'P09_WKEY_NODE' {
  $o = & $node 'R:\hermes\bank\probe-wkey.cjs' $addon $login 2>&1
  if($LASTEXITCODE -ne 0 -or -not($o -match 'WKEY_NODE_COMPATIBLE')) { throw "wkey probe failed: $o" }
}

$bankgpt = Import-BankGpt
$logs = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$gw = Start-Process $node -ArgumentList @('R:\hermes\bank\bank-model-gateway.mjs') -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'verify-gateway.out.log') -RedirectStandardError (Join-Path $logs 'verify-gateway.err.log')

try {
  Step 'P10_GATEWAY_HEALTH' {
    for($i=0; $i -lt 100; $i++) {
      if($gw.HasExited) { throw 'gateway exited' }
      try {
        $h = Invoke-RestMethod 'http://127.0.0.1:17891/health' -TimeoutSec 2
        if($h.status -eq 'UP') { return }
      } catch {}
      Start-Sleep -Milliseconds 200
    }
    throw 'gateway health timeout'
  }

  Step 'P11_FRESH_CAS' {
    $a = Invoke-RestMethod 'http://127.0.0.1:17891/auth/login' -Method Post -TimeoutSec 1800
    if($a.cas -ne 'READY' -or $a.apiKey -ne 'READY') { throw 'CAS not ready' }
  }

  Step 'P12_AICODER_MODEL' {
    $b = @{
      model = 'aicoder-plus'
      messages = @(@{role='user';content='Reply exactly: AICODER_MODEL_OK'})
      stream = $false
      max_tokens = 64
    } | ConvertTo-Json -Depth 8
    $r = Invoke-RestMethod 'http://127.0.0.1:17891/wizard/v1/chat/completions' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($b)) -TimeoutSec 300
    $t = [string]$r.choices[0].message.content
    if($t -notmatch 'AICODER_MODEL_OK') { throw "unexpected: $t" }
  }

  if($bankgpt) {
    Step 'P13_BANKGPT_MODEL' {
      $b = @{
        model = 'wizard-bankgpt'
        messages = @(@{role='user';content='Reply exactly: BANKGPT_MODEL_OK'})
        stream = $false
        max_tokens = 64
      } | ConvertTo-Json -Depth 8
      $r = Invoke-RestMethod 'http://127.0.0.1:17891/bankgpt/v1/chat/completions' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($b)) -TimeoutSec 300
      $t = [string]$r.choices[0].message.content
      if($t -notmatch 'BANKGPT_MODEL_OK') { throw "unexpected: $t" }
    }
  } else {
    $results['P13_BANKGPT_MODEL'] = 'BLOCKED_CONFIG'
    Write-Host '[BLOCKED] P13_BANKGPT_MODEL: OpenCode BankGPT config not found' -ForegroundColor Yellow
  }

  Step 'P14_BUDGET_POLICY' {
    $q = Invoke-RestMethod 'http://127.0.0.1:17891/budget/status'
    if($q.request_limit_10min -ne 100 -or $q.safety_limit_10min -ne 90) { throw 'rate policy mismatch' }
    if($q.quota_window -ne '21:00-09:00' -and $q.quota_limit_tokens -ne 40000000) { throw 'quota policy mismatch' }
  }
} finally {
  try {
    if($gw -and -not $gw.HasExited) { Stop-Process -Id $gw.Id -Force }
  } catch {}
}

$results['P15_AGENT_TOOL_LOOP'] = 'MANUAL_NEXT'
$results['P16_DELEGATION'] = 'MANUAL_NEXT'
$results['P17_BROWSER_E2E'] = 'MANUAL_NEXT'
$results['P18_COMPUTER_USE_AX'] = 'MANUAL_NEXT'
$results['P19_TEST_FULL_CHAIN'] = 'MANUAL_NEXT'

$out = [ordered]@{
  timestamp = (Get-Date).ToString('o')
  results = $results
  bank_real_e2e = ($results.Values -notcontains 'FAIL')
  next = 'Run TEST_CAPABILITY_AUDIT in Hermes Desktop for P15-P19'
}

New-Item -ItemType Directory -Force (Join-Path $Root 'evidence') | Out-Null
$out | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $Root 'evidence\verify-all.json')
Write-Host ''
Write-Host 'Base runtime and model verification completed. P15-P19 require real execution inside the Hermes Agent Loop.' -ForegroundColor Cyan
$out.results.GetEnumerator() | Format-Table -AutoSize
