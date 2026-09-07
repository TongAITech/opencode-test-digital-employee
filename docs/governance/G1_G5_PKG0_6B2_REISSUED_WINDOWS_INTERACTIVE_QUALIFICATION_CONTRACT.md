# G1-G5 PKG0.6B2 Reissued Windows Interactive Qualification Contract

Contract ID: `PKG0.6B2-REISSUED-2026-09-07`

Status: `REISSUED / FROZEN BY 00.9`

Authority type: `GIT_NATIVE_GOVERNANCE_CONTRACT`

Scope: `POST_B1_REAL_WINDOWS_INTERACTIVE_QUALIFICATION`

ArchitectureBaseline: `v7 / FROZEN / UNCHANGED`

Canonical repository: `TongAITech/opencode-test-digital-employee`

Canonical main: `58e5e1259cd26846b31ea21a8a87df0bcf071edc`

Reissue parent / authorized packaging head: `ac11ee35d198607ed9724b501a26666aedf00f47`

B1 Windows execution authority: `9a52e33204c51f8e5f15ea8b6c2c60d533103d95`

B1 formal Windows run: `34079065820`

B1 Evidence authority: `c11208af52d085296494dc26e86ed587be6cef0d:docs/reviews/G1_G5_PACKAGE_WINDOWS_QUALIFICATION_EVIDENCE.md`

---

## 1. Reissue declaration and non-equivalence boundary

The previously referenced record named `10.1.PKG.2.1 | PKG0.6B2 Gate Authorization & Evidence Contract` could not be retrieved from the inspected Git history/current tree, File Library, or other retrievable formal project sources. Its immutable locator, exact text, scenario IDs/count, and original machine-readable Evidence schema are therefore unavailable.

This contract is deliberately **REISSUED** under explicit Product Owner authorization to repair that authority-persistence gap.

```text
ORIGINAL_CONTRACT_RECOVERY = FAILED / NOT_RETRIEVABLE
ORIGINAL_CONTRACT_EXISTS_OR_NEVER_EXISTED = NOT_DETERMINED
ORIGINAL_EQUIVALENCE_CLAIM = NO
VERBATIM_EQUIVALENCE_CLAIM = NO
ORIGINAL_SCENARIO_COUNT_CLAIM = NO
ORIGINAL_SCENARIO_ID_CLAIM = NO
KNOWN_BOUNDARY_WEAKENING = FORBIDDEN
```

The reissue may be stricter where a retrievable frozen/current source already establishes a safety, truth, routing, HumanGate, offline, or evidence invariant. It must not invent a new product feature merely to create a test condition.

The immutable authority for this reissued contract is the enclosing Git commit plus this file's Git blob identity. 00.9 records those exact identities after publication; conversation text is not contract authority.

---

## 2. Current governance state

```text
G1 = PASS / FROZEN
G2 = PASS / FROZEN
G2R-1 = PASS / FROZEN
G2.1 = PASS / FROZEN
G3 = PASS / FROZEN
G4 = PASS / FROZEN
G5 = PASS / CLOSED / FROZEN

PKG0_6B1 = PASS / CLOSED
PKG0_6B2 = BLOCKED UNTIL REAL INTERACTIVE EXECUTION
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
PKG1 = HOLD
LOCAL_VALIDATION = HOLD
G6 = HOLD
```

B2 is a qualification gate. It does not authorize product-semantic repair, Architecture v7 change, dependency reselection, final package assembly, runtime-lock canonicalization, manifest canonicalization, Local Validation, or G6 behavior.

---

## 3. Retrievable source basis

This reissue preserves constraints directly supported by the following retrievable Git-native sources:

1. `workspace-template/.opencode/agents/aitest-director.md` at reissue parent `ac11ee35d198607ed9724b501a26666aedf00f47`, blob `0eb1e9ff4e9253f6a7d73824042cfc74dfed0a49`.
   - Primary agent = `aitest-director`.
   - R1 Event Stream is sole durable runtime truth.
   - Explicit new test goal routes through `aitest_director` action `start_test`.
   - Continue intent routes through `aitest_director` action `continue_test`.
   - G3 intake uses `aitest_g3_director`.
   - G4 execution/convergence uses `aitest_g4_director` plus Router-bound execution.
   - HumanGate completion intent is only `REQUEST_TO_VERIFY_COMPLETION`; official `aitest_human_gate_resume`, durable Mission truth, and fresh Browser Runtime verification govern resume.

