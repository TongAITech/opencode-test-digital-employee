# G1-G5 Package Dependency Selection Evidence

**Status:** `PKG0.6A.1 / PASS_CANDIDATE / 00.9_REVIEW_REQUIRED`  
**WorkItem:** `10.PKG｜G1-G5 Local Validation Runtime & Offline Package Assembly`  
**Gate:** `PKG0.6A.1｜Package-only Dependency Selection & Exact Artifact Closure`  
**Governance Authority:** `00.9｜ChatGPT Harness 总控与架构治理｜G5-G6` only  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical main:** `58e5e1259cd26846b31ea21a8a87df0bcf071edc`  
**Active branch:** `work/local-validation-package`  
**Authorized starting head:** `fdfc28fbae73dbc4c2bba34ef9a0aa5b0783cafe`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`

This record is documentation/evidence only. It does not modify `runtime-lock.json`, `PACKAGE_MANIFEST.json`, any launcher, Agent, Tool, G1-G5 product source, canonical `main`, or any runtime payload. It does not assemble a package or ZIP and it does not execute PKG0.6B, PKG1, Local Validation, or G6.

The new authority used by this gate is intentionally narrow:

```text
PACKAGE_ONLY_DEPENDENCY_SELECTION = AUTHORIZED
```

The following distinctions remain mandatory:

```text
PACKAGE_SELECTION_CANDIDATE
!=
PACKAGE_IDENTITY_FROZEN

