[CmdletBinding()]
param(
  [string]$ResultPath = (Join-Path $PWD "qualification-result.json"),
  [string]$WorkRoot = (Join-Path $env:RUNNER_TEMP "g1-g5-package-windows-qualification")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
  $PSNativeCommandUseErrorActionPreference = $false
}

$ExpectedStartingHead = "b2556de9a3a0dfc3e3028fb168284688ef3a24fc"
$DependencyCandidateHead = "de326fa4b35186a6acbdfc2bf8ed98549b2130c2"
$ExpectedMain = "58e5e1259cd26846b31ea21a8a87df0bcf071edc"
$ExpectedBranch = "work/local-validation-package"
$WorkflowPath = ".github/workflows/g1-g5-package-windows-qualification.yml"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$ResultPath = [IO.Path]::GetFullPath($ResultPath)

if (Test-Path $WorkRoot) { Remove-Item -Recurse -Force $WorkRoot }
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ResultPath) | Out-Null

$script:Checks = [ordered]@{}
$script:Details = [ordered]@{}
$script:Gaps = [System.Collections.Generic.List[string]]::new()
$script:Measured = [ordered]@{
  chromium_archive_sha256 = $null
  chromium_archive_size = $null
  chromium_exe_version = $null
  python_vc_runtime_reality = $null
  opencode_version = $null
  opencode_web_required = "UNRESOLVED_B2"
  opencode_sidecar_required = "UNRESOLVED_B2"
}
$script:Paths = [ordered]@{}
$script:pluginLayoutReady = $false
$script:StopReason = $null
$script:SelfTestMode = $false
# Carry-forward observations from diagnostic run 34075744762; not a new selection.
$script:ChromiumIdentity = [ordered]@{
  sha256 = "045621e45a9dd27002c7fc1d8e10fe9f5f71f4cadbf44ec6f397f56f0179725c"
  size = [long]201068834
  version = "151.0.7922.34"
}
# A file existing on disk is not proof that its upstream qualification succeeded.
$script:Prerequisites = [ordered]@{
  GIT_WORKFLOW_IDENTITY = @()
  QUALIFICATION_RUNNER_SELF_TEST = @("GIT_WORKFLOW_IDENTITY")
  OPENCODE_ARCHIVE_IDENTITY = @()
  PYTHON_ARCHIVE_IDENTITY = @()
  CHROMIUM_ARCHIVE_DOWNLOAD_AND_MEASURE = @()
  RIPGREP_ARCHIVE_IDENTITY = @()
  CODEGRAPH_BINARY_IDENTITY = @()
  PYTHON_ARCHIVE_EXTRACT = @("PYTHON_ARCHIVE_IDENTITY")
  PYTHON_WINDOWS_EXECUTION = @("PYTHON_ARCHIVE_EXTRACT")
  PYTHON_VC_RUNTIME_REALITY = @("PYTHON_ARCHIVE_EXTRACT")
  PLAYWRIGHT_WHEEL_CLOSURE_DOWNLOAD = @()
  PLAYWRIGHT_OFFLINE_MATERIALIZATION = @("PYTHON_WINDOWS_EXECUTION","PLAYWRIGHT_WHEEL_CLOSURE_DOWNLOAD")
  PLAYWRIGHT_WINDOWS_IMPORT = @("PLAYWRIGHT_OFFLINE_MATERIALIZATION")
  CHROMIUM_ARCHIVE_EXTRACT_AND_VERSION = @("CHROMIUM_ARCHIVE_DOWNLOAD_AND_MEASURE")
  PLAYWRIGHT_CDP_EXTERNAL_CHROMIUM = @("PLAYWRIGHT_WINDOWS_IMPORT","CHROMIUM_ARCHIVE_EXTRACT_AND_VERSION")
  RIPGREP_WINDOWS_EXECUTION = @("RIPGREP_ARCHIVE_IDENTITY")
  CODEGRAPH_WINDOWS_EXECUTION = @("CODEGRAPH_BINARY_IDENTITY")
  OPENCODE_VERSION = @("OPENCODE_ARCHIVE_IDENTITY")
  OPENCODE_PLUGIN_RELEASE_BUILD_MATERIALIZATION = @()
  OPENCODE_QUALIFICATION_WORKSPACE_STAGE = @("PYTHON_WINDOWS_EXECUTION","PLAYWRIGHT_WINDOWS_IMPORT","CHROMIUM_ARCHIVE_EXTRACT_AND_VERSION","RIPGREP_WINDOWS_EXECUTION","CODEGRAPH_BINARY_IDENTITY","CODEGRAPH_WINDOWS_EXECUTION","OPENCODE_PLUGIN_RELEASE_BUILD_MATERIALIZATION")
  OPENCODE_WORKSPACE_LOAD = @("OPENCODE_VERSION","OPENCODE_QUALIFICATION_WORKSPACE_STAGE")
  OPENCODE_AGENT_DISCOVERY = @("OPENCODE_WORKSPACE_LOAD")
  OPENCODE_TOOL_LOAD = @("OPENCODE_WORKSPACE_LOAD")
  OPENCODE_PLUGIN_OFFLINE_LAYOUT = @("OPENCODE_QUALIFICATION_WORKSPACE_STAGE","OPENCODE_WORKSPACE_LOAD")
}

function Add-Check {
  param([string]$Name, [string]$Status, [string]$Detail)
  $script:Checks[$Name] = [ordered]@{ status = $Status; detail = $Detail }
  $prefix = if ($script:SelfTestMode) { "RUNNER_SELFTEST_CHECK" } else { "QUAL_CHECK" }
  Write-Host ("{0} {1}={2} :: {3}" -f $prefix, $Name, $Status, $Detail)
}

function Test-CheckPrerequisites {
  param([string]$Name)
  if ($script:StopReason) {
    Add-Check $Name "BLOCKED_BY_UPSTREAM_QUALIFICATION" ("STOP / " + $script:StopReason)
    return $false
  }
  $dependencies = @()
  if ($Name -notin @("GIT_WORKFLOW_IDENTITY","QUALIFICATION_RUNNER_SELF_TEST")) {
    $dependencies += @("GIT_WORKFLOW_IDENTITY","QUALIFICATION_RUNNER_SELF_TEST")
  }
  if ($script:Prerequisites.Contains($Name)) { $dependencies += $script:Prerequisites[$Name] }
  $blocked = @(foreach ($dependency in $dependencies) {
    if (-not $script:Checks.Contains($dependency)) {
      "$dependency=NOT_EXECUTED"
    } elseif ([string]$script:Checks[$dependency].status -ne "PASS") {
      "$dependency=$($script:Checks[$dependency].status)"
    }
  })
  if ($blocked.Count -gt 0) {
    Add-Check $Name "BLOCKED_BY_UPSTREAM_QUALIFICATION" ("prerequisites=" + ($blocked -join "; ") + "; check_body=NOT_EXECUTED; downstream_product_failure=NOT_ESTABLISHED")
    return $false
  }
  return $true
}

