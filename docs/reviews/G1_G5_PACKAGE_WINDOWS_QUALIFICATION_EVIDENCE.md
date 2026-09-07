# G1-G5 Package Windows Qualification Evidence

WorkItem: `10.PKG.4 | PKG0.6B1R | QUALIFICATION_RUNNER_REPAIR_AND_RERUN`  
Evidence recorded: 2026-09-07, after repaired run `34079065820` completed.  
Disposition: `PKG0_6B1R_WINDOWS_QUALIFICATION_RUNNER_REPAIR=PASS`; `PKG0_6B1=PASS_CANDIDATE`; return to `00.9` for independent Review. This document is not a package identity freeze or authorization for B2/PKG1.

## 1. Exact Git recovery and scope

```makefile
CANONICAL_REPOSITORY = TongAITech/opencode-test-digital-employee
CANONICAL_MAIN = 58e5e1259cd26846b31ea21a8a87df0bcf071edc
EXPECTED_REMOTE_HEAD_AT_RECOVERY = b2556de9a3a0dfc3e3028fb168284688ef3a24fc
ACTUAL_REMOTE_HEAD_AT_RECOVERY = b2556de9a3a0dfc3e3028fb168284688ef3a24fc
BRANCH_DIVERGENCE = NONE
ACTIVE_BRANCH = work/local-validation-package
DEPENDENCY_CANDIDATE_HEAD = de326fa4b35186a6acbdfc2bf8ed98549b2130c2
B1R_TOOLING_COMMIT = 9a52e33204c51f8e5f15ea8b6c2c60d533103d95
REPAIR_PARENT = b2556de9a3a0dfc3e3028fb168284688ef3a24fc
REPAIR_TREE = 24bfd1d57abe334628d0b579f30f40f751702fae
REMOTE_HEAD_AFTER_REPAIR_PUSH = 9a52e33204c51f8e5f15ea8b6c2c60d533103d95
MAIN_AFTER_REPAIR_AND_RUN = 58e5e1259cd26846b31ea21a8a87df0bcf071edc
```

The starting commit message and parent were independently fetched from Git: `test(pkg): add Windows package qualification runner`, parent `de326fa4b35186a6acbdfc2bf8ed98549b2130c2`. The repair commit message is `test(pkg): repair Windows qualification runner`. The active branch was checked again immediately before its non-forced fast-forward update and again after the run; no divergence was found.

The repair diff against the authorized starting head has exactly two files:

| Path | Additions | Deletions | Purpose |
|---|---:|---:|---|
| `tools/package_windows_qualification.ps1` | 211 | 29 | ExpectedSize fix, dependency-aware qualification, Chromium carry-forward assertions, runner self-tests and result provenance |
| `.github/workflows/g1-g5-package-windows-qualification.yml` | 52 | 1 | Authorized exact-ref cleanup job, ordering and fail-closed result enforcement |

No changes in this WorkItem to `runtime-lock.json`, `PACKAGE_MANIFEST.json`, product launcher, Agent, Tool, G1-G5 product source, dependency selections, or `main`. This evidence document is a separate, subsequent documentation-only change. The Windows execution authority is the repair commit, not the later documentation commit. PKG0 through PKG0.6A.1 were not repeated.

## 2. Two runs, distinct authority

| Field | First diagnostic run | Fresh repaired run |
|---|---|---|
| Run ID | `34075744762` | `34079065820` |
| Windows job ID | `101601356906` | `101610757980` |
| Executed commit | `b2556de9a3a0dfc3e3028fb168284688ef3a24fc` | `9a52e33204c51f8e5f15ea8b6c2c60d533103d95` |
| Workflow conclusion | `failure` | `success` |
| Structured gate result | `FAIL` as originally emitted by defective runner | `PASS_CANDIDATE` |
| Authority | `DIAGNOSTIC_EVIDENCE_VALID / NOT_FINAL_QUALIFICATION` | Formal B1 qualification evidence, subject to 00.9 independent Review |
| Classification | `QUALIFICATION_RUNNER_DEFECT` | Fresh qualification on repaired tooling |

The new run was triggered by `push`, attempt `1`, on `work/local-validation-package`. It started at `2026-09-07T03:15:53Z`; the completed/success run metadata was updated at `2026-09-07T03:18:45Z`. All Windows job steps, including artifact upload and conclusion enforcement, completed successfully. This is a new run ID on the repair commit, not a re-run of the old commit.

