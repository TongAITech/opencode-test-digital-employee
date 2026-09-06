# G1-G5 Local Validation Package Identity Candidate

**Status:** `PACKAGE_IDENTITY_CANDIDATE / 00.9_REVIEW_REQUIRED`  
**WorkItem:** `10.PKG｜G1-G5 Local Validation Runtime & Offline Package Assembly`  
**Phase:** `PKG0.5_CANONICAL_PACKAGE_IDENTITY_RESOLUTION`  
**Repair:** `PKG0.5R_PACKAGE_IDENTITY_CANDIDATE_DRIFT_REPAIR`  
**Governance Authority:** `00.9｜ChatGPT Harness 总控与架构治理｜G5-G6` only  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical source commit / starting commit:** `58e5e1259cd26846b31ea21a8a87df0bcf071edc`  
**Packaging branch:** `work/local-validation-package`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`  
**Package target:** `windows-x64 + Git Bash + offline-first + no-admin-install + no-online-pip/npm/playwright-install`

This record is packaging/governance evidence only. It does not freeze a package identity, modify G1-G5 product semantics, update `runtime-lock.json`, update `PACKAGE_MANIFEST.json`, modify launchers or Agent/Tool source, authorize Windows qualification, authorize PKG1, or authorize package assembly.

---

## 1. PKG0.5 verdict

```text
PKG0_5_CANONICAL_PACKAGE_IDENTITY_RESOLUTION =
BLOCKED_PENDING_WINDOWS_AND_BINARY_IDENTITY_QUALIFICATION

OPENCODE_EVIDENCE_LEDGER = COMPLETE
PRODUCT_SEMANTICS_MODIFIED = NO
RUNTIME_LOCK_MODIFIED = NO
PACKAGE_MANIFEST_MODIFIED = NO
PACKAGING_CONSTRUCTION_STARTED = NO
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
LOCAL_VALIDATION_PACKAGE_ASSEMBLY_READY = NO
G1_G5_REOPEN_REQUIRED = NO
G6 = HOLD
```

The source/evidence recon logic is complete enough to identify the current package authority candidates and remaining gaps. Construction remains blocked because the required Windows OpenCode compatibility qualification and several exact portable payload identities are not yet closed. No product-semantics blocker was found.

This repair also explicitly separates three authority layers:

```text
PROJECT_LOCK_TRUTH
UPSTREAM_IDENTITY_EVIDENCE
LEGACY_OR_PACKAGE_CANDIDATE_EVIDENCE
```

Only values actually present in `runtime-lock.json@58e5e1259cd26846b31ea21a8a87df0bcf071edc` are described below as canonical runtime-lock truth.

---

## 2. Conversation-only identities rejected

00.9 has classified these as non-canonical conversation carry-forward and they are not package authority:

```text
OpenCode 1.18.21 = REJECTED_FROM_CURRENT_PACKAGE_IDENTITY
a17-test-director = REJECTED_FROM_CURRENT_PACKAGE_IDENTITY
```

No `a17-test-director` alias is created or proposed by this record.

---

## 3. Canonical Agent entrypoint resolution

Current Git source proves:

```text
CANONICAL_PRIMARY_AGENT_CANDIDATE = aitest-director
source = workspace-template/.opencode/agents/aitest-director.md
mode = primary

DEFECT_HUNTER_AGENT = aitest-diagnosis
source = workspace-template/.opencode/agents/aitest-diagnosis.md
mode = subagent
router_role = DEFECT_HUNTER