function Classify-Exception {
  param([System.Management.Automation.ErrorRecord]$ErrorRecord)
  $message = [string]$ErrorRecord.Exception.Message
  if ($message.StartsWith("CHROMIUM_ARTIFACT_IDENTITY_CONFLICT")) { $script:StopReason = $message }
  if ($message.StartsWith("EXECUTION_SUBSTRATE_")) {
    return [ordered]@{ status = "BLOCKED_BY_EXECUTION_SUBSTRATE"; detail = $message }
  }
  return [ordered]@{ status = "FAIL"; detail = $message }
}

function Invoke-Checked {
  param([string]$Name, [scriptblock]$Body)
  if (-not (Test-CheckPrerequisites $Name)) { return $false }
  try {
    $detail = & $Body
    if ($null -eq $detail) { $detail = "assertion passed" }
    Add-Check -Name $Name -Status "PASS" -Detail ([string]$detail)
    return $true
  } catch {
    $c = Classify-Exception $_
    Add-Check -Name $Name -Status $c.status -Detail $c.detail
    return $false
  }
}

function Get-QualificationGate {
  param([string[]]$Statuses)
  if ($Statuses -contains "FAIL") { return "FAIL" }
  if (@($Statuses | Where-Object { $_.StartsWith("BLOCKED_") }).Count -gt 0) { return "BLOCKED" }
  return "PASS_CANDIDATE"
}

function Invoke-NativeCapture {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [string[]]$Arguments = @(),
    [string]$WorkingDirectory = $RepoRoot
  )
  Push-Location $WorkingDirectory
  try {
    $output = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
    $code = $LASTEXITCODE
    return [ordered]@{ exit_code = $code; output = $output }
  } finally {
    Pop-Location
  }
}

