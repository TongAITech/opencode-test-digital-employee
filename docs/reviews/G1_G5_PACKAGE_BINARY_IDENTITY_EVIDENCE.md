# G1-G5 Package Binary Identity Evidence

**Status:** `PKG0.6A / 00.9_REVIEW_REQUIRED`  
**WorkItem:** `10.PKG｜G1-G5 Local Validation Runtime & Offline Package Assembly`  
**Gate:** `PKG0.6A — Non-Windows Binary & Offline Dependency Identity Closure`  
**Governance Authority:** `00.9｜ChatGPT Harness 总控与架构治理｜G5-G6` only  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical main:** `58e5e1259cd26846b31ea21a8a87df0bcf071edc`  
**Active branch:** `work/local-validation-package`  
**Authorized starting head:** `32e827fe412cc2f7dcbfd49817a76417d84c3e8e`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`

This is documentation/evidence only. It does not modify or authorize modification of `runtime-lock.json`, `PACKAGE_MANIFEST.json`, launchers, Agents, Tools, G1-G5 product source, canonical `main`, package payloads, final package assembly, ZIP build, Local Validation, PKG0.6B Windows qualification, PKG1, or G6.

The governing distinction remains mandatory:

```text
OFFICIAL_ARTIFACT_IDENTITY_CONFIRMED
!=
WINDOWS_PRODUCT_COMPATIBILITY_PASS
```

---

## 1. PKG0.6A boundary and verdict

Authorized scope:

```text
IN_SCOPE = [
  OPENCODE_PLUGIN_OFFLINE_DEPENDENCY_PAYLOAD,
  PYTHON_BUILD_STANDALONE_EXACT_SNAPSHOT_AND_SHA256,
  CHROMIUM_151_0_7922_34_ARCHIVE_SHA256,
  RIPGREP_VERSION_ARTIFACT_AND_SHA256,
  CODEGRAPH_ONNXRUNTIME_DLL_RUNTIME_LOCK_REPRESENTATION,
  PLAYWRIGHT_PYTHON_OFFLINE_DEPENDENCY_CLOSURE
]

OUT_OF_SCOPE = [
  OPENCODE_WINDOWS_POST_G5_COMPATIBILITY_QUALIFICATION,
  WINDOWS_RUNTIME_EXECUTION,
  PACKAGE_ASSEMBLY,
  ZIP_BUILD,
  LOCAL_VALIDATION,
  PKG1
]
```

Result:

```text
PKG0_6A_NON_WINDOWS_BINARY_IDENTITY_CLOSURE = PARTIAL
PKG0_6A_CAN_CLOSE = NO
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
```

Reason: CodeGraph Windows payload identity and the OpenCode v1.18.3 plugin offline identity/provisioning strategy can be closed at the non-Windows evidence level. Python exact standalone snapshot/hash, Chromium exact Chrome archive SHA/inspection evidence, ripgrep version selection, and the Playwright Python package/wheel dependency closure remain open. No G1-G5 semantic defect was found.

---

## 2. Authority model used by this review

### 2.1 Project lock truth

The sole project lock authority for the current package candidate is:

`runtime-lock.json@58e5e1259cd26846b31ea21a8a87df0bcf071edc`.

It freezes the following relevant project-side facts:

```text
Python:
  version = 3.12.10
  platform = windows-x64
  relative_target = workspace-template/runtime/python/python.exe
  sha256 = TO_BE_PINNED_FROM_CANONICAL_PAYLOAD_REGISTRY

Chromium:
  version = 151.0.7922.34
  platform = windows-x64
  relative_target = workspace-template/runtime/browser/chrome-win64/chrome.exe
  sha256 = TO_BE_PINNED_FROM_CANONICAL_PAYLOAD_REGISTRY

CodeGraph:
  provider = codegraph-ai/CodeGraph
  version = 0.20.1
  platform = windows-x64
  relative_target = workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe
  release_asset = codegraph-server-win32-x64.exe
  sha256 = aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1

ripgrep:
  role = REFERENCE_SEARCH_ENRICHMENT
  platform = windows-x64
  status = CAPABILITY_REQUIRED_WHERE_AVAILABLE_VERSION_NOT_YET_PINNED
  sha256 = TO_BE_PINNED_FROM_CANONICAL_PAYLOAD_REGISTRY
