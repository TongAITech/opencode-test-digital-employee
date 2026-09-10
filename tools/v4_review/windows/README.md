# Windows no-admin isolation probe

Status: **SOURCE READY; LOCAL COMPILE SUCCEEDED; WINDOWS EXECUTION NOT_RUN; ISOLATION NOT_PROVEN.**

This probe is an isolated V4 F54 feasibility experiment. It does not install a General Worker, change the product repository, authorize a bank target, or claim that arbitrary production tools are safely confined. Current product reference is `042a88a3fa3ac93cecb7b0d3ad5ff4b7f6bd71ac`.

The implementation uses the classic Windows AppContainer creation path: unique package identity, a zero-capability security descriptor on process creation, and filesystem ACL grants for that identity. The fixture root grant does not inherit; bin/read fixtures receive recursive read/execute, notes receive modify, and protected/outside roots have explicit AppContainer denial. Microsoft documents the AppContainer/user access intersection and the required process attributes in [Launch an AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer). It describes filesystem and network isolation in [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation). These documents justify selecting a real OS primitive; the probe result must establish observed behavior on the target Windows image.

## Files

- `AppContainerProbe.cs`: parent oracle, native launch boundary, trusted instrumented attack child, cmd and PowerShell descendants, local TCP fixture.
- `run-spike.ps1`: creates a new disposable directory, compiles with the installed Windows .NET Framework compiler, runs the probe, and returns nonzero unless the complete bounded oracle passes.
- `static-qualification.json`: source/binary SHA256 and local compile-only status.
- `AppContainerProbe.syntax-check.exe`: local Mono syntax-check output; **do not use it for Windows qualification**. The wrapper recompiles source using the Windows image's installed compiler.

Windows integration entry:

```powershell
& .\run-spike.ps1 -OutputDirectory (Join-Path $env:RUNNER_TEMP ('aitest-isolation-' + [Guid]::NewGuid().ToString('N')))
```

The wrapper refuses an existing output directory. It downloads nothing. The actual probe must run without an elevated token and without enabled Administrators membership. On elevated CI, an outer bootstrap attempts to launch the same probe with the UAC linked limited token. This bootstrap is recorded separately. If the host has no suitable limited token or cannot launch it, the result is **ENVIRONMENT_BLOCKED**, not no-admin PASS. A normal non-admin Windows account can run the wrapper directly.

The limited probe creates a disposable current-user AppContainer profile and changes ACLs only on the newly created fixture tree. It does not alter UAC, firewall policy, machine settings, loopback exemptions, host authentication, bank files, or the product R1 store. The profile is deleted on completion; any cleanup failure is reported and prevents full bounded PASS. The fixture directory remains as evidence.

## What the outer oracle requires

1. Actual parent token is non-elevated with Administrators disabled. Actual child and both cmd/PowerShell descendants report the expected AppContainer SID and zero capabilities.
2. The contained child reads an approved diagnostic fixture and creates/reads an approved note. cmd redirection and PowerShell code each create their own approved note and actually start a further instrumented executable. A failed process launch is not a confinement PASS.
3. The child and both descendants attempt real reads from protected/outside sentinels, writes to an authorized read-only fixture, and real writes to a protected scratch `runtime-spine.db` sentinel, a separate outside-root sentinel, a `..` traversal, an uppercase path alias, and a junction from the allowed notes root into the protected root. Each attempt must return an access-denied exception. Other I/O errors do not count as denial proof.
4. cmd redirection and PowerShell's own file APIs also attempt unauthorized sentinel writes. The outer non-container oracle first proves it can read the protected/outside/read-only fixtures, then compares all three original contents after all children exit.
5. A real parent TCP connection succeeds to a live loopback fixture and is observed by the server. The child and descendants try the same endpoint with no network capability. Each must receive Windows socket `WSAEACCES`/10013; connection refusal, DNS failure, timeout, or absence of a request is insufficient. The server must observe only the parent control marker.
6. No parent handles are inherited by the AppContainer process. Its environment is an explicit small set of Windows executable and scratch temporary paths. A JobObject terminates remaining descendants on closure; this provides cleanup, **not** the filesystem/network security claim.

Every required positive and negative path must complete for `PASS_BOUNDED_NATIVE_FIXTURE`. The wrapper fails otherwise and preserves `result.json`, bootstrap-token metadata, compiler output, source/executable identities, and all child reports.

## Limits and next integration requirements

- This is a Windows OS primitive probe, not final installed-package L3 or bank L5 qualification. Local Mono compilation on macOS proves only that this C# source compiles against the available framework API surface; no Win32 P/Invoke or PowerShell execution occurred locally.
- Standard AppContainer has its own profile and Windows-granted system resources. It is not a proof that literally all bytes outside one directory are inaccessible. Protected product resources must be explicitly excluded from writable grants and reachable broker APIs. The probe tests read denial and mutation confinement for the named synthetic paths.
- The networking experiment covers unauthorized TCP to a live same-host endpoint. Non-loopback egress, DNS, UDP, named pipes, COM/RPC, approved network brokers, and target-specific network policy still require additional qualification. No broad production networking capability should be added merely to make a later fixture pass.
- Arbitrary bank-installed Python, Git Bash, build systems, browser libraries, host OpenCode plugins, vendor DLLs, antivirus policies, and corporate Windows lockdown may introduce compatibility constraints. cmd and PowerShell descendants exercise actual interpreter/process inheritance; they do not certify every installed tool.
- Runtime-issued caller/session/epoch leases, revocation, conflict-safe writes, protected-resource catalogues, R1 event receipts, diagnostic repair candidates, and routing into G4 remain product implementation work. This native fixture cannot supply those contracts.
- Junction failure, compiler absence, AppContainer launch failure, denied approved work, missing limited-token context, or malformed child evidence remain explicit blockers or failures. Fix the source/host integration and repeat the same oracle; do not relax expected outcomes to manufacture green evidence.