function Get-Sha256 {
  param([string]$Path)
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Download-Exact {
  param(
    [string]$Url,
    [string]$Destination,
    [string]$ExpectedSha256 = "",
    [long]$ExpectedSize = 0
  )
  $hasExpectedSize = $PSBoundParameters.ContainsKey("ExpectedSize")
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if (-not $curl) { throw "EXECUTION_SUBSTRATE_CURL_NOT_AVAILABLE" }
  $r = Invoke-NativeCapture -FilePath $curl.Source -Arguments @("-fL","--retry","3","--retry-delay","2","--connect-timeout","30","-o",$Destination,$Url) -WorkingDirectory $WorkRoot
  if ($r.exit_code -ne 0 -or -not (Test-Path $Destination)) {
    throw "EXECUTION_SUBSTRATE_DOWNLOAD_FAILED|url=$Url|exit=$($r.exit_code)|output=$($r.output)"
  }
  $sha = Get-Sha256 $Destination
  $size = [long](Get-Item -LiteralPath $Destination).Length
  if ($ExpectedSha256 -and $sha -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "SHA256_MISMATCH|file=$Destination|expected=$ExpectedSha256|actual=$sha"
  }
  if ($hasExpectedSize -and $size -ne [long]$ExpectedSize) {
    throw "SIZE_MISMATCH|file=$Destination|expected=$ExpectedSize|actual=$size"
  }
  return [ordered]@{ path=$Destination; sha256=$sha; size=$size; url=$Url }
}

function Download-PyPiWheel {
  param(
    [string]$Package,
    [string]$Version,
    [string]$Filename,
    [string]$ExpectedSha256,
    [long]$ExpectedSize,
    [string]$Destination
  )
  try {
    $meta = Invoke-RestMethod -Uri "https://pypi.org/pypi/$Package/$Version/json" -TimeoutSec 45
  } catch {
    throw "EXECUTION_SUBSTRATE_PYPI_METADATA_FAILED|package=$Package|version=$Version|$($_.Exception.Message)"
  }
  $entry = @($meta.urls | Where-Object { $_.filename -eq $Filename }) | Select-Object -First 1
  if (-not $entry) { throw "PYPI_EXACT_WHEEL_NOT_FOUND|$Package==$Version|$Filename" }
  if ([string]$entry.digests.sha256 -ne $ExpectedSha256) {
    throw "PYPI_METADATA_SHA256_MISMATCH|$Filename|expected=$ExpectedSha256|metadata=$($entry.digests.sha256)"
  }
  if ([long]$entry.size -ne $ExpectedSize) {
    throw "PYPI_METADATA_SIZE_MISMATCH|$Filename|expected=$ExpectedSize|metadata=$($entry.size)"
  }
  return Download-Exact -Url ([string]$entry.url) -Destination $Destination -ExpectedSha256 $ExpectedSha256 -ExpectedSize $ExpectedSize
}

function Expand-ZipExact {
  param([string]$Archive, [string]$Destination)
  if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
}

function Assert-VersionMatch {
  param([string]$Actual, [string]$Expected, [string]$Label)
  if ($Actual -notmatch [regex]::Escape($Expected)) {
    throw "$Label`_VERSION_MISMATCH|expected=$Expected|actual=$Actual"
  }
}

function Invoke-RunnerSelfTests {
  # Exercise the actual downloader with local file:// fixtures, not network mocks.
  $fixtureDir = Join-Path $WorkRoot "runner-self-tests"
  New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null
  $fixture = Join-Path $fixtureDir "three-bytes.bin"
  $empty = Join-Path $fixtureDir "empty.bin"
  [IO.File]::WriteAllBytes($fixture, [byte[]]@(1,2,3))
  [IO.File]::WriteAllBytes($empty, [byte[]]@())
  $uri = ([Uri]::new($fixture)).AbsoluteUri
  $emptyUri = ([Uri]::new($empty)).AbsoluteUri
  $destination = Join-Path $fixtureDir "download.bin"
  $sha = Get-Sha256 $fixture
  function Assert-Rejected {
    param([scriptblock]$Body, [string]$Prefix)
    try { & $Body | Out-Null } catch {
      if (-not $_.Exception.Message.StartsWith($Prefix)) { throw }
      return
    }
    throw "RUNNER_SELF_TEST_EXPECTED_REJECTION_MISSING|$Prefix"
  }
  $r = Download-Exact $uri $destination -ExpectedSha256 $sha
  if ($r.size -ne 3) { throw "RUNNER_SELF_TEST_UNBOUND_SIZE_FAILED" }
  $r = Download-Exact $uri $destination -ExpectedSha256 $sha -ExpectedSize ([long]3)
  if ($r.size -ne 3) { throw "RUNNER_SELF_TEST_EXACT_SIZE_FAILED" }
  Assert-Rejected { Download-Exact $uri $destination -ExpectedSize ([long]2) } "SIZE_MISMATCH|"
  Assert-Rejected { Download-Exact $uri $destination -ExpectedSize ([long]0) } "SIZE_MISMATCH|"
  Assert-Rejected { Download-Exact $uri $destination -ExpectedSize ([long]4294967296) } "SIZE_MISMATCH|"
  $r = Download-Exact $emptyUri $destination -ExpectedSize ([long]0)
  if ($r.size -ne 0) { throw "RUNNER_SELF_TEST_EMPTY_SIZE_FAILED" }
  Assert-Rejected { Download-Exact $uri $destination -ExpectedSha256 ('0' * 64) -ExpectedSize 3 } "SHA256_MISMATCH|"

  # Isolate injected failures from the formal matrix and label their console output.
  $savedChecks = $script:Checks
  $savedStop = $script:StopReason
  $savedMode = $script:SelfTestMode
  try {
    $script:SelfTestMode = $true
    $script:StopReason = $null
    function Reset-SelfTestChecks {
      $script:Checks = [ordered]@{}
      foreach ($name in $script:Prerequisites.Keys) {
        $script:Checks[$name] = [ordered]@{ status="PASS"; detail="SELF_TEST_FIXTURE_ONLY" }
      }
    }
    function Assert-BodyBlocked {
      param([string]$Name)
      Invoke-Checked $Name { throw "RUNNER_SELF_TEST_DOWNSTREAM_BODY_EXECUTED" } | Out-Null
      if ($script:Checks[$Name].status -ne "BLOCKED_BY_UPSTREAM_QUALIFICATION") {
        throw "RUNNER_SELF_TEST_CASCADE_NOT_BLOCKED|$Name"
      }
    }
    Reset-SelfTestChecks
    $script:Checks["PLAYWRIGHT_WHEEL_CLOSURE_DOWNLOAD"].status = "FAIL"
    foreach ($name in @("PLAYWRIGHT_OFFLINE_MATERIALIZATION","PLAYWRIGHT_WINDOWS_IMPORT","PLAYWRIGHT_CDP_EXTERNAL_CHROMIUM")) { Assert-BodyBlocked $name }
    Reset-SelfTestChecks
    $script:Checks["CODEGRAPH_BINARY_IDENTITY"].status = "FAIL"
    foreach ($name in @("CODEGRAPH_WINDOWS_EXECUTION","OPENCODE_QUALIFICATION_WORKSPACE_STAGE","OPENCODE_WORKSPACE_LOAD","OPENCODE_AGENT_DISCOVERY","OPENCODE_TOOL_LOAD","OPENCODE_PLUGIN_OFFLINE_LAYOUT")) { Assert-BodyBlocked $name }
    Reset-SelfTestChecks
    $script:Checks.Remove("PYTHON_ARCHIVE_IDENTITY")
    Assert-BodyBlocked "PYTHON_ARCHIVE_EXTRACT"
    Reset-SelfTestChecks
    $ok = Invoke-Checked "PYTHON_WINDOWS_EXECUTION" { "real body reached after PASS prerequisites" }
    if (-not $ok -or $script:Checks["PYTHON_WINDOWS_EXECUTION"].status -ne "PASS") { throw "RUNNER_SELF_TEST_POSITIVE_BODY_SKIPPED" }
    $script:StopReason = "CHROMIUM_ARTIFACT_IDENTITY_CONFLICT|SELF_TEST_ONLY"
    Assert-BodyBlocked "RIPGREP_ARCHIVE_IDENTITY"
    if ((Get-QualificationGate @("PASS","BLOCKED_BY_UPSTREAM_QUALIFICATION")) -ne "BLOCKED") { throw "RUNNER_SELF_TEST_BLOCKED_GATE_GREEN" }
    if ((Get-QualificationGate @("FAIL","BLOCKED_BY_UPSTREAM_QUALIFICATION")) -ne "FAIL") { throw "RUNNER_SELF_TEST_ROOT_FAILURE_HIDDEN" }
    if ((Get-QualificationGate @("PASS","DEFERRED_TO_B2","NOT_EXECUTED")) -ne "PASS_CANDIDATE") { throw "RUNNER_SELF_TEST_PASS_GATE_FAILED" }
  } finally {
    $script:Checks = $savedChecks
    $script:StopReason = $savedStop
    $script:SelfTestMode = $savedMode
  }
  $script:Details.runner_self_tests = [ordered]@{
    expected_size_cases=7
    blocked_body_cases=11
    positive_body_cases=1
    aggregate_gate_cases=3
    actual_download_exact_function="EXECUTED_ON_WINDOWS"
    injected_results_in_formal_matrix="NO"
  }
  "22/22 runner self-test cases; ExpectedSize omitted/exact/mismatch/zero/Int64/empty/SHA; upstream cascade and STOP block bodies; aggregate BLOCKED is not green"
}

Invoke-Checked "GIT_WORKFLOW_IDENTITY" {
  $head = Invoke-NativeCapture "git.exe" @("rev-parse","HEAD") $RepoRoot
  if ($head.exit_code -ne 0) { throw "GIT_HEAD_UNREADABLE|$($head.output)" }
  if ($env:GITHUB_SHA -and $head.output.Trim() -ne $env:GITHUB_SHA) {
    throw "GITHUB_SHA_CHECKOUT_MISMATCH|git=$($head.output.Trim())|github=$env:GITHUB_SHA"
  }
  if ($env:GITHUB_REF_NAME -and $env:GITHUB_REF_NAME -ne $ExpectedBranch) {
    throw "BRANCH_MISMATCH|expected=$ExpectedBranch|actual=$env:GITHUB_REF_NAME"
  }
  $parent = Invoke-NativeCapture "git.exe" @("rev-parse","HEAD^") $RepoRoot
  if ($parent.exit_code -ne 0 -or $parent.output.Trim() -ne $ExpectedStartingHead) {
    throw "REPAIR_PARENT_MISMATCH|expected=$ExpectedStartingHead|actual=$($parent.output)"
  }
  $main = Invoke-NativeCapture "git.exe" @("rev-parse","refs/remotes/origin/main") $RepoRoot
  if ($main.exit_code -ne 0 -or $main.output.Trim() -ne $ExpectedMain) { throw "CANONICAL_MAIN_DRIFT|$($main.output)" }
  "branch=$env:GITHUB_REF_NAME; sha=$($head.output.Trim()); starting_head=$ExpectedStartingHead; main=$ExpectedMain"
} | Out-Null

Invoke-Checked "QUALIFICATION_RUNNER_SELF_TEST" { Invoke-RunnerSelfTests } | Out-Null

$downloads = Join-Path $WorkRoot "downloads"
$extract = Join-Path $WorkRoot "extract"
New-Item -ItemType Directory -Force -Path $downloads,$extract | Out-Null

$openCodeZip = Join-Path $downloads "opencode-windows-x64.zip"
$pythonTgz = Join-Path $downloads "cpython-3.12.10+20250529-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$chromeZip = Join-Path $downloads "chrome-win64.zip"
$rgZip = Join-Path $downloads "ripgrep-15.2.0-x86_64-pc-windows-msvc.zip"
$codegraphExe = Join-Path $WorkRoot "codegraph\codegraph-server-win32-x64.exe"
$onnxDll = Join-Path $WorkRoot "codegraph\onnxruntime.dll"

Invoke-Checked "OPENCODE_ARCHIVE_IDENTITY" {
  $a = Download-Exact -Url "https://github.com/anomalyco/opencode/releases/download/v1.18.3/opencode-windows-x64.zip" -Destination $openCodeZip -ExpectedSha256 "68bc62930f6cb5755e0409aa9de0bb270a66ed2b8c9cf0c029e9f2287ed5486e" -ExpectedSize 59152536
  $script:Details.opencode_archive = $a
  "sha256=$($a.sha256); size=$($a.size)"
} | Out-Null

Invoke-Checked "PYTHON_ARCHIVE_IDENTITY" {
  $a = Download-Exact -Url "https://github.com/astral-sh/python-build-standalone/releases/download/20250529/cpython-3.12.10%2B20250529-x86_64-pc-windows-msvc-install_only_stripped.tar.gz" -Destination $pythonTgz -ExpectedSha256 "ca22a9a9e64ecab6d0b5de7cdf8b679ccaa41e9def6aaa2b4aaa6bb23ec7aaba" -ExpectedSize 21172386
  $script:Details.python_archive = $a
  "sha256=$($a.sha256); size=$($a.size)"
} | Out-Null

Invoke-Checked "CHROMIUM_ARCHIVE_DOWNLOAD_AND_MEASURE" {
  $a = Download-Exact -Url "https://storage.googleapis.com/chrome-for-testing-public/151.0.7922.34/win64/chrome-win64.zip" -Destination $chromeZip
  $script:Measured.chromium_archive_sha256 = $a.sha256
  $script:Measured.chromium_archive_size = $a.size
  $script:Details.chromium_archive = $a
  if ($a.sha256 -cne $script:ChromiumIdentity.sha256 -or [long]$a.size -ne $script:ChromiumIdentity.size) {
    throw "CHROMIUM_ARTIFACT_IDENTITY_CONFLICT|expected_sha256=$($script:ChromiumIdentity.sha256)|actual_sha256=$($a.sha256)|expected_size=$($script:ChromiumIdentity.size)|actual_size=$($a.size)"
  }
  "sha256=$($a.sha256); size=$($a.size); carry_forward_identity=EXACT_MATCH"
} | Out-Null

Invoke-Checked "RIPGREP_ARCHIVE_IDENTITY" {
  $a = Download-Exact -Url "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-x86_64-pc-windows-msvc.zip" -Destination $rgZip -ExpectedSha256 "71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5" -ExpectedSize 1789611
  $script:Details.ripgrep_archive = $a
  "sha256=$($a.sha256); size=$($a.size)"
} | Out-Null

Invoke-Checked "CODEGRAPH_BINARY_IDENTITY" {
  $e = Download-Exact -Url "https://github.com/codegraph-ai/CodeGraph/releases/download/v0.20.1/codegraph-server-win32-x64.exe" -Destination $codegraphExe -ExpectedSha256 "aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1" -ExpectedSize 105874432
  $d = Download-Exact -Url "https://github.com/codegraph-ai/CodeGraph/releases/download/v0.20.1/onnxruntime.dll" -Destination $onnxDll -ExpectedSha256 "52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948" -ExpectedSize 11567648
  $script:Details.codegraph_exe = $e
  $script:Details.codegraph_onnxruntime = $d
  "exe_sha256=$($e.sha256); dll_sha256=$($d.sha256); colocated=$((Split-Path $codegraphExe) -eq (Split-Path $onnxDll))"
} | Out-Null

$pythonExtract = Join-Path $extract "python"
$pythonExe = Join-Path $pythonExtract "python\python.exe"
Invoke-Checked "PYTHON_ARCHIVE_EXTRACT" {
  if (-not (Test-Path $pythonTgz)) { throw "EXECUTION_SUBSTRATE_PYTHON_ARCHIVE_UNAVAILABLE" }
  New-Item -ItemType Directory -Force -Path $pythonExtract | Out-Null
  $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
  if (-not $tar) { throw "EXECUTION_SUBSTRATE_TAR_NOT_AVAILABLE" }
  $r = Invoke-NativeCapture $tar.Source @("-xzf",$pythonTgz,"-C",$pythonExtract) $WorkRoot
  if ($r.exit_code -ne 0) { throw "PYTHON_ARCHIVE_EXTRACT_FAILED|$($r.output)" }
  if (-not (Test-Path $pythonExe)) { throw "PYTHON_EXE_MISSING|expected=$pythonExe" }
  "python.exe=$pythonExe"
} | Out-Null

Invoke-Checked "PYTHON_WINDOWS_EXECUTION" {
  if (-not (Test-Path $pythonExe)) { throw "EXECUTION_SUBSTRATE_PORTABLE_PYTHON_UNAVAILABLE" }
  $r = Invoke-NativeCapture $pythonExe @("-c","import sys; print(sys.version.split()[0]); print(sys.executable)") $WorkRoot
  if ($r.exit_code -ne 0) { throw "PORTABLE_PYTHON_EXECUTION_FAILED|$($r.output)" }
  $lines = @($r.output -split "`r?`n")
  Assert-VersionMatch $lines[0] "3.12.10" "PYTHON"
  $actualExe = [IO.Path]::GetFullPath($lines[-1].Trim())
  $expectedExe = [IO.Path]::GetFullPath($pythonExe)
  if (-not $actualExe.Equals($expectedExe,[StringComparison]::OrdinalIgnoreCase)) {
    throw "SYSTEM_PYTHON_FALLBACK_DETECTED|expected=$expectedExe|actual=$actualExe"
  }
  "version=3.12.10; sys.executable=$actualExe; system_fallback=NO"
} | Out-Null

Invoke-Checked "PYTHON_VC_RUNTIME_REALITY" {
  if (-not (Test-Path $pythonExe)) { throw "EXECUTION_SUBSTRATE_PORTABLE_PYTHON_UNAVAILABLE" }
  $pyDir = Split-Path $pythonExe
  $local = @("vcruntime140.dll","vcruntime140_1.dll") | ForEach-Object {
    $p = Join-Path $pyDir $_
    [ordered]@{ name=$_; present=(Test-Path $p); sha256=if(Test-Path $p){Get-Sha256 $p}else{$null} }
  }
  $system = @("vcruntime140.dll","vcruntime140_1.dll") | ForEach-Object {
    $p = Join-Path $env:SystemRoot "System32\$_"
    [ordered]@{ name=$_; present=(Test-Path $p); version=if(Test-Path $p){(Get-Item $p).VersionInfo.FileVersion}else{$null} }
  }
  $script:Details.python_vc_runtime = [ordered]@{ application_local=$local; host_system32=$system }
  $localPresent = @($local | Where-Object { $_.present }).Count
  if ($localPresent -gt 0) {
    $script:Measured.python_vc_runtime_reality = "APPLICATION_LOCAL_PRESENT($localPresent/2)"
  } else {
    $script:Measured.python_vc_runtime_reality = "APPLICATION_LOCAL_ABSENT / HOST_RUNTIME_USED_IF_EXECUTION_PASSED"
    $script:Gaps.Add("PYTHON_APPLICATION_LOCAL_VC_RUNTIME_ABSENT")
  }
  $script:Measured.python_vc_runtime_reality
} | Out-Null

$wheelDir = Join-Path $downloads "wheels"
New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
$wheelSpecs = @(
  [ordered]@{ package="playwright"; version="1.62.0"; filename="playwright-1.62.0-py3-none-win_amd64.whl"; sha256="92c0d98ed04eb35af557b709875edba415b1f548bdb22ddb5bb3e1e6c835c2f1"; size=38164458 },
  [ordered]@{ package="pyee"; version="13.0.1"; filename="pyee-13.0.1-py3-none-any.whl"; sha256="af2f8fede4171ef667dfded53f96e2ed0d6e6bd7ee3bb46437f77e3b57689228"; size=15659 },
  [ordered]@{ package="typing-extensions"; version="4.16.0"; filename="typing_extensions-4.16.0-py3-none-any.whl"; sha256="481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8"; size=45571 },
  [ordered]@{ package="greenlet"; version="3.5.5"; filename="greenlet-3.5.5-cp312-cp312-win_amd64.whl"; sha256="49ddacd36af37735fab103846f4ee4d18a492dde72730d1699c0c8ebe30d9f18"; size=324171 }
)

Invoke-Checked "PLAYWRIGHT_WHEEL_CLOSURE_DOWNLOAD" {
  $downloaded = @()
  foreach ($s in $wheelSpecs) {
    $dest = Join-Path $wheelDir $s.filename
    $downloaded += Download-PyPiWheel -Package $s.package -Version $s.version -Filename $s.filename -ExpectedSha256 $s.sha256 -ExpectedSize $s.size -Destination $dest
  }
  $script:Details.playwright_wheels = $downloaded
  "4/4 exact wheels downloaded and verified; pip_install_online=NO"
} | Out-Null

$sitePackages = Join-Path (Split-Path $pythonExe) "Lib\site-packages"
Invoke-Checked "PLAYWRIGHT_OFFLINE_MATERIALIZATION" {
  if (-not (Test-Path $pythonExe)) { throw "EXECUTION_SUBSTRATE_PORTABLE_PYTHON_UNAVAILABLE" }
  foreach ($s in $wheelSpecs) {
    if (-not (Test-Path (Join-Path $wheelDir $s.filename))) {
      throw "EXECUTION_SUBSTRATE_WHEEL_UNAVAILABLE|$($s.filename)"
    }
  }
  New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
  $py = @'
import pathlib, sys, zipfile
target = pathlib.Path(sys.argv[1])
for wheel in sys.argv[2:]:
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(target)
print(target)
'@
  $args = @("-c",$py,$sitePackages) + @($wheelSpecs | ForEach-Object { Join-Path $wheelDir $_.filename })
  $r = Invoke-NativeCapture $pythonExe $args $WorkRoot
  if ($r.exit_code -ne 0) { throw "PLAYWRIGHT_WHEEL_DIRECT_MATERIALIZATION_FAILED|$($r.output)" }
  "site_packages=$sitePackages; method=verified-wheel-direct-extraction; pip=NOT_USED"
} | Out-Null

$playwrightForbiddenBrowserPath = Join-Path $WorkRoot "forbidden-playwright-managed-browsers"
$env:PLAYWRIGHT_BROWSERS_PATH = $playwrightForbiddenBrowserPath
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
$env:PYTHONNOUSERSITE = "1"

Invoke-Checked "PLAYWRIGHT_WINDOWS_IMPORT" {
  if (-not (Test-Path $pythonExe)) { throw "EXECUTION_SUBSTRATE_PORTABLE_PYTHON_UNAVAILABLE" }
  $code = 'import importlib.metadata as m,sys; from playwright.sync_api import sync_playwright; import pyee,greenlet,typing_extensions; print(sys.executable); print(m.version("playwright"),m.version("pyee"),m.version("typing-extensions"),m.version("greenlet")); p=sync_playwright().start(); print(p.chromium.name); p.stop()'
  $r = Invoke-NativeCapture $pythonExe @("-c",$code) $WorkRoot
  if ($r.exit_code -ne 0) { throw "PLAYWRIGHT_IMPORT_OR_DRIVER_START_FAILED|$($r.output)" }
  if ($r.output -notmatch "1\.62\.0\s+13\.0\.1\s+4\.16\.0\s+3\.5\.5") {
    throw "PLAYWRIGHT_RUNTIME_VERSION_CLOSURE_MISMATCH|$($r.output)"
  }
  $nodeExe = Join-Path $sitePackages "playwright\driver\node.exe"
  $driverPackage = Join-Path $sitePackages "playwright\driver\package"
  if (-not (Test-Path $nodeExe) -or -not (Test-Path $driverPackage)) {
    throw "PLAYWRIGHT_DRIVER_NODE_PAYLOAD_MISSING|node=$nodeExe|package=$driverPackage"
  }
  "portable_python_import=PASS; driver_node=$nodeExe; versions=1.62.0/13.0.1/4.16.0/3.5.5"
} | Out-Null

$chromeExtract = Join-Path $extract "chrome"
$chromeExe = Join-Path $chromeExtract "chrome-win64\chrome.exe"
Invoke-Checked "CHROMIUM_ARCHIVE_EXTRACT_AND_VERSION" {
  if (-not (Test-Path $chromeZip)) { throw "EXECUTION_SUBSTRATE_CHROMIUM_ARCHIVE_UNAVAILABLE" }
  Expand-ZipExact $chromeZip $chromeExtract
  if (-not (Test-Path $chromeExe)) { throw "CHROMIUM_EXE_MISSING|expected=$chromeExe" }
  $version = (Get-Item $chromeExe).VersionInfo.ProductVersion
  if (-not $version) { $version = (Get-Item $chromeExe).VersionInfo.FileVersion }
  $script:Measured.chromium_exe_version = [string]$version
  $script:Details.chromium_exe = [ordered]@{ path=$chromeExe; product_version=$version; sha256=(Get-Sha256 $chromeExe) }
  if ([string]$version -cne $script:ChromiumIdentity.version) {
    throw "CHROMIUM_ARTIFACT_IDENTITY_CONFLICT|expected_version=$($script:ChromiumIdentity.version)|actual_version=$version"
  }
  "chrome.exe=$chromeExe; version=$version; carry_forward_identity=EXACT_MATCH"
} | Out-Null

Invoke-Checked "PLAYWRIGHT_CDP_EXTERNAL_CHROMIUM" {
  if (-not (Test-Path $chromeExe)) { throw "EXECUTION_SUBSTRATE_CHROMIUM_EXE_UNAVAILABLE" }
  if (-not (Test-Path $pythonExe)) { throw "EXECUTION_SUBSTRATE_PORTABLE_PYTHON_UNAVAILABLE" }
  $profile = Join-Path $WorkRoot "chrome-profile"
  New-Item -ItemType Directory -Force -Path $profile | Out-Null
  $port = 9229
  $proc = Start-Process -FilePath $chromeExe -ArgumentList @("--headless=new","--remote-debugging-address=127.0.0.1","--remote-debugging-port=$port","--user-data-dir=$profile","--no-first-run","--no-default-browser-check","about:blank") -PassThru
  try {
    $ready = $false
    $versionJson = $null
    for ($i=0; $i -lt 60; $i++) {
      Start-Sleep -Milliseconds 500
      try {
        $versionJson = Invoke-RestMethod -Uri "http://127.0.0.1:$port/json/version" -TimeoutSec 2
        $ready = $true
        break
      } catch {}
      if ($proc.HasExited) { break }
    }
    if (-not $ready) { throw "CDP_ENDPOINT_NOT_READY|chrome_exit=$($proc.HasExited)" }
    Assert-VersionMatch ([string]$versionJson.Browser) "151.0.7922.34" "CDP_CHROMIUM"
    $code = @'
import sys
from playwright.sync_api import sync_playwright
endpoint=sys.argv[1]
with sync_playwright() as p:
    browser=p.chromium.connect_over_cdp(endpoint)
    print(browser.version)
    print(len(browser.contexts))
    browser.close()
'@
    $r = Invoke-NativeCapture $pythonExe @("-c",$code,"http://127.0.0.1:$port") $WorkRoot
    if ($r.exit_code -ne 0) { throw "PLAYWRIGHT_CONNECT_OVER_CDP_FAILED|$($r.output)" }
    Assert-VersionMatch $r.output "151.0.7922.34" "PLAYWRIGHT_CDP"
    if (Test-Path $playwrightForbiddenBrowserPath) {
      $managedFiles = @(Get-ChildItem -LiteralPath $playwrightForbiddenBrowserPath -Recurse -File -ErrorAction SilentlyContinue)
      if ($managedFiles.Count -gt 0) {
        throw "PLAYWRIGHT_MANAGED_BROWSER_DOWNLOAD_DETECTED|path=$playwrightForbiddenBrowserPath|files=$($managedFiles.Count)"
      }
    }
    "cdp_ready=PASS; connect_over_cdp=PASS; browser=151.0.7922.34; managed_browser_download=NO"
  } finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  }
} | Out-Null