2. `workspace-template/.opencode/agents/aitest-diagnosis.md` at reissue parent, blob `66d37d30d8872909fd33ec19ce7b59a327a55a8f`.
   - Diagnosis agent = `aitest-diagnosis`.
   - It uses `aitest_diagnosis`.
   - Failed test/observation is not automatically a confirmed defect.
   - Insufficient evidence must return through governed G2 -> G3/G4 evidence acquisition.
   - Only canonical G5 defect truth may confirm a defect.

3. `docs/reviews/OPENCODE_1_18_3_USER_TURN_CAPABILITY_PROBE.md` at reissue parent, blob `44888d18b96c5f3f7eb8f3d40b6de5b4bfa810c0`.
   - OpenCode v1.18.3 has a real user-message hook.
   - Supported stable pre-LLM short-circuit interception is **NOT_PROVEN**.
   - User text is not completion authority.
   - The supported fallback is Primary Director -> deterministic runtime resolver -> fresh Browser Runtime verification -> canonical HumanGate resolution.

4. `docs/reviews/G1_G5_PACKAGE_WINDOWS_QUALIFICATION_EVIDENCE.md` at `c11208af52d085296494dc26e86ed587be6cef0d`.
   - B1 Windows package compatibility is independently closed by 00.9.
   - Exact OpenCode/Python/Chromium/ripgrep/CodeGraph/Playwright candidates and their Windows compatibility are carry-forward inputs.
   - B1 explicitly did **not** execute B2 real interactive qualification.

5. `docs/reviews/G1_G5_PACKAGE_WINDOWS_INTERACTIVE_QUALIFICATION_EVIDENCE.md` and its JSON at `ac11ee35d198607ed9724b501a26666aedf00f47`.
   - Prior B2 preflight executed zero real Windows runs/user turns and correctly remained BLOCKED.
   - `OPENCODE_WEB_REQUIRED`, `OPENCODE_SIDECAR_REQUIRED`, and `DIRECT_INTERACTIVE_ENTRYPOINT_SUPPORTED` remain unresolved until B2.

If any execution-time observation conflicts with these retrievable frozen/current authorities, execution must STOP and return to 00.9; the test must not be changed to accommodate an implementation drift.

---

## 4. Exact B1-qualified B2 runtime inputs

B2 must carry forward the B1-qualified identities without reselection:

```text
OpenCode = 1.18.3
OpenCode Windows artifact SHA256 = 68bc62930f6cb5755e0409aa9de0bb270a66ed2b8c9cf0c029e9f2287ed5486e
Primary Agent = aitest-director
Diagnosis Agent = aitest-diagnosis

Python = 3.12.10 / snapshot 20250529
Python archive SHA256 = ca22a9a9e64ecab6d0b5de7cdf8b679ccaa41e9def6aaa2b4aaa6bb23ec7aaba

Chromium = 151.0.7922.34
Chromium archive SHA256 = 045621e45a9dd27002c7fc1d8e10fe9f5f71f4cadbf44ec6f397f56f0179725c
Chromium archive size = 201068834

ripgrep = 15.2.0
ripgrep archive SHA256 = 71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5

CodeGraph = 0.20.1
CodeGraph exe SHA256 = aa1b6108217c119af6ac444b8652a0eadcfe2c343bff78ead2edd15b6b7b15b1
onnxruntime.dll SHA256 = 52f8ebe8f08f369a44fed6d1cb680c7c89169795e1c2949ee25b88b538ef0948

Playwright Python = 1.62.0
External browser authority = Chromium 151.0.7922.34
Playwright managed-browser download = FORBIDDEN

@opencode-ai/plugin = 1.18.3
Target-host online dependency installation = FORBIDDEN
```

A B2 run may use a disposable qualification state directory/database/environment binding, but may not change frozen product semantics or create a second durable product truth.