The original failure and original JSON have not been erased or rewritten. Per the supplied 00.9 independent-review disposition, neither product compatibility failure nor package candidate failure was established by that first run. No product repair or dependency reselection was authorized or performed.

## 3. Root cause and narrow repair

### 3.1 ExpectedSize semantics

The original `Download-Exact` used `[Nullable[long]]$ExpectedSize` and accessed `$ExpectedSize.Value`. On the first real Windows run, supplied sizes were boxed as Int64 and `.Value` raised `The property 'Value' cannot be found on this object.` after download, SHA256 computation and expected-SHA comparison. Five identity/closure checks emitted this runner exception; downstream work then consumed incomplete acquisition or staging.

The repaired downloader uses `[long]$ExpectedSize = 0`, captures `$PSBoundParameters.ContainsKey("ExpectedSize")`, and compares the measured Int64 length directly against `[long]$ExpectedSize`. Omitted size does not assert size; supplied size, including zero, requires exact equality. SHA256 mismatch and genuine size mismatch remain failures. There is no remaining `$ExpectedSize.Value` access in the repaired source.

### 3.2 Dependency-aware result semantics

An explicit prerequisite graph is evaluated before each dependent check body. A missing or non-PASS prerequisite yields `BLOCKED_BY_UPSTREAM_QUALIFICATION`, naming the prerequisite status and recording `check_body=NOT_EXECUTED` and `downstream_product_failure=NOT_ESTABLISHED`. Upstream FAIL or execution-substrate BLOCKED is retained, not hidden.

Playwright materialization depends on portable Python execution and the full wheel closure; import depends on materialization; CDP depends on import and qualified Chromium. CodeGraph execution depends on both exact payload identities. Workspace staging depends on complete qualified runtime payloads and plugin pre-provisioning. OpenCode workspace/agent/tool and target-style plugin checks cannot run against a failed or partial workspace stage. The tool probe uses the same prerequisite guard.

Any `FAIL` keeps the aggregate gate at `FAIL`; any `BLOCKED_*` prevents a green result. A Chromium SHA256, size or exact executable-version conflict records `CHROMIUM_ARTIFACT_IDENTITY_CONFLICT`, blocks subsequent qualification bodies, and preserves a structured diagnostic result. This changes qualification tooling, not product semantics.

### 3.3 Actual Windows runner self-tests

The fresh Windows result reports `QUALIFICATION_RUNNER_SELF_TEST=PASS`, with 22 cases:

| Group | Cases | Actual behavior tested |
|---|---:|---|
| Downloader and identity | 7 | Omitted size, exact size, mismatch, supplied zero mismatch, Int64 value above 32-bit range, empty file with exact zero, SHA mismatch |
| Dependency/STOP blocked bodies | 11 | Playwright cascade, CodeGraph and workspace cascade, missing prerequisite, global Chromium STOP |
| Positive execution | 1 | A body executes when all prerequisites pass |
| Aggregate gate | 3 | BLOCKED is not green; root FAIL remains FAIL; allowed B2 defer/not-executed semantics remain distinct |

Downloader tests exercised the actual `Download-Exact` function on Windows with local file-URI fixtures. Injected prerequisite failures used isolated check dictionaries, were restored in `finally`, and were logged under `RUNNER_SELFTEST_CHECK`, not inserted as actual product results. No local Linux execution is presented as Windows proof.

## 4. Fresh complete qualification matrix

The downloaded JSON contains exactly the following 24 PASS checks and one explicitly non-executed B2 check. There are no real-matrix FAIL, BLOCKED or DEFERRED statuses. The count includes Git identity and runner self-tests; it is not a claim of 24 product end-to-end tests.