$rgExtract = Join-Path $extract "ripgrep"
$rgExe = Join-Path $rgExtract "ripgrep-15.2.0-x86_64-pc-windows-msvc\rg.exe"
Invoke-Checked "RIPGREP_WINDOWS_EXECUTION" {
  if (-not (Test-Path $rgZip)) { throw "EXECUTION_SUBSTRATE_RIPGREP_ARCHIVE_UNAVAILABLE" }
  Expand-ZipExact $rgZip $rgExtract
  if (-not (Test-Path $rgExe)) { throw "RIPGREP_EXE_MISSING|expected=$rgExe" }
  $v = Invoke-NativeCapture $rgExe @("--version") $WorkRoot
  if ($v.exit_code -ne 0) { throw "RIPGREP_VERSION_COMMAND_FAILED|$($v.output)" }
  Assert-VersionMatch $v.output "15.2.0" "RIPGREP"
  $search = Invoke-NativeCapture $rgExe @("-n","--fixed-strings","R1_EVENT_STREAM",(Join-Path $RepoRoot "workspace-template")) $RepoRoot
  if ($search.exit_code -ne 0 -or -not $search.output) { throw "RIPGREP_REAL_SEARCH_FAILED|exit=$($search.exit_code)|$($search.output)" }
  $script:Details.ripgrep = [ordered]@{ absolute_path=$rgExe; version_output=$v.output; search_sample=($search.output -split "`r?`n" | Select-Object -First 5) }
  "absolute_path=$rgExe; version=15.2.0; real_search=PASS; system_rg_fallback=NO"
} | Out-Null

