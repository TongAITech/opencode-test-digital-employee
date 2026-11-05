# Local Mac Validation Enablement v1

Status: ENGINEERING CANDIDATE  
Branch: `work/local-mac-validation`  
Baseline: `4edd78536633d4258705c6083fe55b44e51f54bb`  
ArchitectureBaseline: `v7 / FROZEN / UNCHANGED`

## Purpose

Enable a local macOS reference environment for validating the OpenCode testing
digital employee before bank field validation.

This WorkItem is platform/packaging enablement only. It does not change R1 Event
Stream truth, Planner/Scheduler semantics, Session Router semantics, G3/G4
testing intelligence or real-execution semantics, and it does not contain G5.

## Frozen boundaries

- Existing bank Windows packaging source and root `runtime-lock.json` stay unchanged.
- Canonical product source under `workspace-template/` stays unchanged.
- Local Mac package is a derived payload, never Engineering Source Truth.
- R1 Event Stream remains sole durable Runtime Truth.
- System Python is not a runtime fallback.
- Target-host dependency installation is forbidden.
- Runtime binaries/dependencies are acquired only during offline-package assembly.
- PFC source, credentials, cookies, DBs and runtime state are never committed.

## Gates

```text
LMV-0 MAC_OFFLINE_PACKAGE_BUILD
LMV-1 OPENCODE_1_18_3_ADMISSION
LMV-2 R1_R4_RUNTIME_BOOT
LMV-3 LOCAL_PFC_TARGET_BINDING
LMV-4 PFC_SMOKE_AND_PRODUCT_LOOP
LMV-5 AUTONOMOUS_TESTING_EVIDENCE
LMV-6 DEFECT_HUNTER (after G5 is independently frozen)
```

This enablement implements LMV-0..LMV-3 capability. Runtime PASS still requires
real execution evidence on the target Mac.

## Runtime profile

The assembly profile pins:

- CPython 3.12.10 portable install-only distribution.
- Playwright Python 1.62.0, installed into portable Python at assembly time.
- OpenCode 1.18.3.
- Chrome for Testing 151.0.7922.34.
- CodeGraph 0.20.1.
- ripgrep 15.1.0.

Both Apple Silicon and Intel lock profiles are present.

Chrome archive identities were first observed from successful real builds on
GitHub-hosted native Mac runners and then promoted into the lock profiles:

- arm64: `01a23ef9501b2745e0c2944c2e583207e6f6132d8d91c3a87ff65b5079e438ef`
- x64: `69bcc853db975a2380767e9ff36da17f1d7b782fbbe191a210f676d2d5967d3e`

The canonical package assembly entry is `packaging/local-mac/pinned-build.sh`.
A subsequent independent build must re-download Chrome and verify the archive
against these already-recorded digests before LMV-0 can be accepted.

## Compatibility model

No product-source rewrite is required.

1. Mac package creates `runtime/python/python.exe` as a package-local symlink to
   `runtime/python/bin/python3`, preserving the existing no-system-fallback
   runtime contract.
2. A package-owned bash wrapper ensures existing OpenCode lifecycle code resolves
   bundled OpenCode 1.18.3 even when login-shell PATH files differ.
3. Existing Browser runtime is bound through `AITEST_BROWSER_EXECUTABLE`.
4. Existing CodeGraph resolver is bound through `AITEST_RUNTIME_LOCK` and
   `AITEST_CODEGRAPH_BINARY`.
5. Package-owned ripgrep is prepended to PATH.

## PFC binding

Digital-employee installation is deliberately separate from the local PFC target.

`local-mac.sh bind /absolute/path/to/local/PFC` records only the filesystem root.
It does not persist credentials. Detailed URLs, accounts, APIs, DBs and business
facts are learned/configured later during real local validation.

## Evidence boundary

Source/CI can establish:
- platform contracts,
- unchanged bank packaging,
- shell syntax,
- existing G3/G4 regression preservation,
- native arm64/x64 package assembly and pinned payload identity verification.

Source inspection cannot establish:
- offline package actually runs on the user's Mac,
- OpenCode Web + G2.1 control loop health on that Mac,
- local PFC reachability,
- real test execution/evidence/defect quality.

Those remain runtime validation gates.
