[CmdletBinding()]
param([string]$OutputDirectory, [switch]$UseDisposableCiUser, [string]$RuntimeDirectory, [string]$GitDirectory)
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
# These copies become read/execute-only before the confined process starts.
if ($RuntimeDirectory -or $GitDirectory) {
    if (-not (Test-Path "$RuntimeDirectory/python/python.exe") -or -not (Test-Path "$GitDirectory/bin/bash.exe")) { throw 'INTERPRETER_PAYLOAD_MISSING_FAIL_CLOSED' }
    Copy-Item "$RuntimeDirectory/python" (Join-Path $OutputDirectory 'bin/python') -Recurse
    Copy-Item $GitDirectory (Join-Path $OutputDirectory 'bin/git') -Recurse
    Copy-Item (Join-Path $PSScriptRoot 'python-proof.py') (Join-Path $OutputDirectory 'bin/python-proof.py')
    Copy-Item (Join-Path $PSScriptRoot 'bash-proof.sh') (Join-Path $OutputDirectory 'bin/bash-proof.sh')
    Set-Content (Join-Path $OutputDirectory 'bin/interpreters-required.marker') 'PYTHON_AND_GIT_BASH_MUST_EXECUTE'
    @{ python_source='HASH_PINNED_PREVIOUS_OFFLINE_PACKAGE'; git_source='EXISTING_GITHUB_RUNNER_GIT_INSTALLATION'; python_sha256=(Get-FileHash "$RuntimeDirectory/python/python.exe" -Algorithm SHA256).Hash; bash_sha256=(Get-FileHash "$GitDirectory/bin/bash.exe" -Algorithm SHA256).Hash; git_directory=$GitDirectory } | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'interpreter-identities.json')
}
Get-FileHash -Algorithm SHA256 $source,$exe | Select-Object Path,Hash | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'identities.json')
if ($UseDisposableCiUser) {
    # CI provisioning is separate from the product user's no-admin execution.
    # Hosted runners may disable UAC and have no linked limited token.
    if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP -or
        -not $OutputDirectory.StartsWith(([IO.Path]::GetFullPath($env:RUNNER_TEMP) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'CI_USER_BOOTSTRAP_REQUIRES_DISPOSABLE_GITHUB_RUNNER_TEMP'
    }
    $userName = 'v4probe' + [Guid]::NewGuid().ToString('N').Substring(0,10)
    $securePassword = ConvertTo-SecureString ('V4!' + [Guid]::NewGuid().ToString('N') + 'a9!') -AsPlainText -Force
    $created = $false
    try {
        $account = New-LocalUser -Name $userName -Password $securePassword -Description 'Disposable synthetic V4 CI probe' -AccountNeverExpires
        $created = $true
        $acl = Get-Acl -LiteralPath $OutputDirectory
        $rule = [Security.AccessControl.FileSystemAccessRule]::new($account.SID, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $OutputDirectory -AclObject $acl
        $credential = [PSCredential]::new(($env:COMPUTERNAME + '\' + $userName), $securePassword)
        $child = Start-Process -FilePath $exe -ArgumentList @('--run', ('"' + $OutputDirectory + '"')) -WorkingDirectory $OutputDirectory -Credential $credential -LoadUserProfile -Wait -PassThru
        $probeExit = $child.ExitCode
        # Only after the complete probe and its descendants exit, let the CI
        # evidence collector read the new fixture tree. This is not a child grant.
        $collectorAcl = Get-Acl -LiteralPath $OutputDirectory
        $collectorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $collectorAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($collectorSid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
        Set-Acl -LiteralPath $OutputDirectory -AclObject $collectorAcl
        @{ mode='DISPOSABLE_CI_STANDARD_LOCAL_USER'; user_sid=$account.SID.Value; child_exit=$probeExit; product_install_admin_requirement='NONE_INTRODUCED'; setup_requires_ci_admin=$true } | ConvertTo-Json | Set-Content (Join-Path $OutputDirectory 'ci-user-bootstrap.json')
    } finally {
        if ($created) { Remove-LocalUser -Name $userName }
    }
} else {
    & $exe --bootstrap $OutputDirectory
    $probeExit = $LASTEXITCODE
}
$result = Join-Path $OutputDirectory 'result.json'
if (Test-Path -LiteralPath $result) { Get-Content -Raw -LiteralPath $result }
Write-Output ('SPIKE_ARTIFACT_DIRECTORY=' + $OutputDirectory)
if ($probeExit -ne 0) { throw ('WINDOWS_ISOLATION_NOT_PROVEN; exit=' + $probeExit + '; output=' + $OutputDirectory) }