---

## 5. Strict definitions

```text
REAL_WINDOWS =
  native Windows x64 execution substrate controlled/authorized for this qualification;
  NOT Linux, Wine, static inspection, or a Linux-hosted simulation.

REAL_OPENCODE =
  exact B1-qualified OpenCode 1.18.3 Windows candidate executing against the current qualification workspace/package candidate.

REAL_USER_TURN =
  an actual OpenCode user input accepted by the real OpenCode session and processed through the real primary-agent/subagent/tool/runtime path.
```

The following are **not** substitutes for `REAL_USER_TURN`:

```text
CI_COMPATIBILITY_ONLY
DEBUG_CONFIG
AGENT_LIST
DEBUG_AGENT
PROCESS_START_ONLY
TOOL_REGISTRY_STATIC_DISCOVERY_ONLY
FIXTURE_PLAYBACK
STATIC_SOURCE_INSPECTION
DIRECT_PYTHON_CALL_THAT_BYPASSES_OPENCODE_USER_TURN
CONVERSATION_RECONSTRUCTION
```

A real B2 user turn may be driven through a supported OpenCode terminal/TUI/CLI interaction channel on the authorized Windows machine, but the resulting evidence must prove that the turn became an OpenCode session/user message and reached the governed agent/tool/runtime route. Merely piping text to an unrelated process is not sufficient.

---

## 6. Entry conditions

B2 execution may start only when all are true:

```text
B2_CONTRACT = THIS_REISSUED_GIT_NATIVE_CONTRACT
GIT_RECOVERY = EXACT / NO DIVERGENCE
CANONICAL_MAIN = 58e5e1259cd26846b31ea21a8a87df0bcf071edc
B1 = PASS / CLOSED
REAL_WINDOWS_CHANNEL = ESTABLISHED AND AUTHORIZED
REAL_OPENCODE_1_18_3 = AVAILABLE
REAL_PROVIDER_MODEL_BINDING = AVAILABLE FOR REAL USER TURNS
B1_QUALIFIED_OFFLINE_RUNTIME_LAYOUT = AVAILABLE
PRODUCT_SEMANTICS_CHANGE_REQUIRED_BEFORE_RUN = NO
```

Provider/model credentials must never be committed or copied into Evidence. Evidence may record non-secret provider/model identity sufficient to establish that a real model-backed OpenCode turn occurred.

If the Windows channel can only run non-interactive PowerShell/SSH commands but cannot establish/prove real OpenCode user turns and resulting agent/tool routing, the channel is insufficient for B2 and B2 remains BLOCKED.

---

## 7. Mandatory reissued scenarios

All scenario IDs below are **B2R-local** (`R = REISSUED`). They are not claimed to be IDs from the lost contract.

### B2R-S01 — Direct interactive entry and entrypoint boundary resolution

On native Windows, launch exact OpenCode 1.18.3 against the current B2 qualification workspace and submit at least one real user turn through the direct interactive entrypoint.

Must resolve from real execution:

```text
DIRECT_INTERACTIVE_ENTRYPOINT_SUPPORTED = YES | NO
OPENCODE_WEB_REQUIRED = YES | NO
OPENCODE_SIDECAR_REQUIRED = YES | NO
```

No field may remain null/unknown/unresolved in a B2 PASS candidate.

PASS requires that the direct interaction path actually processes a user turn. If direct interaction works without external web/sidecar, record `WEB_REQUIRED=NO` and/or `SIDECAR_REQUIRED=NO` only from that execution evidence, not from source inference.

### B2R-S02 — Primary Director explicit-test-goal real routing

Submit a real OpenCode user turn equivalent to an explicit new test goal, using a disposable qualification scope so no real project truth is polluted.

Must prove:
- `aitest-director` is the actual primary routing authority for the turn;
- the real turn reaches official `aitest_director` action `start_test` or an exact source-backed equivalent in the frozen runtime;
- Mission/Goal truth is created/resolved durably by runtime, not inferred from conversation history;
- any resulting Planner Session is a real governed session, not a mock/session string invented by the test.