ENTRYPOINT_AGENT_IDENTITY = RESOLVED
```

`workspace-template/.opencode/tools/aitest.ts` exposes the Director, G3 Director, G4 Director and canonical G5 Diagnosis/Defect Hunter tool surfaces. `workspace-template/.opencode/tools/aitest_human_gate.ts` exposes the canonical HumanGate user-turn resume surface.

The G5 CodeContract identifies `agent_name = aitest-diagnosis` for the persisted `DEFECT_HUNTER` router role. `DIAGNOSIS` is compatibility spelling, not a second durable role.

The sentence in `aitest-director.md` that says G5 remains HOLD is stale post-G5 packaging/product-surface wording. It is not used here to reopen G5 and remains classified for later repair only.

---

## 4. OPENCODE_EVIDENCE_LEDGER

| Version / mode / entrypoint | Source | Evidence type | What it proves | Historical/current | Product/package authority |
| --- | --- | --- | --- | --- | --- |
| OpenCode `1.18.3` | `PACKAGE_MANIFEST.json` | legacy package declaration | old R1-R4 package expected 1.18.3 | historical/stale | NO |
| OpenCode `1.18.3` | `packaging/start-pfc-ai-r1r4.sh` | legacy launcher | old package validates 1.18.3 before startup | historical/stale | NO |
| `opencode web` | `workspace-template/pfc-field-validation/pfc_opencode_process.py` | legacy runtime launcher | old R1-R4 sidecar path launches `opencode web`; not `serve` | historical | NO for current G1-G5 |
| OpenCode `1.18.3` user-turn capability | `docs/reviews/OPENCODE_1_18_3_USER_TURN_CAPABILITY_PROBE.md` | historical engineering probe | `chat.message` exists and is invoked; stable supported pre-LLM short-circuit is not proven; Director fallback is valid for HumanGate resume | historically proven | CANDIDATE INPUT ONLY |
| `aitest-director` | `workspace-template/.opencode/agents/aitest-director.md` | current source | primary agent; R1 Event Stream is sole durable runtime truth; Director tool permissions | current source | YES for agent identity candidate |
| `aitest-diagnosis` | `workspace-template/.opencode/agents/aitest-diagnosis.md` | current source | G5 Diagnosis worker is a subagent | current source | YES for Defect Hunter identity |
| G5 Defect Hunter | `docs/governance/G5_DEFECT_TRUTH_AND_AUTONOMOUS_DEFECT_HUNTER_CODE_CONTRACT_CANDIDATE_V2.md` | G5 engineering contract evidence | `DEFECT_HUNTER -> aitest-diagnosis`; DIAGNOSIS alias only | current G5 source | YES for worker identity |
| G1-G5 OpenCode tool surfaces | `workspace-template/.opencode/tools/aitest.ts` | current source | Director/G3/G4/G5 tool bridges exist | current source | YES for qualification scope |
| HumanGate resume surface | `workspace-template/.opencode/tools/aitest_human_gate.ts` | current source | deterministic user-turn resume tool surface exists | current source | YES for qualification scope |
| G5 OpenCode surface validation | `docs/reviews/G5_ENGINEERING_CLOSURE_EVIDENCE.md` + `test_g5_opencode_surface.py` | construction validation | G5 product/OpenCode source surface and Python product-entry seam passed; temporary runtime spine remained R1-truth based | current G5 construction evidence | NOT a Windows OpenCode-binary qualification |
| OpenCode `v1.18.3` Windows x64 | upstream `anomalyco/opencode` release `v1.18.3` | official immutable release | exact Windows x64 standalone asset and release digest exist | upstream candidate | QUALIFICATION CANDIDATE ONLY |
| direct interactive TUI | upstream `packages/opencode/src/cli/cmd/tui.ts@v1.18.3` | upstream source | root `opencode [project]` starts TUI, supports `--agent`; without explicit network args it uses an in-process Worker/internal transport | upstream candidate capability | source-backed capability, not package PASS |
| `.opencode/tools/*.ts` loading | upstream `packages/opencode/src/tool/registry.ts@v1.18.3` | upstream source | custom JS/TS tools are scanned and dynamically imported | upstream candidate capability | source-backed capability |
| compiled standalone runtime | upstream `packages/opencode/script/build.ts@v1.18.3` | upstream build source | Windows x64 OpenCode is Bun-compiled standalone; TUI worker is compiled/embedded | upstream candidate capability | source-backed capability |
| `.opencode` dependency preparation | upstream `packages/opencode/src/config/config.ts@v1.18.3` | upstream source | config loading schedules preparation of matching `@opencode-ai/plugin`; custom tool load waits on dependency preparation | upstream candidate behavior | OFFLINE PACKAGING GAP |
| OpenCode `1.18.21` | no canonical project source evidence found | conversation-only carry-forward | nothing canonical | rejected | NO |
| `a17-test-director` | no canonical project source evidence found | conversation-only carry-forward | nothing canonical | rejected | NO |

No second source-backed OpenCode version candidate was found in the canonical project source. PKG0.5 therefore does not broaden qualification to arbitrary later releases.

---

## 5. OpenCode 1.18.3 qualification candidate identity

The only source-backed version eligible for qualification is currently `1.18.3`.

Official upstream release identity:

```text
OPENCODE_QUALIFICATION_CANDIDATE = 1.18.3
OPENCODE_QUALIFICATION_PLATFORM = windows-x64
OPENCODE_QUALIFICATION_ARTIFACT = opencode-windows-x64.zip
OPENCODE_QUALIFICATION_RELEASE = anomalyco/opencode v1.18.3
OPENCODE_QUALIFICATION_RELEASE_TARGET = c69abee0c73253aebae65e87e4e1b9bfa8c38021
OPENCODE_QUALIFICATION_SHA256 = 68bc62930f6cb5755e0409aa9de0bb270a66ed2b8c9cf0c029e9f2287ed5486e
```

This is the SHA256 of the exact official release archive. It is exact upstream artifact evidence, but it is **not** promoted to canonical package identity by this record because Windows post-G5 compatibility qualification is not complete.

Therefore:

```text
CANONICAL_OPENCODE_VERSION_CANDIDATE = NONE
CANONICAL_OPENCODE_ARTIFACT = NONE
CANONICAL_OPENCODE_SHA256 = NONE
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
```

---

## 6. OpenCode compatibility qualification status

Required post-G5 qualification matrix:

| Check | Result | Evidence boundary |
| --- | --- | --- |
| exact Windows package `opencode --version` | NOT EXECUTED | PKG0.5R is documentation-only and Windows qualification is explicitly out of scope |
| current `workspace-template` loads in exact Windows OpenCode binary | NOT EXECUTED | requires real Windows binary execution |
| primary `aitest-director` discovered by binary | NOT EXECUTED | source identity proven; binary discovery not proven |
| `.opencode/tools/aitest.ts` loads | NOT EXECUTED on target binary | upstream loader capability proven only |
| `aitest_director` callable | NOT EXECUTED on target binary | source/static product seam exists |
| `aitest_g3_director` callable | NOT EXECUTED on target binary | source/static product seam exists |
| `aitest_g4_director` callable | NOT EXECUTED on target binary | source/static product seam exists |
| G5 Diagnosis / Defect Hunter discoverable | NOT EXECUTED on target binary | current source + G5 validation prove surface, not binary loading |
| HumanGate tool discoverable | NOT EXECUTED on target binary | source exists; binary loading not proven |
| real user-turn -> tool invocation surface | NOT EXECUTED on target binary | historical v1.18.3 hook probe exists; post-G5 end-to-end binary qualification not run |

Accordingly:

```text
OPENCODE_COMPATIBILITY_QUALIFICATION = BLOCKED
```

No product incompatibility has been demonstrated. This is an execution-substrate/evidence blocker, not `FAIL`.

---

## 7. Launch mode / sidecar resolution

Three different concepts remain separate:

```text
opencode serve
opencode web
opencode interactive TUI / primary agent entrypoint
```

Evidence:

1. Legacy R1-R4 launcher uses `opencode web`; it does not use `opencode serve`.
2. Upstream v1.18.3 provides a direct interactive TUI as the root command and supports `--agent`.
3. With no explicit `--port`, `--hostname` or mDNS network flags, the v1.18.3 TUI uses an internal Worker and `http://opencode.internal` transport rather than requiring an externally launched web/serve process.

Fail-closed result retained:

```text
OPENCODE_SERVE_REQUIRED = NO
DIRECT_INTERACTIVE_ENTRYPOINT_SUPPORTED = YES
OPENCODE_WEB_REQUIRED = UNRESOLVED
OPENCODE_SIDECAR_REQUIRED = UNRESOLVED
```

The last two remain unresolved because the current G1-G5 Windows package compatibility matrix has not been executed. Legacy `opencode web` is not allowed to become current package authority merely because it exists, and conversation-only claims that all sidecars are unnecessary are likewise rejected.

---

## 8. Separate Node runtime decision

Current evidence does not require a separately packaged `node.exe`:

- OpenCode v1.18.3 Windows x64 is produced as a Bun-compiled standalone executable.
- OpenCode's custom-tool registry imports `.opencode/tools/*.ts` through its own runtime path.
- The controlled browser implementation in canonical G1-G5 source uses Python Playwright CDP (`playwright.sync_api`) rather than a separately launched Node runtime.

Therefore:

```text
SEPARATE_NODE_RUNTIME_REQUIRED = NO
```

This does **not** mean the offline dependency closure is complete. OpenCode v1.18.3 config loading schedules installation/preparation of a matching `@opencode-ai/plugin` dependency for `.opencode` directories, and custom tool loading waits for those dependencies. An offline package must pre-provision or otherwise deterministically satisfy this dependency without target-host online npm access.

```text
OPENCODE_PLUGIN_OFFLINE_DEPENDENCY_PAYLOAD_GAP = OPEN
```

The Python browser path also requires the Python Playwright package/driver support to be pre-provisioned in portable Python; target-host `playwright install`, pip or npm is forbidden.

```text
PLAYWRIGHT_PYTHON_OFFLINE_DEPENDENCY_CLOSURE_GAP = OPEN
```

---

## 9. Portable binary identity resolution and authority separation

### 9.1 Python

#### PROJECT_LOCK_TRUTH

Direct authority: `runtime-lock.json@58e5e1259cd26846b31ea21a8a87df0bcf071edc`.

```text
role = PORTABLE_RUNTIME
version = 3.12.10
platform = windows-x64
relative_target = workspace-template/runtime/python/python.exe
status = PINNED_VERSION_FROM_CURRENT_CONSTRUCTION
sha256 = TO_BE_PINNED_FROM_CANONICAL_PAYLOAD_REGISTRY
```

The canonical runtime lock does **not** select an exact `python-build-standalone` release snapshot/build artifact.

#### UPSTREAM_IDENTITY_EVIDENCE / PACKAGE_IDENTITY_CANDIDATE

```text
provenance_family_candidate = python-build-standalone
exact_upstream_artifact = UNRESOLVED
exact_snapshot = UNRESOLVED
sha256 = UNRESOLVED
freeze_authority = 00.9_REQUIRED
```

Therefore:

```text
PORTABLE_PYTHON_IDENTITY =
3.12.10 / windows-x64 /
CANONICAL_TARGET=workspace-template/runtime/python/python.exe /
EXACT_UPSTREAM_ARTIFACT=UNRESOLVED /
SHA256=UNRESOLVED
```

### 9.2 Chromium

#### PROJECT_LOCK_TRUTH

Direct authority: `runtime-lock.json@58e5e1259cd26846b31ea21a8a87df0bcf071edc`.

```text
role = CONTROLLED_BROWSER
version = 151.0.7922.34
platform = windows-x64
relative_target = workspace-template/runtime/browser/chrome-win64/chrome.exe
status = PINNED_VERSION_FROM_CURRENT_CONSTRUCTION
sha256 = TO_BE_PINNED_FROM_CANONICAL_PAYLOAD_REGISTRY
```

#### UPSTREAM_IDENTITY_EVIDENCE / PACKAGE_IDENTITY_CANDIDATE

GoogleChromeLabs Chrome-for-Testing data contains `151.0.7922.34` at revision `1654411`. The following are upstream identity evidence, **not** current runtime-lock fields:

```text
upstream_provider_candidate = Chrome-for-Testing
upstream_artifact_candidate = chrome-win64.zip
upstream_revision_evidence = 1654411
archive_sha256 = UNRESOLVED
freeze_authority = 00.9_REQUIRED
```

Therefore:

```text
PORTABLE_CHROMIUM_IDENTITY =
151.0.7922.34 / windows-x64 /
CANONICAL_TARGET=workspace-template/runtime/browser/chrome-win64/chrome.exe /
UPSTREAM_PROVIDER_EVIDENCE=Chrome-for-Testing /
UPSTREAM_ARTIFACT_EVIDENCE=chrome-win64.zip /
REVISION_EVIDENCE=1654411 /
SHA256=UNRESOLVED
```

No later/current Chrome version may replace the canonical lock version without governance authorization.

### 9.3 CodeGraph

#### PROJECT_LOCK_TRUTH

Direct authority: `runtime-lock.json@58e5e1259cd26846b31ea21a8a87df0bcf071edc`.

```text
role = STRUCTURAL_CODE_INTELLIGENCE
provider = codegraph-ai/CodeGraph
version = 0.20.1
platform = windows-x64
relative_target = workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe
release_asset = codegraph-server-win32-x64.exe
sha256 = aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1
```

Official upstream `v0.20.1` release metadata confirms the exact executable digest above. There is no CodeGraph executable identity conflict.

#### OFFICIAL_RELEASE_COMPANION_EVIDENCE

The same official Windows release states that `onnxruntime.dll` is additionally required beside the executable. Its exact official release identity is:

```text
artifact = onnxruntime.dll
sha256 = 52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948
authority = OFFICIAL_RELEASE_COMPANION_EVIDENCE
runtime_lock_currently_contains_companion = NO
representation_status = PKG1_RUNTIME_LOCK_REPRESENTATION_REQUIRED
```

This companion evidence does not mean the current lock already contains `onnxruntime.dll`, and PKG0.5R does not authorize editing the lock.

Therefore:

```text
PORTABLE_CODEGRAPH_IDENTITY =
0.20.1 /
CANONICAL_TARGET=workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe /
ARTIFACT=codegraph-server-win32-x64.exe /
SHA256=aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1 /
OFFICIAL_RELEASE_MATCH=YES /
COMPANION_EVIDENCE=onnxruntime.dll@52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948 /
COMPANION_LOCK_STATUS=PKG1_RUNTIME_LOCK_REPRESENTATION_REQUIRED
```

### 9.4 ripgrep

#### PROJECT_LOCK_TRUTH

Direct authority: `runtime-lock.json@58e5e1259cd26846b31ea21a8a87df0bcf071edc`.

The canonical runtime lock currently freezes only:

```text
role = REFERENCE_SEARCH_ENRICHMENT
platform = windows-x64
status = CAPABILITY_REQUIRED_WHERE_AVAILABLE_VERSION_NOT_YET_PINNED
sha256 = TO_BE_PINNED_FROM_CANONICAL_PAYLOAD_REGISTRY
```

It does **not** currently freeze provider, version, artifact, or relative target.

#### UPSTREAM / LEGACY / PACKAGE CANDIDATE EVIDENCE

Any references to `BurntSushi/ripgrep`, a Windows executable location, or an artifact naming family are not canonical runtime-lock truth in the current source. If retained for later resolution, they have only the following authority:

```text
UPSTREAM_PROVIDER_CANDIDATE = BurntSushi/ripgrep
LEGACY_PACKAGE_TARGET_EVIDENCE = historical/package evidence only
PACKAGE_IDENTITY_CANDIDATE = requires independent resolution
VERSION = UNRESOLVED
ARTIFACT = UNRESOLVED
RELATIVE_TARGET = UNRESOLVED
SHA256 = UNRESOLVED
FREEZE_AUTHORITY = 00.9_REQUIRED
```

Therefore:

```text
PORTABLE_RIPGREP_IDENTITY =
ROLE=REFERENCE_SEARCH_ENRICHMENT /
PLATFORM=windows-x64 /
VERSION=UNRESOLVED /
ARTIFACT=UNRESOLVED /
RELATIVE_TARGET=UNRESOLVED /
SHA256=UNRESOLVED
```

`RIPGREP_LOCK_AUTHORITY_OVERCLAIM = REMOVED`.

---

## 10. Binary identity gaps remaining

The existing blocker list is retained unchanged:

```text
BINARY_IDENTITY_GAPS_REMAINING = [
  OPENCODE_WINDOWS_POST_G5_COMPATIBILITY_QUALIFICATION,
  OPENCODE_PLUGIN_OFFLINE_DEPENDENCY_PAYLOAD,
  PYTHON_BUILD_STANDALONE_EXACT_SNAPSHOT_AND_SHA256,
  CHROMIUM_151_0_7922_34_ARCHIVE_SHA256,
  RIPGREP_VERSION_ARTIFACT_AND_SHA256,
  CODEGRAPH_ONNXRUNTIME_DLL_RUNTIME_LOCK_REPRESENTATION,
  PLAYWRIGHT_PYTHON_OFFLINE_DEPENDENCY_CLOSURE
]
```

```text
BINARY_IDENTITY_CONFLICT = NO
```

For CodeGraph, the official executable digest matches the 00.9-corrected canonical runtime-lock digest. The companion-DLL representation gap remains open.

---

## 11. Legacy packaging supersession plan

This is classification only. PKG0.5R does not modify or delete these files.

| Surface | Disposition | Reason |
| --- | --- | --- |
| `PACKAGE_MANIFEST.json` | `REPAIR` | retain manifest concept, but source identity, G5 gate state and runtime metadata are stale |
| `packaging/INSTALL-PFC-AITEST.sh` | `SUPERSEDE` for G1-G5 local-validation package; `RETAIN_AS_HISTORY` | PFC/R1-R4 installer is not current single-entry G1-G5 package authority |
| `packaging/start-pfc-ai-r1r4.sh` | `SUPERSEDE` for G1-G5 local-validation package; `RETAIN_AS_HISTORY` | hardcoded legacy package/version and web-oriented start path |
| `packaging/status-pfc-ai-r1r4.sh` | `SUPERSEDE` for G1-G5 local-validation package; `RETAIN_AS_HISTORY` | legacy runtime/process identity |
| `packaging/stop-pfc-ai-r1r4.sh` | `SUPERSEDE` for G1-G5 local-validation package; `RETAIN_AS_HISTORY` | legacy runtime/process identity |
| `workspace-template/pfc-field-validation/pfc_opencode_process.py` | `RETAIN_AS_HISTORY` / not current package authority | proves historic `opencode web` process path only |
| `workspace-template/.opencode/agents/aitest-director.md` | `STILL_REQUIRED` + stale G5-HOLD wording `REPAIR` candidate | current primary agent is required; stale closure wording must not drive package truth |
| `workspace-template/.opencode/agents/aitest-diagnosis.md` | `STILL_REQUIRED` | canonical G5 Defect Hunter worker |
| `workspace-template/.opencode/tools/aitest.ts` | `STILL_REQUIRED` | current Director/G3/G4/G5 product tool surfaces |
| `workspace-template/.opencode/tools/aitest_human_gate.ts` | `STILL_REQUIRED` | current HumanGate user-turn tool surface |

No wholesale deletion of legacy packaging is authorized.

---

## 12. PKG1 preconditions produced by this candidate

Before `PKG1_PACKAGING_CANONICALIZATION` can be authorized, 00.9 must independently review this candidate and explicitly decide how to close at least:

1. real Windows x64 OpenCode 1.18.3 post-G5 compatibility qualification;
2. offline `@opencode-ai/plugin` dependency provisioning for current `.opencode` custom tools;
3. exact Python 3.12.10 standalone build snapshot/hash;
4. Chromium 151.0.7922.34 exact archive hash;
5. ripgrep exact version/artifact/relative-target/hash;
6. CodeGraph `onnxruntime.dll` representation in the package/runtime lock;
7. portable Python Playwright dependency/driver offline closure.

Only after successful OpenCode compatibility qualification may the 1.18.3 qualification identity be promoted to:

```text
CANONICAL_OPENCODE_VERSION_CANDIDATE
CANONICAL_OPENCODE_ARTIFACT
CANONICAL_OPENCODE_SHA256
```

This record intentionally does not perform that promotion.

---

## 13. PKG0.5R repair result and final boundary

```text
PKG0_5R_PACKAGE_IDENTITY_CANDIDATE_DRIFT_REPAIR =
ENGINEERING_PASS_CANDIDATE

PROJECT_LOCK_VS_UPSTREAM_EVIDENCE = EXPLICITLY_SEPARATED
RIPGREP_LOCK_AUTHORITY_OVERCLAIM = REMOVED

CHROMIUM_CANONICAL_TARGET =
workspace-template/runtime/browser/chrome-win64/chrome.exe

CODEGRAPH_CANONICAL_TARGET =
workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe

OPENCODE_1_18_3_QUALIFICATION_CANDIDATE = UNCHANGED
OPENCODE_COMPATIBILITY_QUALIFICATION = BLOCKED

BRANCH = work/local-validation-package
STARTING_COMMIT = 58e5e1259cd26846b31ea21a8a87df0bcf071edc
MAIN_MODIFIED = NO
PRODUCT_SEMANTICS_MODIFIED = NO
PRODUCT_SOURCE_MODIFIED = NO
RUNTIME_LOCK_MODIFIED = NO
PACKAGE_MANIFEST_MODIFIED = NO
LAUNCHER_MODIFIED = NO
OPENCODE_AGENT_OR_TOOL_MODIFIED = NO
PACKAGING_CONSTRUCTION_STARTED = NO
WINDOWS_QUALIFICATION_STARTED = NO
ZIP_ASSEMBLY_STARTED = NO
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
PKG1 = HOLD
LOCAL_VALIDATION_PACKAGE_ASSEMBLY_READY = NO
G1_G5_REOPEN_REQUIRED = NO
G6 = HOLD
```

**STOP after this documentation/evidence-only repair and return to 00.9 for independent re-review.**
