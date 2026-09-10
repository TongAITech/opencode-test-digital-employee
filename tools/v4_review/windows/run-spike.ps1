[CmdletBinding()]
param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'WINDOWS_REQUIRED: this probe cannot run on macOS/Linux.' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $env:TEMP ('aitest-appcontainer-spike-' + [Guid]::NewGuid().ToString('N')) }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $OutputDirectory) { throw 'OUTPUT_MUST_BE_NEW: refusing to change permissions on any existing directory.' }
[IO.Directory]::CreateDirectory((Join-Path $OutputDirectory 'bin')) | Out-Null
Set-Content -LiteralPath (Join-Path $OutputDirectory 'SPIKE_ONLY.marker') -Value 'DISPOSABLE_SYNTHETIC_FIXTURE_ONLY'
$source = Join-Path $PSScriptRoot 'AppContainerProbe.cs'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'ENVIRONMENT_BLOCKED: .NET Framework compiler unavailable; no runtime will be downloaded.' }
$exe = Join-Path $OutputDirectory 'bin\AppContainerProbe.exe'
& $compiler /nologo /target:exe /platform:x64 /optimize+ '/reference:System.Web.Extensions.dll' ('/out:' + $exe) $source 2>&1 | Tee-Object -FilePath (Join-Path $OutputDirectory 'compile.log')
if ($LASTEXITCODE -ne 0) { throw ('COMPILE_FAILED; output=' + $OutputDirectory) }
Get-FileHash -Algorithm SHA256 $source,$exe | Select-Object Path,Hash | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'identities.json')
& $exe --bootstrap $OutputDirectory
$probeExit = $LASTEXITCODE
$result = Join-Path $OutputDirectory 'result.json'
if (Test-Path -LiteralPath $result) { Get-Content -Raw -LiteralPath $result }
Write-Output ('SPIKE_ARTIFACT_DIRECTORY=' + $OutputDirectory)
if ($probeExit -ne 0) { throw ('WINDOWS_ISOLATION_NOT_PROVEN; exit=' + $probeExit + '; output=' + $OutputDirectory) }