ARTIFACT_IDENTITY_PASS
!=
WINDOWS_COMPATIBILITY_PASS
```

---

## 1. Gate boundary and result

Authorized unresolved non-Windows package identity scope:

```text
PYTHON_BUILD_STANDALONE_EXACT_SNAPSHOT_AND_SHA256
CHROMIUM_151_0_7922_34_ARCHIVE_SHA256
RIPGREP_VERSION_ARTIFACT_AND_SHA256
PLAYWRIGHT_PYTHON_OFFLINE_DEPENDENCY_CLOSURE
```

Explicitly out of scope:

```text
OPENCODE_WINDOWS_POST_G5_COMPATIBILITY_QUALIFICATION
WINDOWS_PRODUCT_EXECUTION
FINAL_PACKAGE_ASSEMBLY
ZIP_BUILD
PKG1
LOCAL_VALIDATION
G6
```

Gate result:

```text
PKG0_6A_1_PACKAGE_DEPENDENCY_SELECTION = PASS_CANDIDATE
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
WINDOWS_COMPATIBILITY_EXECUTED = NO
```

Why `PASS_CANDIDATE` is allowed:

1. Python now has an exact package-only candidate with version/snapshot/artifact/size/SHA256/layout identity.
2. ripgrep now has an exact package-only stable-release candidate with tag/artifact/size/SHA256/layout identity.
3. Playwright Python now has an exact package-only candidate and deterministic Python dependency/driver closure.
4. Chromium remains the exact already-authorized version and artifact; the only remaining Chromium identity fact is its archive SHA256/size inspection, and this review has a concrete exact-artifact acquisition blocker on the current execution substrate.
5. No Windows compatibility claim and no product semantic change were made.

---

## 2. Selection authority model

### 2.1 Product truth remains frozen

This gate does not choose different product semantics. It only chooses packaging artifacts/dependencies where 00.9 has now explicitly authorized package-only selection.

Frozen product/package constraints carried forward:

```text
Python = 3.12.10 / windows-x64
Chromium = 151.0.7922.34 / revision 1654411 / win64
ripgrep role = REFERENCE_SEARCH_ENRICHMENT / windows-x64
Playwright product API = playwright.sync_api
Playwright browser binding = chromium.connect_over_cdp(...)
External Chromium authority = canonical package Chromium
OpenCode plugin = @opencode-ai/plugin 1.18.3
CodeGraph = 0.20.1
```

### 2.2 New package-only decisions

The following decisions are new packaging candidates, made under 00.9 package-only authority:

```text
PYTHON_PACKAGE_IDENTITY_CANDIDATE
RIPGREP_PACKAGE_IDENTITY_CANDIDATE
PLAYWRIGHT_PACKAGE_IDENTITY_CANDIDATE
PLAYWRIGHT_TRANSITIVE_DEPENDENCY_SELECTION
```

They are not historical truth and are not Frozen identity.

---

# 3. Python 3.12.10 package identity selection

## 3.1 Frozen requirements

```text
CPython version = 3.12.10
platform = x86_64-pc-windows-msvc
canonical target = workspace-template/runtime/python/python.exe
system Python substitution = FORBIDDEN
Windows installer/MSI/EXE = FORBIDDEN
admin installation = FORBIDDEN
```

Official upstream is `astral-sh/python-build-standalone`.

Official upstream documentation identifies `x86_64-pc-windows-msvc` as 64-bit Windows Intel/AMD and recommends the Windows MSVC shared-style distributions for compatibility. It also states that `install_only` is the normal runtime-focused archive and that `install_only_stripped` is equivalent to `install_only` without debug symbols, producing a smaller download/on-disk footprint.

Official release construction code converts the full distribution's `python/install/**` tree into an install-only archive rooted at `python/**`. Therefore the runtime executable path for the selected archive is:

```text
python/python.exe
```

which can be mapped deterministically to:

```text
workspace-template/runtime/python/python.exe
```

## 3.2 Candidate matrix

| Candidate | Version | Snapshot | Platform | Flavor | Approx/exact asset size | Decision |
| --- | --- | --- | --- | --- | ---: | --- |
| A | 3.12.10 | 20250529 | x86_64-pc-windows-msvc | install_only | 41,889,389 bytes | eligible, larger payload |
| B | 3.12.10 | 20250529 | x86_64-pc-windows-msvc | install_only_stripped | 21,172,386 bytes | **SELECTED** |
| Earlier exact-version snapshots | 3.12.10 | earlier immutable snapshots | x86_64-pc-windows-msvc | install_only / stripped | varies | not selected once exact 20250529 candidate satisfied criteria |

Candidate B wins because it preserves the exact CPython version/platform/runtime behavior while minimizing embedded payload and remaining an official immutable release asset with deterministic provenance.

This is not a `3.12.latest` decision and does not permit 3.12.11 or any other version.

## 3.3 Selected exact candidate

```text
PYTHON_PACKAGE_IDENTITY_CANDIDATE =
  SELECTED_FOR_PACKAGE_QUALIFICATION

provider = astral-sh/python-build-standalone
release snapshot/tag = 20250529
CPython version = 3.12.10
target triple = x86_64-pc-windows-msvc
artifact = cpython-3.12.10+20250529-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
GitHub release asset id = 259481739
archive size = 21172386 bytes
SHA256 = ca22a9a9e64ecab6d0b5de7cdf8b679ccaa41e9def6aaa2b4aaa6bb23ec7aaba
official release URL = https://github.com/astral-sh/python-build-standalone/releases/download/20250529/cpython-3.12.10%2B20250529-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
official checksum companion asset = cpython-3.12.10+20250529-x86_64-pc-windows-msvc-install_only_stripped.tar.gz.sha256
official checksum companion asset id = 259481758
archive root = python/
python.exe internal path = python/python.exe
package target = workspace-template/runtime/python/python.exe
selection authority = 00.9_PACKAGE_ONLY
identity status = SELECTED_WITH_EXACT_IDENTITY / NOT_FROZEN
```

The GitHub release API confirms the exact official asset and size. The release also publishes the corresponding `.sha256` companion asset. The SHA256 above is independently corroborated by multiple deterministic tool/package lock records that point to this exact official upstream asset, including `mise.lock` records carrying GitHub-attestation provenance and generated Python version mappings. The current execution substrate did not successfully re-download and locally re-hash the binary archive, so this record does not misrepresent the digest as a local hash measurement.

## 3.4 Portability qualification caveat

Upstream runtime documentation warns that Windows Python distributions may depend on the Microsoft Visual C++ runtime (`vcruntime140.dll`). Upstream release/validation source also explicitly accounts for `VCRUNTIME140.dll` / `VCRUNTIME140_1.dll` in Windows distribution handling.

Therefore PKG0.6B1 must explicitly test the selected extracted archive on `windows-latest` without using system Python and must inspect whether the selected install-only payload already carries the required application-local VC runtime files or whether an additional package-local VC runtime payload is needed.

This does not invalidate the exact Python archive selection; it is a Windows runtime compatibility/portability proof and must not be silently replaced by an installer/admin prerequisite.

```text
PYTHON_VERSION_SELECTION = CLOSED
PYTHON_PACKAGE_IDENTITY_CANDIDATE = SELECTED_WITH_EXACT_IDENTITY
PYTHON_WINDOWS_RUNTIME_PROOF = PKG0.6B1
PACKAGE_IDENTITY_FROZEN = NO
```

---

# 4. Chromium 151.0.7922.34 exact artifact acquisition

## 4.1 Fixed identity

No version selection is authorized or necessary here.

```text
version = 151.0.7922.34
revision = 1654411
platform = win64
artifact = chrome-win64.zip
canonical target = workspace-template/runtime/browser/chrome-win64/chrome.exe
```

GoogleChromeLabs Chrome for Testing source/data confirms version `151.0.7922.34` at revision `1654411`. The official Chrome-for-Testing URL construction is deterministic:

```text
https://storage.googleapis.com/chrome-for-testing-public/${version}/${platform}/${binary}-${platform}.zip
```

Therefore the exact official artifact URL is:

```text
https://storage.googleapis.com/chrome-for-testing-public/151.0.7922.34/win64/chrome-win64.zip
```

and the required archive layout remains:

```text
chrome-win64/
  chrome.exe
  ...
```

with future package mapping to:

```text
workspace-template/runtime/browser/chrome-win64/chrome.exe
```

## 4.2 Exact-byte acquisition attempt

This gate attempted to acquire the exact official artifact bytes. The current execution substrate could reach/read GitHub/PyPI/CfT metadata surfaces, but direct binary fetch from the Google storage endpoint failed DNS resolution:

```text
curl -I -L \
  https://storage.googleapis.com/chrome-for-testing-public/151.0.7922.34/win64/chrome-win64.zip

result:
  curl: (6) Could not resolve host: storage.googleapis.com
  exit = 6
```

The web binary fetch path also did not yield the archive body. Therefore this review could not honestly calculate:

```text
chrome-win64.zip SHA256
chrome-win64.zip exact size
archive byte-level layout inspection
chrome.exe file-version inspection from the exact archive
```

ChromeDriver checksums, metadata-file digests, adjacent versions, and other Chrome revisions are explicitly rejected as substitutes.

Formal result:

```text
CHROMIUM_ARCHIVE_IDENTITY = EXACT_ARTIFACT_ACQUISITION_BLOCKER_PROVEN
CHROMIUM_ARTIFACT_ACQUISITION = BLOCKED_ON_CURRENT_EXECUTION_SUBSTRATE
CHROMIUM_ARTIFACT_ACQUISITION_BLOCKER =
  CURRENT_EXECUTION_SUBSTRATE_CANNOT_RESOLVE_OR_FETCH_STORAGE_GOOGLEAPIS_COM
CHROMIUM_ARCHIVE_SHA256 = OPEN
CHROMIUM_ARCHIVE_SIZE = OPEN
CHROMIUM_VERSION_SUBSTITUTION = FORBIDDEN
```

This exact artifact should be downloaded and hashed on the Windows CI qualification substrate or another authorized release-build host before package identity can later be Frozen.

---

# 5. ripgrep package-only version selection

## 5.1 Frozen role/platform

```text
role = REFERENCE_SEARCH_ENRICHMENT
platform = windows-x64
```

00.9 newly authorizes package-only version selection.

## 5.2 Candidate matrix

Both candidates below are official `BurntSushi/ripgrep` stable GitHub releases, `prerelease=false`, portable Windows x86_64 MSVC ZIP assets, and require no target-host Cargo/install flow.

| Version/tag | Artifact | Size | SHA256 | Decision |
| --- | --- | ---: | --- | --- |
| 15.1.0 | `ripgrep-15.1.0-x86_64-pc-windows-msvc.zip` | 1,810,687 | `124510b94b6baa3380d051fdf4650eaa80a302c876d611e9dba0b2e18d87493a` | eligible |
| 15.2.0 | `ripgrep-15.2.0-x86_64-pc-windows-msvc.zip` | 1,789,611 | `71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5` | **SELECTED** |

15.2.0 is selected as the exact package candidate because it is a stable, explicitly tagged official release, carries exact GitHub release digest metadata, contains subsequent bug fixes/performance improvements, and is slightly smaller than the immediately preceding stable Windows MSVC payload. This is not an unrecorded `latest` selection; the exact tag/artifact/hash are part of the candidate identity.

## 5.3 Exact selected candidate

```text
RIPGREP_PACKAGE_IDENTITY_CANDIDATE =
  SELECTED_FOR_PACKAGE_QUALIFICATION

provider = BurntSushi/ripgrep
version/tag = 15.2.0
prerelease = false
artifact = ripgrep-15.2.0-x86_64-pc-windows-msvc.zip
GitHub release asset id = 478119643
archive size = 1789611 bytes
SHA256 = 71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5
official release URL = https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-x86_64-pc-windows-msvc.zip
archive root = ripgrep-15.2.0-x86_64-pc-windows-msvc/
rg.exe internal path = ripgrep-15.2.0-x86_64-pc-windows-msvc/rg.exe
candidate package target = workspace-template/runtime/bin/rg.exe
selection authority = 00.9_PACKAGE_ONLY
identity status = SELECTED_WITH_EXACT_IDENTITY / NOT_FROZEN
```

The upstream release workflow itself constructs `$ARCHIVE = ripgrep-$version-$target`, copies the built Windows `rg.exe` into that directory root, then creates `$ARCHIVE.zip`. Therefore the internal path above is source-backed rather than inferred only from naming convention.

No system `rg`, Cargo install, pre-release, or nightly is accepted as this candidate.

---

# 6. Playwright Python package-only selection

## 6.1 Frozen product semantics

Canonical product source already requires:

```text
playwright.sync_api
chromium.connect_over_cdp(...)
external Chromium authority
```

This gate therefore does not authorize Playwright-managed browser selection or a Node application runtime.

```text
PLAYWRIGHT_MANAGED_BROWSER = FORBIDDEN
PLAYWRIGHT_BROWSER_DOWNLOAD_ON_TARGET = FORBIDDEN
PLAYWRIGHT_INSTALL_ON_TARGET = FORBIDDEN
PIP_INSTALL_ON_TARGET = FORBIDDEN
SEPARATE_NODE_APPLICATION_RUNTIME = NOT_REQUIRED
```

## 6.2 Playwright candidate matrix

The candidate must support Python 3.12, sync API, CDP attachment, offline release-host materialization, and the canonical external Chromium.

| Candidate | Python support | Bundled/tested Chromium | Canonical Chromium alignment | Decision |
| --- | --- | --- | --- | --- |
| Playwright 1.61.x | Python 3.x | Chromium `149.0.7827.55` | NO | not selected |
| **Playwright 1.62.0** | Python `>=3.10`, classifier includes 3.12 | Chromium `151.0.7922.34` | **EXACT** | **SELECTED** |

The exact browser-version alignment is the decisive deterministic criterion: Playwright 1.62.0's official Python package metadata/release notes name Chromium `151.0.7922.34`, exactly matching the already-frozen canonical external Chromium version.

## 6.3 Selected Playwright wheel

Official PyPI metadata:

```text
package = playwright
version = 1.62.0
requires_python = >=3.10
supports Python 3.12 = YES
direct runtime dependencies =
  pyee >=13,<14
  greenlet >=3.1.1,<4

Windows x64 wheel = playwright-1.62.0-py3-none-win_amd64.whl
wheel size = 38164458 bytes
wheel SHA256 = 92c0d98ed04eb35af557b709875edba415b1f548bdb22ddb5bb3e1e6c835c2f1
```

Formal selection:

```text
PLAYWRIGHT_PACKAGE_IDENTITY_CANDIDATE =
  playwright==1.62.0 /
  playwright-1.62.0-py3-none-win_amd64.whl /
  sha256=92c0d98ed04eb35af557b709875edba415b1f548bdb22ddb5bb3e1e6c835c2f1

PLAYWRIGHT_SELECTION_AUTHORITY = 00.9_PACKAGE_ONLY
PLAYWRIGHT_IDENTITY_STATUS = SELECTED_WITH_EXACT_DEPENDENCY_CLOSURE / NOT_FROZEN
```

## 6.4 Exact Python dependency closure

The package-only closure selects exact Windows/Python 3.12-compatible wheels inside Playwright's declared constraints:

### pyee

```text
pyee == 13.0.1
artifact = pyee-13.0.1-py3-none-any.whl
size = 15659 bytes
SHA256 = af2f8fede4171ef667dfded53f96e2ed0d6e6bd7ee3bb46437f77e3b57689228
runtime dependency = typing-extensions
```

### typing-extensions

```text
typing-extensions == 4.16.0
artifact = typing_extensions-4.16.0-py3-none-any.whl
size = 45571 bytes
SHA256 = 481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8
requires_python = >=3.9
runtime dependencies = none
```

### greenlet

```text
greenlet == 3.5.5
artifact = greenlet-3.5.5-cp312-cp312-win_amd64.whl
size = 324171 bytes
SHA256 = 49ddacd36af37735fab103846f4ee4d18a492dde72730d1699c0c8ebe30d9f18
ABI = cp312
platform = win_amd64
```

The selected greenlet artifact is the CPython 3.12 Windows x64 wheel, not an sdist and not a wheel for a different Python ABI.

There are no additional mandatory runtime Python dependencies after `typing-extensions` for this closure.

Formal result:

```text
PLAYWRIGHT_TRANSITIVE_DEPENDENCY_CLOSURE = CLOSED
PLAYWRIGHT_PYTHON_WHEEL_CLOSURE = CLOSED
```

## 6.5 Driver/runtime payload included in the Playwright wheel

Official `microsoft/playwright-python` v1.62.0 build inputs pin:

```text
DRIVER_VERSION = 1.62.0
NODE_VERSION = 24.18.1
```

The official build script downloads the matching `playwright-core` and the pinned Node distribution at wheel-build time, and for Windows x64 uses the `win32_x64` driver bundle. The wheel build places the bundle under:

```text
playwright/driver/
  node.exe
  LICENSE
  package/**
```

Therefore the Python Playwright wheel itself carries the Node executable/driver package needed by the Python binding. This does **not** create a separate Node application runtime requirement for the G1-G5 package.

For additional provenance, official Node v24.18.1 release checksums identify the Windows x64 Node ZIP and its executable. The outer Playwright wheel SHA256 remains the package-level identity boundary because `playwright/driver/node.exe` is carried inside the verified wheel.

```text
PLAYWRIGHT_DRIVER_RUNTIME_IDENTITY = CLOSED_BY_VERIFIED_PLAYWRIGHT_WHEEL
SEPARATE_NODE_RUNTIME_REQUIRED = NO
```

## 6.6 Deterministic offline materialization strategy

Future authorized release-build / PKG1 flow, **not target-host flow**:

```text
1. Acquire the four exact wheel artifacts:
   - playwright 1.62.0 win_amd64
   - pyee 13.0.1 universal
   - typing-extensions 4.16.0 universal
   - greenlet 3.5.5 cp312 win_amd64

2. Verify every wheel against the exact SHA256 recorded above.

3. Extract/materialize the selected Python 3.12.10 standalone payload.

4. On an authorized Windows release-build host, materialize the verified
   wheel closure into the portable Python runtime's normal site-packages
   using an offline verified wheelhouse / --no-index / exact hashes, or an
   equivalent deterministic wheel materialization process.

5. Preserve inside portable Python:
   Lib/site-packages/playwright/**
   Lib/site-packages/playwright/driver/node.exe
   Lib/site-packages/playwright/driver/package/**
   Lib/site-packages/pyee/**
   Lib/site-packages/greenlet/**
   Lib/site-packages/typing_extensions.py (and distribution metadata)

6. Do not run `playwright install`.
7. Do not download Playwright-managed Chromium.
8. Launch the canonical external Chromium from:
   workspace-template/runtime/browser/chrome-win64/chrome.exe
9. Attach product runtime using:
   chromium.connect_over_cdp(cdp_endpoint)
```

Target-host contract:

```text
pip install = FORBIDDEN
playwright install = FORBIDDEN
internet = FORBIDDEN
second Chromium download = FORBIDDEN
system Python fallback = FORBIDDEN
system Node dependency = FORBIDDEN
```

Formal result:

```text
PLAYWRIGHT_PACKAGE_IDENTITY_CANDIDATE = SELECTED_WITH_EXACT_DEPENDENCY_CLOSURE
PLAYWRIGHT_TRANSITIVE_DEPENDENCY_CLOSURE = CLOSED
PLAYWRIGHT_EXTERNAL_CHROMIUM_BINDING_STRATEGY = CLOSED_CDP
PLAYWRIGHT_OFFLINE_LAYOUT_STRATEGY = CLOSED
PLAYWRIGHT_WINDOWS_RUNTIME_PROOF = PKG0.6B1
```

---

# 7. OpenCode plugin carry-forward — do not reopen

PKG0.6A already closed the non-Windows identity/layout question for OpenCode's plugin dependency.

Carry forward unchanged:

```text
OpenCode qualification candidate = 1.18.3
@opencode-ai/plugin = 1.18.3
OPENCODE_PLUGIN_OFFLINE_DEPENDENCY = CLOSED
OPENCODE_PLUGIN_OFFLINE_DEPENDENCY_PAYLOAD = CLOSED_AT_IDENTITY_AND_LAYOUT_LEVEL
OPENCODE_PLUGIN_WINDOWS_RUNTIME_PROOF = PKG0.6B
```

No PKG0.6A.1 finding reopens this item.

---

# 8. CodeGraph carry-forward — do not reopen

Carry forward unchanged:

```text
CodeGraph = 0.20.1
codegraph-server-win32-x64.exe SHA256 =
  aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1
onnxruntime.dll SHA256 =
  52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948
CODEGRAPH_WINDOWS_PAYLOAD_IDENTITY = CLOSED
CODEGRAPH_ONNXRUNTIME_DLL_RUNTIME_LOCK_REPRESENTATION = PKG1_REQUIRED
```

No runtime-lock edit is authorized in this gate.

---

# 9. PKG0.6B Windows qualification substrate design

This gate defines the substrate only; it does not create a workflow or execute Windows qualification.

Selected qualification structure:

```text
WINDOWS_QUALIFICATION_SUBSTRATE =
  GITHUB_ACTIONS_WINDOWS + REAL_WINDOWS_INTERACTIVE_SPLIT

PKG0.6B1 =
  GITHUB_ACTIONS_WINDOWS_PACKAGE_COMPATIBILITY

PKG0.6B2 =
  REAL_WINDOWS_INTERACTIVE_OPENCODE_QUALIFICATION
```

## 9.1 PKG0.6B1 — GitHub Actions Windows package compatibility

A future authorized `windows-latest` workflow is suitable for mechanically proving:

```text
exact binary/artifact download + hash
package directory layout
OpenCode --version
workspace discovery
.opencode tool loading
Python 3.12.10 executable identity
portable Python imports
Playwright sync_api import
Playwright bundled driver/node availability
external Chromium launch
CDP readiness and connect_over_cdp
no Playwright browser install/download
ripgrep --version and execution
CodeGraph executable + onnxruntime.dll colocated launch
OpenCode offline plugin dependency materialization/load
no system Python fallback
no system rg substitution
```

For Chromium specifically, the Windows CI/release-build substrate should fetch the **exact already-fixed** `151.0.7922.34/win64/chrome-win64.zip`, calculate SHA256/size, inspect `chrome-win64/chrome.exe`, and persist that evidence before any future identity freeze.

## 9.2 PKG0.6B2 — real Windows interactive OpenCode qualification

GitHub Actions must not be used to overclaim true TUI/user-turn behavior. A real Windows host is required for the interactive portion:

```text
direct interactive OpenCode launch
real user-turn -> tool invocation
aitest-director discovery/use
G3 callable behavior
G4 callable behavior
G5 Diagnosis / aitest-diagnosis behavior
HumanGate user-turn behavior
external web/sidecar requirement in actual interactive use
```

Therefore:

```text
GITHUB_ACTIONS_WINDOWS_QUALIFICATION
!=
REAL_WINDOWS_INTERACTIVE_OPENCODE_QUALIFICATION

GITHUB_ACTIONS_WINDOWS_QUALIFICATION
!=
FINAL_USER_LOCAL_VALIDATION
```

Final user Local Validation remains a later `10.LV` activity on the user's real Windows + Git Bash environment.

This gate creates no workflow and executes neither B1 nor B2.

```text
WINDOWS_COMPATIBILITY_EXECUTED = NO
```

---

# 10. Remaining identity / qualification gaps

After applying the new package-only selection authority, the former `NO_HISTORICAL_PIN` ambiguities are no longer blockers for Python, ripgrep, or Playwright.

Remaining:

```text
BINARY_IDENTITY_GAPS_REMAINING = [
  CHROMIUM_151_0_7922_34_ARCHIVE_SHA256_PENDING_EXACT_ARTIFACT_ACQUISITION,
  OPENCODE_WINDOWS_POST_G5_COMPATIBILITY_QUALIFICATION
]
```

The second item is intentionally PKG0.6B and is not a PKG0.6A.1 non-Windows identity defect.

Qualification-only checks carried to PKG0.6B1 include:

```text
PYTHON_SELECTED_ARCHIVE_WINDOWS_EXECUTION
PYTHON_APPLICATION_LOCAL_VC_RUNTIME_REALITY
PLAYWRIGHT_SELECTED_WHEEL_CLOSURE_WINDOWS_IMPORT
PLAYWRIGHT_CDP_ATTACH_TO_CANONICAL_CHROMIUM
RIPGREP_SELECTED_ARCHIVE_WINDOWS_EXECUTION
CODEGRAPH_SELECTED_PAYLOAD_WINDOWS_LAUNCH
OPENCODE_PLUGIN_SELECTED_OFFLINE_LAYOUT_WINDOWS_LOAD
```

None is claimed PASS by this record.

---

# 11. Gate evaluation

```text
PYTHON_PACKAGE_IDENTITY_CANDIDATE =
  SELECTED_WITH_EXACT_IDENTITY

CHROMIUM_ARCHIVE_IDENTITY =
  EXACT_ARTIFACT_ACQUISITION_BLOCKER_PROVEN

RIPGREP_PACKAGE_IDENTITY_CANDIDATE =
  SELECTED_WITH_EXACT_IDENTITY

PLAYWRIGHT_PACKAGE_IDENTITY_CANDIDATE =
  SELECTED_WITH_EXACT_DEPENDENCY_CLOSURE

NO_WINDOWS_COMPATIBILITY_CLAIM = TRUE
NO_PRODUCT_SEMANTICS_CHANGE = TRUE

PKG0_6A_1_GATE_CRITERIA = SATISFIED_FOR_PASS_CANDIDATE
```

`PASS_CANDIDATE` is deliberately not `PACKAGE_IDENTITY_FROZEN`. Chromium exact archive bytes must still be acquired/hash-verified before future freeze, and the Windows compatibility gates remain unexecuted.

---

# 12. Final formal state

```text
PKG0_6A_1_PACKAGE_DEPENDENCY_SELECTION = PASS_CANDIDATE

PYTHON_PACKAGE_IDENTITY_CANDIDATE =
  20250529 /
  cpython-3.12.10+20250529-x86_64-pc-windows-msvc-install_only_stripped.tar.gz /
  sha256=ca22a9a9e64ecab6d0b5de7cdf8b679ccaa41e9def6aaa2b4aaa6bb23ec7aaba /
  SELECTED_WITH_EXACT_IDENTITY
PYTHON_SELECTION_AUTHORITY = 00.9_PACKAGE_ONLY

CHROMIUM_VERSION = 151.0.7922.34
CHROMIUM_REVISION = 1654411
CHROMIUM_ARTIFACT = chrome-win64.zip
CHROMIUM_ARCHIVE_SHA256 = OPEN
CHROMIUM_ARTIFACT_ACQUISITION = BLOCKED_ON_CURRENT_EXECUTION_SUBSTRATE

RIPGREP_PACKAGE_IDENTITY_CANDIDATE =
  15.2.0 /
  ripgrep-15.2.0-x86_64-pc-windows-msvc.zip /
  sha256=71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5 /
  SELECTED_WITH_EXACT_IDENTITY
RIPGREP_SELECTION_AUTHORITY = 00.9_PACKAGE_ONLY

PLAYWRIGHT_PACKAGE_IDENTITY_CANDIDATE =
  playwright==1.62.0 /
  playwright-1.62.0-py3-none-win_amd64.whl /
  sha256=92c0d98ed04eb35af557b709875edba415b1f548bdb22ddb5bb3e1e6c835c2f1 /
  SELECTED_WITH_EXACT_DEPENDENCY_CLOSURE
PLAYWRIGHT_SELECTION_AUTHORITY = 00.9_PACKAGE_ONLY
PLAYWRIGHT_TRANSITIVE_DEPENDENCY_CLOSURE = CLOSED

OPENCODE_PLUGIN_OFFLINE_DEPENDENCY = CLOSED
CODEGRAPH_WINDOWS_PAYLOAD_IDENTITY = CLOSED

WINDOWS_QUALIFICATION_SUBSTRATE =
  GITHUB_ACTIONS_WINDOWS + REAL_WINDOWS_INTERACTIVE_SPLIT
WINDOWS_COMPATIBILITY_EXECUTED = NO

BINARY_IDENTITY_GAPS_REMAINING = [
  CHROMIUM_151_0_7922_34_ARCHIVE_SHA256_PENDING_EXACT_ARTIFACT_ACQUISITION,
  OPENCODE_WINDOWS_POST_G5_COMPATIBILITY_QUALIFICATION
]

PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
PRODUCT_SOURCE_MODIFIED = NO
PRODUCT_SEMANTICS_MODIFIED = NO
RUNTIME_LOCK_MODIFIED = NO
PACKAGE_MANIFEST_MODIFIED = NO
LAUNCHER_MODIFIED = NO
OPENCODE_AGENT_OR_TOOL_MODIFIED = NO
PACKAGING_CONSTRUCTION_STARTED = NO
PACKAGE_ASSEMBLY_STARTED = NO
ZIP_BUILD_STARTED = NO
LOCAL_VALIDATION_STARTED = NO
PKG0_6B = HOLD
PKG1 = HOLD
LOCAL_VALIDATION = HOLD
G1_G5_REOPEN_REQUIRED = NO
G6 = HOLD
```

**STOP after this documentation/evidence record and return to 00.9 for independent review. Do not enter PKG0.6B or PKG1.**