Conversation history must not be used as Mission/Plan/Task/Attempt/Session truth.

### B2R-S03 — Continue-test real routing

From the same controlled qualification Mission where valid, submit a real user turn equivalent to `继续测试` / `continue testing`.

Must prove the turn reaches `aitest_director` continuation routing and runtime resolves the existing durable Mission/Plan/Task rather than fabricating a new one or regenerating an already-frozen plan.

If a controlled qualification Mission cannot be safely produced without product mutation, STOP as an execution/qualification blocker rather than bypassing the route.

### B2R-S04 — G3 real tool route

Through a real OpenCode user turn and governed Director path, reach the official G3 surface `aitest_g3_director` and execute a non-destructive/source-backed qualification action such as TestIntent registration where the current tool contract supports it.

PASS requires a real tool call/result, not only permission/config/tool-registry visibility. Focused G3 work must remain inside Mission/Plan/Task/Session governance.

### B2R-S05 — G4 real tool route

Through a real OpenCode user turn and governed Director path, reach the official G4 surface `aitest_g4_director` and execute a non-destructive/source-backed qualification action that proves the real execution/convergence route is callable.

PASS requires a real tool call/result. No fixture playback or direct Python bypass counts.

### B2R-S06 — G5 Diagnosis real route without false defect confirmation

Use a controlled failure/observation input that cannot be mistaken for a real bank defect. Through a real OpenCode user turn, route to `aitest-diagnosis` and its official `aitest_diagnosis` capability.

Must prove:
- the agent/tool route is actually invoked;
- a failed observation is not automatically promoted to confirmed defect;
- insufficient evidence remains insufficient or requests governed evidence through G2 -> G3/G4;
- no second defect truth store is created.

This scenario must **not** claim a confirmed product defect merely to obtain PASS.

### B2R-S07 — HumanGate completion intent is not completion authority

Create or use a controlled qualification Mission with exactly one compatible PENDING HumanGate and associated BrowserContext/HUMAN lease using existing product/runtime APIs without modifying frozen semantics.

Submit a real OpenCode completion-intent user turn such as `完成`, `好了`, `已登录`, or an equivalent credential-safe phrase while the browser condition is deliberately **not yet complete**.

Must prove:
- user text is classified only as `REQUEST_TO_VERIFY_COMPLETION`;
- current Mission comes from R1 durable truth, not conversation memory;
- the official `aitest_human_gate_resume` path is invoked with durable `mission_id` plus current user text;
- fresh Browser Runtime verification runs against the same BrowserContext under HUMAN lease;
- `WAITING_HUMAN` / `NOT_YET_COMPLETE` keeps the HumanGate PENDING;
- no HUMAN->AI lease reclaim occurs on failed verification.

PASS for this negative scenario means the unsafe resume is rejected correctly.

### B2R-S08 — HumanGate verified `RESUME_SAFE` path

Using a controlled qualification HumanGate/BrowserContext, establish the required browser completion condition through the authorized human/browser channel, then submit a new real OpenCode completion-intent turn.

Must prove:
- completion text still acts only as a request to verify;
- fresh Browser Runtime verification of the same BrowserContext succeeds;
- runtime returns/establishes `RESUME_SAFE` according to the frozen HumanGate contract;
- canonical R2.6 HumanGate truth is resolved;
- BrowserLease transitions HUMAN -> AI only after successful fresh verification;
- the same root Attempt/StepCursor is recovered/resumed rather than replaced.

### B2R-S09 — HumanGate ambiguity fail-closed path

Using a disposable qualification state, create a Mission state with multiple compatible PENDING HumanGates only if existing runtime APIs/tests permit this without semantic changes.

Submit a real completion-intent OpenCode turn.

Required outcome is `CLARIFICATION_REQUIRED` or the exact frozen equivalent; runtime/Director must not silently select a gate.

If current frozen runtime makes constructing this adversarial state impossible through supported qualification APIs, B2 cannot silently drop the invariant. Record `B2R-S09 = BLOCKED_BY_QUALIFICATION_STATE_CONSTRUCTION`, return to 00.9, and do not claim overall PASS.

### B2R-S10 — Offline dependency behavior during real turns