```

The ripgrep lock does not freeze provider, version, artifact, or relative target.

### 2.2 Git/history reality

Repository history inspection found no additional canonical project record that selects:

- a unique `python-build-standalone` snapshot/build artifact for Python 3.12.10;
- a ripgrep version/artifact/hash;
- a Playwright Python package version/wheel/transitive dependency set.

The runtime payload/cache/archive paths are deliberately excluded from Git, so missing payload identity cannot be reconstructed by treating a non-source binary directory as current project truth.

### 2.3 Upstream evidence boundary

Official upstream release/source evidence may establish artifact facts and compatibility candidates, but it may not silently replace missing project-side selection authority. Third-party lockfiles are used only as corroborating package-resolution evidence where explicitly identified; they are not promoted to project governance authority.

---

## 3. Python 3.12.10 standalone identity

### 3.1 Canonical project truth

```text
version = 3.12.10
platform = windows-x64
target = workspace-template/runtime/python/python.exe
```

### 3.2 Recon result

The Git/history/build-evidence search did not identify one exact project-backed `python-build-standalone` release snapshot, Windows x64 artifact name, or artifact SHA256.

There can be multiple upstream release snapshots containing CPython 3.12.10. Selecting an arbitrary snapshot, including a latest snapshot, would create new package identity authority that does not exist in the current project truth.

Therefore:

```text
PYTHON_BINARY_IDENTITY = OPEN
PYTHON_BUILD_STANDALONE_EXACT_SNAPSHOT_AND_SHA256 = OPEN
PYTHON_VERSION_SELECTION = FROZEN_AT_3.12.10
PYTHON_UPSTREAM_SNAPSHOT_SELECTION = GOVERNANCE_GAP
```

No Python binary was promoted or frozen by PKG0.6A.

---

## 4. Chromium 151.0.7922.34 identity

### 4.1 Canonical project truth

```text
version = 151.0.7922.34
platform = windows-x64
artifact_required = chrome-win64.zip
target = workspace-template/runtime/browser/chrome-win64/chrome.exe
```

### 4.2 Official upstream identity evidence

GoogleChromeLabs Chrome-for-Testing data identifies:

```text
version = 151.0.7922.34
revision = 1654411
platform = win64
artifact family = chrome-win64.zip
```

This establishes the exact browser version/revision and expected Chrome-for-Testing artifact family. It does not by itself establish the archive bytes or project-approved archive SHA256.

### 4.3 Fail-closed archive result

During this review, the exact Chrome archive body was not mechanically obtained through the available evidence substrate, so the following required facts were not independently calculated/inspected:

```text
chrome-win64.zip SHA256 = UNRESOLVED
chrome-win64.zip size = UNRESOLVED_BY_THIS_REVIEW
archive layout inspection = NOT_COMPLETED
chrome.exe file-version inspection from exact archive = NOT_COMPLETED
```

ChromeDriver checksum evidence is explicitly rejected as evidence for `chrome-win64.zip`. No adjacent or newer Chrome version is substituted.

Therefore:

```text
CHROMIUM_BINARY_IDENTITY = OPEN
CHROMIUM_151_0_7922_34_ARCHIVE_SHA256 = OPEN
```

---

## 5. ripgrep identity

### 5.1 Canonical project truth

The current lock freezes only:

```text
role = REFERENCE_SEARCH_ENRICHMENT
platform = windows-x64
status = CAPABILITY_REQUIRED_WHERE_AVAILABLE_VERSION_NOT_YET_PINNED
sha256 = TO_BE_PINNED_FROM_CANONICAL_PAYLOAD_REGISTRY
```

### 5.2 Selection result

Project-side historical evidence did not provide source-backed authority to select a specific ripgrep version. Any upstream provider/artifact naming convention remains candidate evidence only until 00.9 makes or authorizes a version-selection decision.

Therefore:

```text
RIPGREP_VERSION_SELECTION = GOVERNANCE_GAP
RIPGREP_BINARY_IDENTITY = OPEN
RIPGREP_VERSION = UNRESOLVED
RIPGREP_ARTIFACT = UNRESOLVED
RIPGREP_RELATIVE_TARGET = UNRESOLVED
RIPGREP_SHA256 = UNRESOLVED
```

No latest ripgrep release was selected.

---

## 6. CodeGraph Windows payload identity

### 6.1 Canonical executable

Project lock truth:

```text
provider = codegraph-ai/CodeGraph
version = 0.20.1
platform = windows-x64
target = workspace-template/runtime/code-intelligence/codegraph/codegraph-server-win32-x64.exe
artifact = codegraph-server-win32-x64.exe
sha256 = aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1
```

Official CodeGraph v0.20.1 release metadata independently matches this executable SHA256. Official release metadata also reports executable size `105874432` bytes.

### 6.2 Required Windows companion

The same official Windows release requires `onnxruntime.dll` beside the executable and provides:

```text
artifact = onnxruntime.dll
sha256 = 52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948
size = 11567648 bytes
placement = beside codegraph-server-win32-x64.exe
```

The current project runtime lock does not contain this companion DLL identity. That fact remains explicit.

Result:

```text
CODEGRAPH_WINDOWS_PAYLOAD_IDENTITY = CLOSED
CODEGRAPH_EXECUTABLE_IDENTITY = CLOSED
CODEGRAPH_ONNXRUNTIME_DLL_IDENTITY = CLOSED
CODEGRAPH_ONNXRUNTIME_DLL_RUNTIME_LOCK_REPRESENTATION = PKG1_REQUIRED
RUNTIME_LOCK_CURRENTLY_CONTAINS_ONNXRUNTIME_DLL = NO
```

PKG0.6A does not edit the lock.

---

## 7. OpenCode v1.18.3 offline plugin dependency

### 7.1 Version authority

PKG0.5 accepted OpenCode `1.18.3` as the sole source-backed qualification candidate. Upstream OpenCode v1.18.3 source binds the matching plugin version:

```text
OpenCode = 1.18.3
@opencode-ai/plugin = 1.18.3
@opencode-ai/sdk = 1.18.3
```

The official v1.18.3 plugin package metadata declares direct runtime dependencies:

```text
@ai-sdk/provider = 3.0.8
@opencode-ai/sdk = 1.18.3
effect = 4.0.0-beta.83
zod = 4.1.8
```

and optional OpenTUI peers `>=0.4.3`.

### 7.2 Exact plugin tarball identity

Independent npm v3 lock evidence consistently resolves:

```text
package = @opencode-ai/plugin
version = 1.18.3
artifact = plugin-1.18.3.tgz
resolved = https://registry.npmjs.org/@opencode-ai/plugin/-/plugin-1.18.3.tgz
integrity = sha512-hAm/hZkSCsMSNHVy9DKmFtZAve/qYoIWpduNPcvXnnKK7NMlJEOQitA6CQC67Ym5DFKypDW1TC9YO6S1WdGtpg==
sha512_hex = 8409bf8599120ac312347572f432a616d640bdefea628216a5db8d3dcbd79e728aecd3252443908ad03a0900baed89b90c52b2a435b54c2f583ba4b559d1ada6
```

The same lock evidence resolves the matching SDK `1.18.3` and the plugin direct dependencies above. The npm lock closure records exact versions/integrities for transitive packages used by this resolution, including the Windows x64 optional `msgpackr-extract` native package when applicable.

Representative resolved dependency tree from the lock closure:

```text
@opencode-ai/plugin@1.18.3
├─ @ai-sdk/provider@3.0.8
│  └─ json-schema@0.4.0
├─ @opencode-ai/sdk@1.18.3
│  └─ cross-spawn@7.0.6
│     ├─ path-key@3.1.1
│     ├─ shebang-command@2.0.0
│     │  └─ shebang-regex@3.0.0
│     └─ which@2.0.2
│        └─ isexe@2.0.0
├─ effect@4.0.0-beta.83
│  ├─ @standard-schema/spec@1.1.0
│  ├─ fast-check@4.9.0
│  │  └─ pure-rand@8.4.2
│  ├─ find-my-way-ts@0.1.6
│  ├─ ini@7.0.0
│  ├─ kubernetes-types@1.30.0
│  ├─ msgpackr@2.0.5
│  │  └─ msgpackr-extract@3.0.4 (optional)
│  │     ├─ node-gyp-build-optional-packages@5.2.2
│  │     │  └─ detect-libc@2.1.2
│  │     └─ @msgpackr-extract/msgpackr-extract-win32-x64@3.0.4 (Windows x64 optional payload)
│  ├─ multipasta@0.2.8
│  ├─ toml@4.3.0
│  ├─ uuid@14.0.2
│  └─ yaml@2.9.0
└─ zod@4.1.8
```

This lock tree is package-resolution corroboration, not project governance authority. The compatible plugin version itself is derived from OpenCode v1.18.3 source/release identity.

### 7.3 Deterministic offline provisioning strategy

OpenCode v1.18.3 configuration code prepares the matching `@opencode-ai/plugin` dependency for `.opencode`. Its npm service implementation checks the existing directory state and can return without dependency reification when the requested dependency is already represented by the local package manifest/lock and `node_modules` exists.

Therefore the package-build strategy is:

```text
RELEASE_BUILD_HOST:
  resolve and verify exact locked dependency closure
  materialize package.json
  materialize package-lock.json
  materialize node_modules/** from the exact lock closure
  verify package integrity before inclusion

TARGET_HOST:
  use pre-provisioned .opencode dependency payload
  npm install = FORBIDDEN
  bun install online = FORBIDDEN
  internet = FORBIDDEN
```

Expected package-relative materialization location for PKG1:

```text
workspace-template/.opencode/package.json
workspace-template/.opencode/package-lock.json
workspace-template/.opencode/node_modules/**
```

The current canonical Git tree intentionally does not contain those generated/offline dependency payloads; PKG0.6A only establishes their deterministic identity/layout strategy. Actual payload materialization belongs to later authorized packaging work.

Result:

```text
OPENCODE_PLUGIN_OFFLINE_DEPENDENCY = CLOSED
OPENCODE_PLUGIN_OFFLINE_DEPENDENCY_PAYLOAD = CLOSED_AT_IDENTITY_AND_LAYOUT_LEVEL
OPENCODE_PLUGIN_OFFLINE_MATERIALIZATION = PKG1_REQUIRED
OPENCODE_PLUGIN_WINDOWS_RUNTIME_PROOF = PKG0.6B
```

This result does not claim that OpenCode has passed on Windows.

---

## 8. Playwright Python offline dependency

### 8.1 Canonical product behavior

Canonical G1-G5 browser runtime imports `playwright.sync_api`, starts Playwright, and attaches to an externally controlled Chromium using `chromium.connect_over_cdp(cdp_endpoint)`.

This establishes the product binding strategy:

```text
PLAYWRIGHT_EXTERNAL_CHROMIUM_BINDING_STRATEGY = CLOSED_CDP
PLAYWRIGHT_MANAGED_BROWSER_DOWNLOAD = FORBIDDEN
PLAYWRIGHT_INSTALL_ON_TARGET = FORBIDDEN
```

The package must bind Playwright to the canonical external Chromium `151.0.7922.34`; it must not cause Playwright to download or substitute another managed Chromium revision.

### 8.2 Missing package identity authority

Canonical Git/history does not freeze a Playwright Python package version, wheel identity, transitive wheel identities, or embedded driver/runtime payload identity. No current project dependency manifest found by this review provides that version-selection authority.

Choosing a remembered, conversation-only, environment-local, or latest Playwright version would violate the PKG0.6A rules.

Therefore:

```text
PLAYWRIGHT_PYTHON_OFFLINE_DEPENDENCY = OPEN
PLAYWRIGHT_VERSION_SELECTION = GOVERNANCE_GAP
PLAYWRIGHT_PYTHON_WHEEL_IDENTITY = OPEN
PLAYWRIGHT_TRANSITIVE_DEPENDENCY_IDENTITY = OPEN
PLAYWRIGHT_DRIVER_RUNTIME_IDENTITY = OPEN
PLAYWRIGHT_EXTERNAL_CHROMIUM_BINDING_STRATEGY = CLOSED_CDP
```

The final package must ultimately satisfy all of:

```text
NO pip install
NO playwright install
NO internet
NO Playwright-managed Chromium download
```

but PKG0.6A cannot freeze the missing Playwright package identity without new governance authority.

---

## 9. PKG0.6B input preparation only

The separate Windows qualification gate remains:

```text
PKG0.6B = OPENCODE_WINDOWS_POST_G5_COMPATIBILITY_QUALIFICATION
```

Prepared qualification input only:

```text
OpenCode version = 1.18.3
artifact = opencode-windows-x64.zip
SHA256 = 68bc62930f6cb5755e0409aa9de0bb270a66ed2b8c9cf0c029e9f2287ed5486e
primary agent = aitest-director
Defect Hunter agent = aitest-diagnosis
```

The official release archive identity is not a compatibility result.

Windows matrix definition:

| Check | PKG0.6A result |
| --- | --- |
| `opencode --version` | `NOT_EXECUTED_ON_WINDOWS` |
| current workspace load | `NOT_EXECUTED_ON_WINDOWS` |
| `aitest-director` discovery | `NOT_EXECUTED_ON_WINDOWS` |
| `.opencode/tools/aitest.ts` load | `NOT_EXECUTED_ON_WINDOWS` |
| Director callable | `NOT_EXECUTED_ON_WINDOWS` |
| G3 callable | `NOT_EXECUTED_ON_WINDOWS` |
| G4 callable | `NOT_EXECUTED_ON_WINDOWS` |
| G5 Diagnosis / Defect Hunter callable | `NOT_EXECUTED_ON_WINDOWS` |
| HumanGate callable | `NOT_EXECUTED_ON_WINDOWS` |
| offline plugin dependency works | `NOT_EXECUTED_ON_WINDOWS` |
| direct interactive launch works | `NOT_EXECUTED_ON_WINDOWS` |
| external web/sidecar requirement | `NOT_EXECUTED_ON_WINDOWS` |

No Windows workflow/substrate is created by this review. The current canonical repository validation workflow inspected by this review is Ubuntu-based, so PKG0.6A does not infer an authorized Windows qualification substrate.

```text
OPENCODE_WINDOWS_COMPATIBILITY = NOT_EXECUTED
WINDOWS_QUALIFICATION_SUBSTRATE = UNRESOLVED
```

---

## 10. Remaining gaps after PKG0.6A

```text
BINARY_IDENTITY_GAPS_REMAINING = [
  OPENCODE_WINDOWS_POST_G5_COMPATIBILITY_QUALIFICATION,
  PYTHON_BUILD_STANDALONE_EXACT_SNAPSHOT_AND_SHA256,
  CHROMIUM_151_0_7922_34_ARCHIVE_SHA256,
  RIPGREP_VERSION_ARTIFACT_AND_SHA256,
  PLAYWRIGHT_PYTHON_OFFLINE_DEPENDENCY_CLOSURE
]
```

Separately deferred representation work:

```text
PKG1_DEFERRED_REPRESENTATION = [
  CODEGRAPH_ONNXRUNTIME_DLL_RUNTIME_LOCK_REPRESENTATION
]
```

The CodeGraph representation item is no longer an unknown binary identity; it is a known companion identity that is intentionally not written to the lock before PKG1 authorization.

---

## 11. Gate evaluation

```text
ALL_NON_WINDOWS_IDENTITY_GAPS_HAVE_EXACT_SOURCE_BACKED_IDENTITY = NO
ALL_OFFLINE_DEPENDENCY_PAYLOADS_HAVE_DETERMINISTIC_LAYOUT = NO
NO_WINDOWS_EXECUTION_CLAIM_IS_REQUIRED = YES
NO_PRODUCT_SEMANTICS_CHANGE_IS_REQUIRED = YES

PKG0_6A_CAN_CLOSE = NO
```

The second condition remains `NO` because the Playwright Python package/driver dependency payload is not yet version-pinned and therefore cannot yet have a fully deterministic payload closure, despite its external-CDP browser strategy being known.

---

## 12. Final PKG0.6A state

```text
PKG0_6A_NON_WINDOWS_BINARY_IDENTITY_CLOSURE = PARTIAL

PYTHON_BINARY_IDENTITY = OPEN
CHROMIUM_BINARY_IDENTITY = OPEN
RIPGREP_BINARY_IDENTITY = OPEN
CODEGRAPH_WINDOWS_PAYLOAD_IDENTITY = CLOSED
OPENCODE_PLUGIN_OFFLINE_DEPENDENCY = CLOSED
PLAYWRIGHT_PYTHON_OFFLINE_DEPENDENCY = OPEN

OPENCODE_WINDOWS_COMPATIBILITY = NOT_EXECUTED
WINDOWS_QUALIFICATION_SUBSTRATE = UNRESOLVED

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
PKG1 = HOLD
LOCAL_VALIDATION = HOLD
G1_G5_REOPEN_REQUIRED = NO
G6 = HOLD
```

**STOP after this documentation/evidence record and return to 00.9 for independent review. Do not enter PKG0.6B or PKG1.**