| Check | Fresh status | Observation |
|---|---|---|
| `GIT_WORKFLOW_IDENTITY` | PASS | Correct repair SHA, parent, branch and frozen main |
| `QUALIFICATION_RUNNER_SELF_TEST` | PASS | 22/22 cases |
| `OPENCODE_ARCHIVE_IDENTITY` | PASS | Exact candidate SHA256 and size |
| `PYTHON_ARCHIVE_IDENTITY` | PASS | Exact candidate SHA256 and size |
| `CHROMIUM_ARCHIVE_DOWNLOAD_AND_MEASURE` | PASS | Exact carry-forward SHA256 and size |
| `RIPGREP_ARCHIVE_IDENTITY` | PASS | Exact candidate SHA256 and size |
| `CODEGRAPH_BINARY_IDENTITY` | PASS | Both executable and onnxruntime.dll identities; co-located |
| `PYTHON_ARCHIVE_EXTRACT` | PASS | Candidate portable python.exe materialized |
| `PYTHON_WINDOWS_EXECUTION` | PASS | 3.12.10; absolute candidate sys.executable; system fallback NO |
| `PYTHON_VC_RUNTIME_REALITY` | PASS | APPLICATION_LOCAL_PRESENT(2/2) |
| `PLAYWRIGHT_WHEEL_CLOSURE_DOWNLOAD` | PASS | All four exact wheels acquired and verified |
| `PLAYWRIGHT_OFFLINE_MATERIALIZATION` | PASS | Verified-wheel direct extraction; pip NOT_USED |
| `PLAYWRIGHT_WINDOWS_IMPORT` | PASS | Portable Python import and bundled driver/Node payload; exact four-package versions |
| `CHROMIUM_ARCHIVE_EXTRACT_AND_VERSION` | PASS | Measured executable version 151.0.7922.34, exact match |
| `PLAYWRIGHT_CDP_EXTERNAL_CHROMIUM` | PASS | External Chromium CDP endpoint and connect_over_cdp; managed browser download NO |
| `RIPGREP_WINDOWS_EXECUTION` | PASS | 15.2.0; actual search; absolute candidate rg.exe; system fallback NO |
| `CODEGRAPH_WINDOWS_EXECUTION` | PASS | Executable plus DLL co-located; process start and --info; version 0.20.1 |
| `OPENCODE_VERSION` | PASS | Candidate executable 1.18.3 |
| `OPENCODE_PLUGIN_RELEASE_BUILD_MATERIALIZATION` | PASS | Plugin 1.18.3 package-lock and node_modules on CI release-build substrate |
| `OPENCODE_QUALIFICATION_WORKSPACE_STAGE` | PASS | Complete temporary post-install-style workspace, not a final package |
| `OPENCODE_WORKSPACE_LOAD` | PASS | debug config; default agent aitest-director |
| `OPENCODE_AGENT_DISCOVERY` | PASS | aitest-director and aitest-diagnosis discovered |
| `OPENCODE_TOOL_LOAD` | PASS | ToolRegistry exposes aitest_director and aitest_human_gate_resume without an LLM turn |
| `OPENCODE_PLUGIN_OFFLINE_LAYOUT` | PASS | Pre-provisioned plugin layout; dead-proxy target-style probes; lock/count unchanged |
| `WINDOWS_INTERACTIVE_QUALIFICATION` | NOT_EXECUTED | PKG0.6B2 only |

The plugin release-build package-lock SHA256 is `86f13676e5634fd2593172a8b09849eef46b850abe56919eb832267dabbc9f9e`, with 3667 node_modules files. The target-style probe checked stable lock hash and file count. This proves the stated layout/probe checks, not total network isolation or an interactive target-host installation. The CI host also has system VC runtime DLLs; application-local presence 2/2 is an observation, not a claim of clean-host isolation.

## 5. Artifact identities remeasured without reselection

All hashes below are SHA256 and all sizes are bytes. Existing expected identities were retained. Chromium expectations are carried forward from run 34075744762 and were measured afresh.