Across the real-turn scenarios, prove target-style execution does not require or perform:

```text
pip install on target
playwright install
Playwright managed browser download
npm install on target
online bun install on target
second Chromium download
system Python fallback
system ripgrep fallback
```

The pre-provisioned `.opencode/package-lock.json` and `node_modules` layout must remain stable during target-style OpenCode turns. External Chromium remains the browser authority.

Release-build materialization performed before target-style execution is not target-host installation, but its exact resulting identity must be recorded.

### B2R-S11 — Durable truth / no legacy fallback

For every scenario that creates or resolves Mission/Plan/Task/Attempt/Session/HumanGate state, Evidence must prove that durable runtime truth comes from the R1 Event Stream/current frozen runtime spine.

Forbidden as product truth:
- conversation history;
- legacy `aitest.db`;
- legacy `pfc_harness.py` Mission tables;
- mock Session identifiers;
- a new B2 SQLite/JSON/durable truth store;
- cross-Mission silent merge.

A qualification-only evidence file is allowed; it is not product runtime truth.

---

## 8. Pre-LLM interception boundary

B2 must not depend on a stable supported pre-LLM short-circuit because that capability is `NOT_PROVEN` for OpenCode 1.18.3 by the retrievable probe.

The expected supported path is:

```text
real OpenCode User Turn
-> Primary Director receives the turn as needed
-> deterministic official runtime/tool resolver
-> durable R1 HumanGate/Mission truth
-> fresh Browser Runtime verification
-> fail-closed result
```

If the only way to make B2 pass requires an unsupported/internal short-circuit trick, B2 fails/blocks; the test must not convert that trick into a new product guarantee.

---

## 9. Required Evidence schema

Each mandatory scenario must produce an Evidence row/object with at least:

```text
scenario_id
scenario_contract = PKG0.6B2-REISSUED-2026-09-07
scenario_status = PASS | FAIL | BLOCKED
start_timestamp
end_timestamp
windows_machine_identity (non-secret; OS/arch plus stable qualification locator)
git_head
canonical_main_observed
opencode_version
opencode_binary_sha256 or exact B1-qualified artifact reference
provider_model_identity (non-secret)
opencode_session_id (when exposed by OpenCode)
user_turn_id/message_id (when exposed)
user_turn_input (credentials/secrets redacted only)
selected_primary_agent
selected_subagent (if any)
tool_calls[] with tool/action/result identity
mission_id (when used)
plan_id/task_id/attempt_id/session_id (when used/exposed)
human_gate_id (when used)
browser_context_id (when used)
browser_lease_before/after (when used)
browser_fresh_verification_result (when used)
r1_event_refs_or_digests[] (when durable runtime state is involved)
stdout_stderr_or_structured_result_refs
screenshots_or_recording_refs (optional/supplemental)
offline_mutation_observation
pass_fail_reason
```

Screenshots/recordings may supplement but never replace structured runtime/Git/OpenCode evidence. Evidence must not contain passwords, API keys, cookies, bank credentials, CAPTCHA secrets, private tokens, or other secrets.

The final B2 Evidence set must also contain:

```text
B2_EXECUTION_SOURCE_HEAD
B2_CONTRACT_COMMIT
B2_CONTRACT_BLOB
REAL_WINDOWS_RUN_OR_SESSION_LOCATOR
REAL_OPENCODE_SESSION_LOCATOR
REQUIRED_SCENARIO_MANIFEST
REQUIRED_SCENARIO_COUNT
PASS_COUNT
FAIL_COUNT
BLOCKED_COUNT
DIRECT_INTERACTIVE_ENTRYPOINT_SUPPORTED = YES | NO
OPENCODE_WEB_REQUIRED = YES | NO
OPENCODE_SIDECAR_REQUIRED = YES | NO
PRODUCT_SEMANTICS_MODIFIED = NO | YES
```

---

## 10. Fail-closed gate semantics

B2 must remain `BLOCKED` or become `FAIL` if any of the following is true:

```text
any mandatory B2R scenario not executed or not conclusively mapped
any mandatory scenario FAIL/BLOCKED
real Windows not established
real OpenCode 1.18.3 not used
real user-turn proof missing
required provider/model real-turn path missing
DIRECT_INTERACTIVE_ENTRYPOINT_SUPPORTED unresolved
OPENCODE_WEB_REQUIRED unresolved
OPENCODE_SIDECAR_REQUIRED unresolved
online target-host dependency install required
managed Playwright browser downloaded/used
conversation-only HumanGate completion accepted
fresh Browser Runtime verification bypassed
HumanGate ambiguity silently auto-selected
legacy/second durable truth used
cross-Mission silent merge observed
canonical main drift observed
B1-qualified binary/dependency identity conflict observed
product/source semantic patch required to make the exact candidate pass
```

Classification rules:

```text
NOT_EXECUTED != PASS
NOT_EXECUTED != FAIL unless the contract required execution and the run has otherwise completed;
for gate aggregation a required NOT_EXECUTED scenario prevents PASS and yields BLOCKED.

UPSTREAM/EXECUTION_SUBSTRATE_BLOCKER != DOWNSTREAM_PRODUCT_FAILURE
TEST_FAIL != CONFIRMED_DEFECT
USER_TEXT != HUMAN_GATE_COMPLETION_AUTHORITY
CI_B1_PASS != B2_INTERACTIVE_PASS
```

Architecture/frozen-semantic violations require immediate STOP and 00.9 review. Do not repair tests to match drift.

---

## 11. Completion rule

`PKG0_6B2 = PASS_CANDIDATE` may be emitted only if:

```text
ALL B2R-S01..B2R-S11 = PASS
REAL_WINDOWS = PROVEN
REAL_OPENCODE_1_18_3 = PROVEN
REAL_USER_TURN_PATHS = PROVEN
DIRECT_INTERACTIVE_ENTRYPOINT_SUPPORTED = YES | NO (resolved)
OPENCODE_WEB_REQUIRED = YES | NO (resolved)
OPENCODE_SIDECAR_REQUIRED = YES | NO (resolved)
OFFLINE_TARGET_BEHAVIOR = PASS
R1_DURABLE_TRUTH_INVARIANTS = PASS
HUMANGATE_NEGATIVE_AND_RESUME_PATHS = PASS
PRODUCT_SEMANTICS_MODIFIED = NO
CANONICAL_MAIN_DRIFT = NO
```

After execution, create/push a B2 Evidence commit and STOP. Return to `00.9` for independent Review.

```text
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED_BY_B2_WORKITEM
PKG1 = HOLD
LOCAL_VALIDATION = HOLD
G6 = HOLD
```

Only 00.9 may independently review the B2 Evidence and subsequently decide Package Identity Freeze / PKG1 authorization.

---

## 12. Permitted and prohibited changes during B2

Permitted without new semantic authorization:
- qualification-only evidence files;
- temporary/disposable qualification state generated through existing runtime APIs;
- credential-safe execution capture;
- narrowly scoped qualification helper only if 00.9 separately authorizes it before use.

Prohibited:
- canonical main modification;
- G1-G5 semantic changes;
- Agent/Tool semantic repair to make B2 pass;
- dependency version/artifact reselection;
- `runtime-lock.json` canonicalization;
- `PACKAGE_MANIFEST.json` canonicalization;
- production launcher/final package construction;
- a second runtime/defect/session durable truth;
- PKG1, Local Validation, or G6 execution.

If a prohibited change appears necessary, STOP with a precise blocker/root-cause classification and return to 00.9.

---

## 13. Authority handoff

After 00.9 publishes and independently reads back this file:

```text
B2_CONTRACT_AUTHORITY_RECOVERY_REPAIR = PASS
B2_CONTRACT = REISSUED / FROZEN
ORIGINAL_EQUIVALENCE = NOT_CLAIMED
B2_EXECUTION = STILL_BLOCKED UNTIL REAL_WINDOWS_INTERACTIVE_CHANNEL_ESTABLISHED
```

A subsequent B2 execution WorkItem must start from the exact Git head containing this frozen reissued contract, verify its blob identity, then execute this contract without reconstructing requirements from conversation history.