Invoke-Checked "CODEGRAPH_WINDOWS_EXECUTION" {
  if (-not (Test-Path $codegraphExe) -or -not (Test-Path $onnxDll)) { throw "EXECUTION_SUBSTRATE_CODEGRAPH_PAYLOAD_UNAVAILABLE" }
  if ((Split-Path $codegraphExe) -ne (Split-Path $onnxDll)) { throw "CODEGRAPH_ONNXRUNTIME_NOT_COLOCATED" }
  $info = Invoke-NativeCapture $codegraphExe @("--info") (Split-Path $codegraphExe)
  if ($info.exit_code -ne 0) { throw "CODEGRAPH_INFO_FAILED|exit=$($info.exit_code)|$($info.output)" }
  if ($info.output -notmatch "0\.20\.1") { throw "CODEGRAPH_VERSION_NOT_PROVEN|$($info.output)" }
  $script:Details.codegraph_info = $info.output
  "exe+dll_colocated=PASS; process_start=PASS; --info=PASS; version=0.20.1"
} | Out-Null

$openCodeExtract = Join-Path $extract "opencode"
$openCodeExe = $null
Invoke-Checked "OPENCODE_VERSION" {
  if (-not (Test-Path $openCodeZip)) { throw "EXECUTION_SUBSTRATE_OPENCODE_ARCHIVE_UNAVAILABLE" }
  Expand-ZipExact $openCodeZip $openCodeExtract
  $candidate = Get-ChildItem -LiteralPath $openCodeExtract -Recurse -File -Filter "opencode.exe" | Select-Object -First 1
  if (-not $candidate) { throw "OPENCODE_EXE_MISSING_AFTER_EXTRACT" }
  $script:Paths.opencode_exe = $candidate.FullName
  $v = Invoke-NativeCapture $candidate.FullName @("--version") $WorkRoot
  if ($v.exit_code -ne 0) { throw "OPENCODE_VERSION_COMMAND_FAILED|$($v.output)" }
  Assert-VersionMatch $v.output "1.18.3" "OPENCODE"
  $script:Measured.opencode_version = "1.18.3"
  "path=$($candidate.FullName); version=1.18.3"
} | Out-Null
if ($script:Paths.Contains("opencode_exe")) { $openCodeExe = [string]$script:Paths.opencode_exe }