| Artifact | Fresh size | Fresh SHA256 |
|---|---:|---|
| OpenCode 1.18.3 Windows x64 ZIP | 59152536 | `68bc62930f6cb5755e0409aa9de0bb270a66ed2b8c9cf0c029e9f2287ed5486e` |
| CPython 3.12.10 Windows standalone archive | 21172386 | `ca22a9a9e64ecab6d0b5de7cdf8b679ccaa41e9def6aaa2b4aaa6bb23ec7aaba` |
| Chromium 151.0.7922.34 win64 ZIP | 201068834 | `045621e45a9dd27002c7fc1d8e10fe9f5f71f4cadbf44ec6f397f56f0179725c` |
| ripgrep 15.2.0 Windows MSVC ZIP | 1789611 | `71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5` |
| CodeGraph 0.20.1 win32-x64 executable | 105874432 | `aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1` |
| CodeGraph onnxruntime.dll | 11567648 | `52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948` |
| playwright-1.62.0-py3-none-win_amd64.whl | 38164458 | `92c0d98ed04eb35af557b709875edba415b1f548bdb22ddb5bb3e1e6c835c2f1` |
| pyee-13.0.1-py3-none-any.whl | 15659 | `af2f8fede4171ef667dfded53f96e2ed0d6e6bd7ee3bb46437f77e3b57689228` |
| typing_extensions-4.16.0-py3-none-any.whl | 45571 | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` |
| greenlet-3.5.5-cp312-cp312-win_amd64.whl | 324171 | `49ddacd36af37735fab103846f4ee4d18a492dde72730d1699c0c8ebe30d9f18` |

```makefile
CHROMIUM_ARCHIVE_SHA256 = 045621e45a9dd27002c7fc1d8e10fe9f5f71f4cadbf44ec6f397f56f0179725c
CHROMIUM_ARCHIVE_SIZE = 201068834
CHROMIUM_EXE_VERSION = 151.0.7922.34
CHROMIUM_CARRY_FORWARD_IDENTITY = EXACT_MATCH
CHROMIUM_ARTIFACT_IDENTITY_CONFLICT = NOT_OBSERVED
```

## 6. First-run observations retained and reconfirmed

The first run did prove the Chromium archive measurement and executable version, portable Python 3.12.10 execution with no system-Python fallback, application-local VC runtime presence 2/2, ripgrep 15.2.0 real search with no system-rg fallback, and OpenCode 1.18.3 workspace/agent/tool observations. Those nine original named PASS checks remain in the unmodified first-run JSON and each has a fresh PASS counterpart.

The first run did not establish a complete Playwright closure, CodeGraph executable-plus-DLL closure, successful workspace staging, or the final plugin layout proof. Its downstream cascade statuses must not be reinterpreted as independent product defects. The repaired run executes those checks with complete verified prerequisites and supplies new evidence rather than rewriting the historical result.

## 7. Raw evidence identity and audit

Both GitHub artifact ZIPs were downloaded. Their measured ZIP digests match the artifact metadata digests. Each original `qualification-result.json` was extracted byte-for-byte and hashed before parsing.

| Evidence | Artifact ID | ZIP bytes | ZIP SHA256 |
|---|---|---:|---|
| First diagnostic run | `10002002938` | 7746 | `1838e644188cd2ae58c3f5281e366207f59ade03603fabf14501a5b48eec4433` |
| Fresh repaired run | `10003110574` | 9754 | `d6772dedd9a95cdf18e3b1540aecd90dbc29c0d0cdaddd6f30cc6d1f06b65e8e` |

| Raw JSON | Bytes | SHA256 |
|---|---:|---|
| First `qualification-result.json` | 147623 | `f791553180d481afe4fa3d67d843ba44658ac89ce633d20da31d16cbe97866a8` |
| Fresh `qualification-result.json` | 154973 | `a8665d5a273b73e546c21e7ed10c277fdfde17d31dd5523b12b05be29b79196e` |

A separate read-only artifact audit checked exact run/commit/branch/Windows identities, a fixed expected 24-check set, each prerequisite's PASS status, all six archive/binary identities, all four exact wheels, Chromium equality across both runs, preservation of the nine first-run observations, 22 runner self-test cases, absence of injected failures from the real matrix, and B2 remaining NOT_EXECUTED. Result: `INDEPENDENT_RESULT_AUDIT=PASS`. This is the WorkItem's independent raw-result check, not a substitute for the requested 00.9 governance Review.

GitHub raw evidence references:

- [First diagnostic run](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/34075744762)
- [Fresh repaired run](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/34079065820)
- [Executed repair commit](https://github.com/TongAITech/opencode-test-digital-employee/commit/9a52e33204c51f8e5f15ea8b6c2c60d533103d95)
- [Repair-only comparison](https://github.com/TongAITech/opencode-test-digital-employee/compare/b2556de9a3a0dfc3e3028fb168284688ef3a24fc...9a52e33204c51f8e5f15ea8b6c2c60d533103d95)
- [First artifact metadata](https://api.github.com/repos/TongAITech/opencode-test-digital-employee/actions/artifacts/10002002938)
- [Fresh artifact metadata](https://api.github.com/repos/TongAITech/opencode-test-digital-employee/actions/artifacts/10003110574)

Artifacts retain the workflow's 30-day retention setting. This document preserves identities and findings; it does not claim indefinite availability of GitHub artifacts.

## 8. Authorized temporary-ref cleanup

Cleanup job `101610723780` in the fresh run completed successfully. Before any deletion, both connector reads and the job checked all four refs against the exact approved SHA. Exact equality to the shared dependency-candidate commit means there were no independent commits on those ref tips to preserve.

| Remote ref | Exact SHA before deletion | Remote state after deletion |
|---|---|---|
| `refs/heads/tmp-b1-should-not-exist` | `de326fa4b35186a6acbdfc2bf8ed98549b2130c2` | ABSENT |
| `refs/heads/tmp-do-not-use-2` | `de326fa4b35186a6acbdfc2bf8ed98549b2130c2` | ABSENT |
| `refs/heads/tmp-do-not-use-3` | `de326fa4b35186a6acbdfc2bf8ed98549b2130c2` | ABSENT |
| `refs/heads/tmp-do-not-use-4` | `de326fa4b35186a6acbdfc2bf8ed98549b2130c2` | ABSENT |

The workflow used one atomic push with per-ref exact-SHA leases and only those four deletion refspecs. Live identity checks preceded the deletion at approximately `2026-09-07T03:16:02Z`; all four absent states and `TEMP_REFS_CLEANUP=PASS` were confirmed by `03:16:03.9414773Z`. A separate post-job GitHub `git/matching-refs/heads/tmp-` read returned `[]`. The cleanup job alone had contents-write permission; the Windows qualification job remained read-only. No replacement temporary ref was created. Cleanup is not a product/package source change.

## 9. Final disposition and boundaries

```makefile
PKG0_6B1R_WINDOWS_QUALIFICATION_RUNNER_REPAIR = PASS
STARTING_HEAD = b2556de9a3a0dfc3e3028fb168284688ef3a24fc
REPAIR_COMMIT = 9a52e33204c51f8e5f15ea8b6c2c60d533103d95
FIRST_RUN = 34075744762
FIRST_RUN_CLASSIFICATION = QUALIFICATION_RUNNER_DEFECT
REPAIR_RUN = 34079065820
REPAIR_RUN_CONCLUSION = success
PYTHON_ARCHIVE_IDENTITY = PASS
PYTHON_WINDOWS_EXECUTION = PASS
PYTHON_VC_RUNTIME_REALITY = APPLICATION_LOCAL_PRESENT(2/2)
PLAYWRIGHT_WHEEL_CLOSURE = PASS
PLAYWRIGHT_WINDOWS_IMPORT = PASS
PLAYWRIGHT_CDP_EXTERNAL_CHROMIUM = PASS
RIPGREP_ARCHIVE_IDENTITY = PASS
RIPGREP_WINDOWS_EXECUTION = PASS
CODEGRAPH_BINARY_IDENTITY = PASS
CODEGRAPH_WINDOWS_EXECUTION = PASS
OPENCODE_ARCHIVE_IDENTITY = PASS
OPENCODE_VERSION = 1.18.3
OPENCODE_WORKSPACE_LOAD = PASS
OPENCODE_AGENT_DISCOVERY = PASS
OPENCODE_TOOL_LOAD = PASS
OPENCODE_PLUGIN_OFFLINE_LAYOUT = PASS
WINDOWS_INTERACTIVE_QUALIFICATION = NOT_EXECUTED / PKG0.6B2
TEMP_REFS_CLEANUP = PASS
PKG0_6B1 = PASS_CANDIDATE
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
PKG0_6B2 = HOLD
PKG1 = HOLD
LOCAL_VALIDATION = HOLD
G1_G5_REOPEN_REQUIRED = NO
G6 = HOLD
NEXT_GATE = 00.9_INDEPENDENT_REVIEW
```

Remaining baseline gaps are unchanged: CodeGraph onnxruntime DLL representation in the final runtime lock, final offline plugin materialization, and interactive OpenCode web/sidecar requirements. Their existing `PKG1_REQUIRED` / `UNRESOLVED_B2` labels are not execution authorization. No target-host interactive launch, provider/model interaction, bank field validation, package identity freeze, PKG1 assembly, G1-G5 reopening, or G6 work was performed or implied.

STOP. Return to 00.9 independent Review.