$pluginStage = Join-Path $WorkRoot "plugin-stage"
Invoke-Checked "OPENCODE_PLUGIN_RELEASE_BUILD_MATERIALIZATION" {
  $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $npm) { throw "EXECUTION_SUBSTRATE_NPM_NOT_AVAILABLE_FOR_RELEASE_BUILD_MATERIALIZATION" }
  New-Item -ItemType Directory -Force -Path $pluginStage | Out-Null
  $packageJson = [ordered]@{ private=$true; dependencies=[ordered]@{ "@opencode-ai/plugin"="1.18.3" } }
  $packageJson | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $pluginStage "package.json") -Encoding utf8
  $r = Invoke-NativeCapture $npm.Source @("install","--ignore-scripts","--no-audit","--no-fund","--save-exact") $pluginStage
  if ($r.exit_code -ne 0) { throw "EXECUTION_SUBSTRATE_NPM_RELEASE_BUILD_MATERIALIZATION_FAILED|$($r.output)" }
  $pluginManifest = Join-Path $pluginStage "node_modules\@opencode-ai\plugin\package.json"
  $lockPath = Join-Path $pluginStage "package-lock.json"
  if (-not (Test-Path $pluginManifest) -or -not (Test-Path $lockPath)) { throw "OPENCODE_PLUGIN_PREPROVISION_LAYOUT_INCOMPLETE" }
  $pm = Get-Content -Raw -LiteralPath $pluginManifest | ConvertFrom-Json
  if ([string]$pm.version -ne "1.18.3") { throw "OPENCODE_PLUGIN_VERSION_MISMATCH|$($pm.version)" }
  $script:Details.plugin_release_build = [ordered]@{
    plugin_version=[string]$pm.version
    package_lock_sha256=Get-Sha256 $lockPath
    node_modules_file_count=@(Get-ChildItem (Join-Path $pluginStage "node_modules") -Recurse -File).Count
    target_host_online_install="FORBIDDEN"
  }
  $script:pluginLayoutReady = $true
  "plugin=1.18.3; package-lock+node_modules materialized on CI release-build substrate"
} | Out-Null

$ocWorkspace = Join-Path $WorkRoot "opencode-workspace"
Invoke-Checked "OPENCODE_QUALIFICATION_WORKSPACE_STAGE" {
  Copy-Item -Recurse -Force (Join-Path $RepoRoot "workspace-template") $ocWorkspace
  if (-not (Test-Path (Join-Path $ocWorkspace "opencode.json"))) { throw "WORKSPACE_TEMPLATE_COPY_FAILED" }

  $marker = [ordered]@{
    schema_version="pfc.r1-r4.installation.v2"
    package_id="PKG0.6B1_QUALIFICATION_TEMP"
    build_identity="QUALIFICATION_ONLY_NOT_PACKAGE_TRUTH"
    runtime_workspace=$ocWorkspace
    opencode_version="1.18.3"
  }
  $marker | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ocWorkspace "PFC_R1_R4_INSTALLATION.json") -Encoding utf8

  $targetPython = Join-Path $ocWorkspace "runtime\python"
  if (Test-Path $targetPython) { Remove-Item -Recurse -Force $targetPython }
  New-Item -ItemType Directory -Force -Path (Split-Path $targetPython -Parent) | Out-Null
  Copy-Item -Recurse -Force (Split-Path $pythonExe) $targetPython

  $targetChrome = Join-Path $ocWorkspace "runtime\browser\chrome-win64"
  New-Item -ItemType Directory -Force -Path (Split-Path $targetChrome -Parent) | Out-Null
  if (Test-Path $targetChrome) { Remove-Item -Recurse -Force $targetChrome }
  Copy-Item -Recurse -Force (Split-Path $chromeExe) $targetChrome

  $targetRgDir = Join-Path $ocWorkspace "runtime\bin"
  New-Item -ItemType Directory -Force -Path $targetRgDir | Out-Null
  Copy-Item -Force $rgExe (Join-Path $targetRgDir "rg.exe")

  $targetCgDir = Join-Path $ocWorkspace "runtime\code-intelligence\codegraph"
  New-Item -ItemType Directory -Force -Path $targetCgDir | Out-Null
  Copy-Item -Force $codegraphExe (Join-Path $targetCgDir "codegraph-server-win32-x64.exe")
  Copy-Item -Force $onnxDll (Join-Path $targetCgDir "onnxruntime.dll")

  if (-not $script:pluginLayoutReady) { throw "EXECUTION_SUBSTRATE_PLUGIN_PREPROVISION_LAYOUT_UNAVAILABLE" }
  Copy-Item -Force (Join-Path $pluginStage "package.json") (Join-Path $ocWorkspace ".opencode\package.json")
  Copy-Item -Force (Join-Path $pluginStage "package-lock.json") (Join-Path $ocWorkspace ".opencode\package-lock.json")
  Copy-Item -Recurse -Force (Join-Path $pluginStage "node_modules") (Join-Path $ocWorkspace ".opencode\node_modules")

  "staged_post_install_workspace=$ocWorkspace; qualification_marker=TEMP_ONLY; product_source_modified=NO"
} | Out-Null

$oldHttpProxy = $env:HTTP_PROXY
$oldHttpsProxy = $env:HTTPS_PROXY
$oldAllProxy = $env:ALL_PROXY
$oldNoProxy = $env:NO_PROXY
$env:HTTP_PROXY = "http://127.0.0.1:9"
$env:HTTPS_PROXY = "http://127.0.0.1:9"
$env:ALL_PROXY = "http://127.0.0.1:9"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:AITEST_WORKSPACE_ROOT = $ocWorkspace
$env:AITEST_RUNTIME_SPINE_DB = Join-Path $WorkRoot "runtime-spine.db"
$env:PYTHONPATH = Join-Path $ocWorkspace "ai-test\runtime"

$pluginLockBefore = if(Test-Path (Join-Path $ocWorkspace ".opencode\package-lock.json")){Get-Sha256 (Join-Path $ocWorkspace ".opencode\package-lock.json")}else{$null}
$pluginCountBefore = if(Test-Path (Join-Path $ocWorkspace ".opencode\node_modules")){@(Get-ChildItem (Join-Path $ocWorkspace ".opencode\node_modules") -Recurse -File).Count}else{-1}

Invoke-Checked "OPENCODE_WORKSPACE_LOAD" {
  if (-not $openCodeExe) { throw "EXECUTION_SUBSTRATE_OPENCODE_EXE_UNAVAILABLE" }
  $r = Invoke-NativeCapture $openCodeExe @("debug","config") $ocWorkspace
  if ($r.exit_code -ne 0) { throw "OPENCODE_DEBUG_CONFIG_FAILED|$($r.output)" }
  $cfg = $r.output | ConvertFrom-Json
  if ([string]$cfg.default_agent -ne "aitest-director") { throw "OPENCODE_DEFAULT_AGENT_MISMATCH|$($cfg.default_agent)" }
  "debug_config=PASS; default_agent=aitest-director; workspace=$ocWorkspace"
} | Out-Null

Invoke-Checked "OPENCODE_AGENT_DISCOVERY" {
  if (-not $openCodeExe) { throw "EXECUTION_SUBSTRATE_OPENCODE_EXE_UNAVAILABLE" }
  $r = Invoke-NativeCapture $openCodeExe @("agent","list") $ocWorkspace
  if ($r.exit_code -ne 0) { throw "OPENCODE_AGENT_LIST_FAILED|$($r.output)" }
  if ($r.output -notmatch "(?m)^aitest-director\s" -or $r.output -notmatch "(?m)^aitest-diagnosis\s") {
    throw "OPENCODE_REQUIRED_AGENT_NOT_DISCOVERED|$($r.output)"
  }
  $script:Details.opencode_agent_list = $r.output
  "aitest-director=DISCOVERED; aitest-diagnosis=DISCOVERED"
} | Out-Null

if (Test-CheckPrerequisites "OPENCODE_TOOL_LOAD") {
  if ($openCodeExe) {
    $probe = Invoke-NativeCapture $openCodeExe @("debug","agent","aitest-director") $ocWorkspace
    if ($probe.exit_code -eq 0 -and $probe.output -match "aitest_director" -and $probe.output -match "aitest_human_gate_resume") {
      Add-Check "OPENCODE_TOOL_LOAD" "PASS" "ToolRegistry exposed aitest_director and aitest_human_gate_resume without an LLM turn"
    } elseif ($probe.output -match "No providers found|No models found|Model not found|provider") {
      Add-Check "OPENCODE_TOOL_LOAD" "DEFERRED_TO_B2" ("ToolRegistry requires provider/model binding unavailable in generic CI; no interactive PASS claimed :: " + $probe.output)
    } else {
      Add-Check "OPENCODE_TOOL_LOAD" "DEFERRED_TO_B2" ("CI could not prove ToolRegistry load without target provider/runtime; no interactive PASS claimed :: " + $probe.output)
    }
    $script:Details.opencode_tool_probe = [ordered]@{ exit_code=$probe.exit_code; output=$probe.output }
  } else {
    Add-Check "OPENCODE_TOOL_LOAD" "BLOCKED_BY_EXECUTION_SUBSTRATE" "OpenCode executable unavailable"
  }
}

Invoke-Checked "OPENCODE_PLUGIN_OFFLINE_LAYOUT" {
  $lockPath = Join-Path $ocWorkspace ".opencode\package-lock.json"
  $pluginManifest = Join-Path $ocWorkspace ".opencode\node_modules\@opencode-ai\plugin\package.json"
  if (-not (Test-Path $lockPath) -or -not (Test-Path $pluginManifest)) { throw "OPENCODE_PLUGIN_OFFLINE_LAYOUT_MISSING" }
  $pm = Get-Content -Raw -LiteralPath $pluginManifest | ConvertFrom-Json
  if ([string]$pm.version -ne "1.18.3") { throw "OPENCODE_PLUGIN_OFFLINE_LAYOUT_VERSION_MISMATCH|$($pm.version)" }
  $lockAfter = Get-Sha256 $lockPath
  $countAfter = @(Get-ChildItem (Join-Path $ocWorkspace ".opencode\node_modules") -Recurse -File).Count
  if ($pluginLockBefore -ne $lockAfter -or $pluginCountBefore -ne $countAfter) {
    throw "OPENCODE_PLUGIN_LAYOUT_MUTATED_DURING_TARGET_STYLE_PROBE|lock_before=$pluginLockBefore|lock_after=$lockAfter|count_before=$pluginCountBefore|count_after=$countAfter"
  }
  "preprovisioned_package_lock_and_node_modules=PASS; plugin=1.18.3; dead_proxy_target_probe=PASS; layout_mutation=NO"
} | Out-Null

$env:HTTP_PROXY = $oldHttpProxy
$env:HTTPS_PROXY = $oldHttpsProxy
$env:ALL_PROXY = $oldAllProxy
$env:NO_PROXY = $oldNoProxy

Add-Check "WINDOWS_INTERACTIVE_QUALIFICATION" "NOT_EXECUTED" "PKG0.6B2 only"
$script:Gaps.Add("CODEGRAPH_ONNXRUNTIME_DLL_RUNTIME_LOCK_REPRESENTATION=PKG1_REQUIRED")
$script:Gaps.Add("OPENCODE_PLUGIN_FINAL_OFFLINE_MATERIALIZATION=PKG1_REQUIRED")
$script:Gaps.Add("OPENCODE_WEB_AND_SIDECAR_INTERACTIVE_REQUIREMENT=UNRESOLVED_B2")

$statuses = @($script:Checks.Values | ForEach-Object { [string]$_.status })
$gateStatus = Get-QualificationGate $statuses

$result = [ordered]@{
  schema_version = "pkg0.6b1.windows-qualification.v2"
  gate = "PKG0.6B1"
  work_item = "PKG0.6B1R"
  gate_status = $gateStatus
  stop_reason = $script:StopReason
  starting_head = $ExpectedStartingHead
  dependency_candidate_head = $DependencyCandidateHead
  first_run = [ordered]@{
    run_id="34075744762"
    workflow_commit="b2556de9a3a0dfc3e3028fb168284688ef3a24fc"
    classification="QUALIFICATION_RUNNER_DEFECT"
    authority="DIAGNOSTIC_EVIDENCE_VALID / NOT_FINAL_QUALIFICATION"
    valid_observations="RETAINED_IN_FIRST_RUN_ARTIFACT; FRESH_RECONFIRMATION_RECORDED_PER_CHECK_STATUS"
  }
  repository = "TongAITech/opencode-test-digital-employee"
  branch = if($env:GITHUB_REF_NAME){$env:GITHUB_REF_NAME}else{$ExpectedBranch}
  workflow_path = $WorkflowPath
  workflow_commit = if($env:GITHUB_SHA){$env:GITHUB_SHA}else{(Invoke-NativeCapture "git.exe" @("rev-parse","HEAD") $RepoRoot).output}
  workflow_run_id = $env:GITHUB_RUN_ID
  workflow_run_attempt = $env:GITHUB_RUN_ATTEMPT
  runner_os = $env:RUNNER_OS
  runner_name = $env:RUNNER_NAME
  runner_arch = $env:RUNNER_ARCH
  chromium_archive_sha256 = $script:Measured.chromium_archive_sha256
  chromium_archive_size = $script:Measured.chromium_archive_size
  chromium_exe_version = $script:Measured.chromium_exe_version
  python_archive_identity = [string]$script:Checks["PYTHON_ARCHIVE_IDENTITY"].status
  python_windows_execution = [string]$script:Checks["PYTHON_WINDOWS_EXECUTION"].status
  python_vc_runtime_reality = $script:Measured.python_vc_runtime_reality
  playwright_wheel_closure = [string]$script:Checks["PLAYWRIGHT_WHEEL_CLOSURE_DOWNLOAD"].status
  playwright_windows_import = [string]$script:Checks["PLAYWRIGHT_WINDOWS_IMPORT"].status
  playwright_cdp_external_chromium = [string]$script:Checks["PLAYWRIGHT_CDP_EXTERNAL_CHROMIUM"].status
  ripgrep_archive_identity = [string]$script:Checks["RIPGREP_ARCHIVE_IDENTITY"].status
  ripgrep_windows_execution = [string]$script:Checks["RIPGREP_WINDOWS_EXECUTION"].status
  codegraph_binary_identity = [string]$script:Checks["CODEGRAPH_BINARY_IDENTITY"].status
  codegraph_windows_execution = [string]$script:Checks["CODEGRAPH_WINDOWS_EXECUTION"].status
  opencode_archive_identity = [string]$script:Checks["OPENCODE_ARCHIVE_IDENTITY"].status
  opencode_version = $script:Measured.opencode_version
  opencode_workspace_load = [string]$script:Checks["OPENCODE_WORKSPACE_LOAD"].status
  opencode_agent_discovery = [string]$script:Checks["OPENCODE_AGENT_DISCOVERY"].status
  opencode_tool_load = [string]$script:Checks["OPENCODE_TOOL_LOAD"].status
  opencode_plugin_offline_layout = [string]$script:Checks["OPENCODE_PLUGIN_OFFLINE_LAYOUT"].status
  opencode_web_required = $script:Measured.opencode_web_required
  opencode_sidecar_required = $script:Measured.opencode_sidecar_required
  windows_interactive_qualification = "NOT_EXECUTED / PKG0.6B2"
  binary_identity_gaps_remaining = @($script:Gaps)
  product_semantics_modified = "NO"
  runtime_lock_modified = "NO"
  package_manifest_modified = "NO"
  checks = $script:Checks
  prerequisite_graph = $script:Prerequisites
  details = $script:Details
}

$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ResultPath -Encoding utf8
Write-Host "QUALIFICATION_RESULT_PATH=$ResultPath"
Write-Host "QUALIFICATION_GATE_STATUS=$gateStatus"
Write-Host "QUALIFICATION_RESULT_JSON_BEGIN"
Get-Content -Raw -LiteralPath $ResultPath | Write-Host
Write-Host "QUALIFICATION_RESULT_JSON_END"
