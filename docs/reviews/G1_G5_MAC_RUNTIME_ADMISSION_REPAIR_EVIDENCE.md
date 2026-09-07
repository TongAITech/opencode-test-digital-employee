# 10.MAC.2R — OpenCode ToolResult and Canonical Truth Envelope Repair Evidence

Governance Authority: `00.9｜ChatGPT Harness 总控与架构治理｜G5-G6`.

Disposition: **Repair + fresh Mac M2-R3 admission PASS; STOP for independent 00.9 review.**

`MAC_EVIDENCE = NON_B2_AUTHORITY`; `MAC_PASS != PKG0_6B2_PASS`.

## R0 recovery and frozen authority

The initial STOP was independently reclassified by 00.9 as a legacy checkout selection issue, not canonical branch drift. The user checkout `/Users/tatu/Documents/opencode-test-digital-employee` was excluded and not modified. No reset, clean, force checkout, or force push was performed.

Fresh independent repair checkout: `/Users/tatu/aitest-runtime/mac-2r-repair`.
Local branch: `work/local-validation-package`; initial clean HEAD and remote packaging HEAD: `17e7500a6e648c35481d9a26638adfeea5d3c00b`.
Remote main: `58e5e1259cd26846b31ea21a8a87df0bcf071edc`.

Repair authorization at initial HEAD: `docs/governance/00.9_MAC_RUNTIME_ADMISSION_REPAIR_AUTHORIZATION.md`, blob `e90ba3df130693ab04b6b6f2aec6bf2bf32b718f`.
Frozen B2 contract blob: `ab16ecee1493d2bee2a05f0e9e02a3c19c83a5ad` (contract commit `43b653f5a867658f65687d38ab8a5cf656eec8fa`).
User recovery authorization specifies the authorization-bearing commit as the exact start; it supersedes the historical pre-repair head wording within that document.

## R1 repair and source preservation

The three bridges serialize domain results to JSON strings only after their existing parse/truth checks. The shared pending result is also serialized, retaining HOLD and its original fields. All 17 exported tools are covered, including Director, G3, G4, Diagnosis/G5, PFC truth/command and HumanGate resume. Exceptions continue to throw.

`interactive_truth()` now applies one canonical envelope around an internal target-result helper. The target-specific body is byte-for-byte unchanged; statuses including NO_MISSION, INVALID_TARGET, HOLD and PENDING_PRODUCTIZATION remain intact. The strict PFC guard is byte-for-byte unchanged, including its strict boolean requirement.

No runtime authority, agent semantics, launcher, provider/model selection, version pin, manifest, runtime lock, canonical main or frozen runner was changed. The new tests are construction evidence; they do not substitute for the real hosted turn.

### Repair commit

```text
REPAIR_COMMIT = 84930cb7e6ae26c1f7d2e8cf51f0734e7e3096ef
REMOTE_HEAD_AFTER_REPAIR = 84930cb7e6ae26c1f7d2e8cf51f0734e7e3096ef
```

The commit was pushed and independently matched by `git ls-remote` before fresh workspace creation. The later evidence-only commit is separate.

Changed files:

- `workspace-template/.opencode/tools/aitest.ts`
- `workspace-template/.opencode/tools/aitest_human_gate.ts`
- `workspace-template/.opencode/tools/pfc.ts`
- `workspace-template/.pfc-internal-field-validation/tests/test_interactive_truth_envelope.py`
- `workspace-template/.pfc-internal-field-validation/tests/test_opencode_tool_result_contract.mjs`
- `workspace-template/ai-test/runtime/aitest_runtime/product_entry.py`

## R2 validation

- New ToolResult test: PASS, 17 exports; declared and pending actions preserve nested payloads, ids, references and PASS/HOLD/FAIL/INVALID_TARGET/NO_MISSION states. Subprocess, parse, truth, path and Python errors remain failures. PFC rejects missing/false/string/numeric/null `conversation_is_not_truth`.
- New truth-envelope test: PASS, 27 named checks plus normalization/filter assertions; empty and populated R1 states for all targets, all target return statements exercised, exceptions propagated, legacy sentinel unchanged and no secondary workspace spine.
- The frozen original ToolResult implementation fails the new assertion (EXPECTED_RED), independently confirming regression sensitivity.
- Frozen `tools/run_wave2_validation.py`: **434/434 PASS**.
- `tools/run_g5_validation.py --mode green`: **PASS**, all six suites including product, recovery, adversarial, HumanGate/duplicate, same-Mission E2E and OpenCode surface.
- Supplementary G5 OpenCode surface and G4 HumanGate surface: PASS.

Initial regression attempts failed because default Git 2.23.0 did not support `git init -b` used by the fixtures. Both complete runners were rerun with the existing `/usr/bin/git` 2.50.1 first in PATH and passed. Initial failure artifacts remain preserved. No old test was edited to accommodate the repair.

Frozen runner blob remains `b006cecb48673a5b8735dda9e1b645ebafe7f1fc`; the G5 runner also remains unchanged. Commands used the existing portable Python 3.12.10:

```sh
node --experimental-vm-modules workspace-template/.pfc-internal-field-validation/tests/test_opencode_tool_result_contract.mjs
<portable-python> workspace-template/.pfc-internal-field-validation/tests/test_interactive_truth_envelope.py
PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin <portable-python> tools/run_wave2_validation.py --root . --output <evidence>/wave2-git250.json
PATH=/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin <portable-python> tools/run_g5_validation.py --root . --mode green --output <evidence>/g5-git250.json
```

## R4 fresh real Mac admission

Fresh workspace: `/Users/tatu/aitest-runtime/workspace/mac-2r`, extracted using `git archive` from the pushed repair commit. Every archived source file retains its hash after the turn. The independent state directory was absent before creation and empty before the turn.

Portable Python was freshly extracted from the previously verified exact upstream archive. Python: `3.12.10`; archive SHA256 `d0d51fa22c0e99b58de1b1b4baeca467d6fd0a1424c7509ea280c0796306c481`.
OpenCode: `1.18.3`, upstream authority `c69abee0c73253aebae65e87e4e1b9bfa8c38021`; installed binary SHA256 `ba11415d6af7efc9dc0073520d546b869711da5f39076d12e08eeb266ba1279b`. Existing exact plugin `1.18.3` dependencies were reused as derived runtime payload.

Explicit environment:

```text
AITEST_WORKSPACE_ROOT=/Users/tatu/aitest-runtime/workspace/mac-2r
AITEST_RUNTIME_SPINE_DB=/Users/tatu/aitest-runtime/state/mac-2r-rehearsal/runtime-spine.db
HTTP_PROXY=http://127.0.0.1:2080
HTTPS_PROXY=http://127.0.0.1:2080
NODE_EXTRA_CA_CERTS=/Users/tatu/aitest-runtime/certs/macos-trusted.pem
OPENCODE_DISABLE_AUTOUPDATE=1
OPENCODE_DISABLE_MODELS_FETCH=1
```

A real `opencode run -m opencode/big-pickle --format json` user turn used the unchanged workspace default agent. It requested exactly the two read-only admission calls, preservation of domain status, and immediate stop. No debug/fixture/direct-Python invocation was used as admission evidence. Process exit: 0; stderr: empty.

Native session: `ses_f8508a46effeD2eRNTk6EYVk69`.
Native user message: `msg_07af75c00001gjGKn0uTT9Ozqq`.
Final assistant message: `msg_07af787910010emNcwylO4a9vo`; finish: `stop`.
Native session/message metadata confirms version `1.18.3`, agent `aitest-director`, provider `opencode`, model `big-pickle` and real model token usage. The native tool events, not the conversation's narrative, establish tool completion and output.

| Hosted tool invocation | Host state | Domain status | truth_source | conversation_is_not_truth |
|---|---|---|---|---|
| aitest_director(action=status) | completed, untruncated | PASS | R1_EVENT_STREAM | true |
| pfc_truth(target=project) | completed, untruncated | PENDING_PRODUCTIZATION | R1_EVENT_STREAM | true |

`PFC_TRUTH_PROJECT=PASS` refers to admission/contract success, not project productization. No business status was upgraded.

Exact decoded hosted outputs:

```json
{
  "aitest_director": {
    "conversation_is_not_truth": true,
    "g2_1_session_management": {
      "agent_owns_session_lifecycle": false,
      "bank_opencode_observation_field_validation": "PENDING",
      "session_router": "RUNTIME_OWNED",
      "session_supervisor": "CONTROL_LOOP_OWNED"
    },
    "mock_session_fallback": "FORBIDDEN",
    "runtime_db": "/Users/tatu/aitest-runtime/state/mac-2r-rehearsal/runtime-spine.db",
    "schema_version": "aitest.r2.autonomous-orchestration.v1",
    "status": "PASS",
    "truth_source": "R1_EVENT_STREAM"
  },
  "pfc_truth": {
    "conversation_is_not_truth": true,
    "gate": "R5_PRODUCTIZATION",
    "legacy_fallback": "FORBIDDEN",
    "status": "PENDING_PRODUCTIZATION",
    "target": "project",
    "truth_source": "R1_EVENT_STREAM"
  }
}
```

All specified blockers were absent: `undefined is not an object`, `AITEST_CANONICAL_RUNTIME_PATH_NOT_FOUND`, `PFC_PORTABLE_PYTHON_NOT_FOUND`, `CANONICAL_RUNTIME_AUTHORITY_UNRESOLVED`, and `PFC_CANONICAL_TRUTH_QUERY_FAILED`.

Independent read-only R1 inspection: SQLite integrity `ok`; only schema/extension migration tables contain rows. Mission, Goal, Plan, Task, Attempt, Session, events, commands and HumanGate tables remain empty. There is no database inside the fresh workspace. No downstream scenario was executed.

## R5 evidence and final gates

Raw local evidence directory: `/Users/tatu/aitest-runtime/evidence/mac-2r`. This document embeds the key hosted outputs and native identifiers; full local logs and hash manifest remain available for independent review.

Evidence SHA256:

- `recovery-integrity.json`: `21d5ed51e9451d8d4df2056e7e1067d73708d983cd064fd38806f4934893ef91`
- `focused-tool-result.json`: `af8508497362af2743a0913d0ffdd9a622c0b1b2e343d06f60c67b547215a50d`
- `focused-truth.json`: `e5d579241debd87c016e3aa5c5266194ad67e345986b2bb14009a410b92106f5`
- `baseline-tool-result-red.json`: `0457fe56004ab20a36fbdaa8a5cea0137aac8e32ffd12c6c9155b7268e109735`
- `wave2-git250.json`: `3bee8ca69216c33d7d1fe1c44eaa80a006ac90162b76dacc20251360c8833ff0`
- `g5-git250.json`: `37b209fdda3beeb7fea5098459d7f91b71ea89902f02860c1955aa7fd8b4cb18`
- `g5-surface.json`: `3591a0c4dca0da2de766f0c726e2ab8686d3983a97a29bc0c9a62b9fc9ba6839`
- `humangate-surface.json`: `793d805c3ffcb1f28309f6931e28e28cde2387f72d3caa09256a3cb38feef1d4`
- `fresh-substrate.json`: `d554ebca85424cd824e37dcb673a8ef3057afa20d984dabc3084eeaa8fa87709`
- `runtime-admission.jsonl`: `23d4768ebfe0d7c7a4aa98feef3a32f418acccc724945f9980a38ca5dd6fb193`
- `runtime-admission.stderr`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `native-session-metadata.json`: `10847cbe9e65cf15b8558e42126519bdd8f36e552c9f702200115c3fd77620a6`
- `post-admission-integrity.json`: `a66031c028f1033d2f876f802c11a4ef66e32fdad843b55bd6fec6202746ecaa`
- `result.json`: `a186b53f2d2b1c625a49592025f9e00dc83d95d76717e89f93752783a1c8ce20`

Final disposition:

```text
REAL_OPENCODE_SESSION = PASS
REAL_USER_TURN = PASS
AITEST_DIRECTOR_STATUS = PASS
PFC_TRUTH_PROJECT = PASS
RUNTIME_ADMISSION = PASS
MAC_EVIDENCE = NON_B2_AUTHORITY
MAC_PASS != PKG0_6B2_PASS
PKG0_6B2 = BLOCKED_PENDING_REAL_WINDOWS_INTERACTIVE_CHANNEL
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
PKG1 = HOLD
LOCAL_VALIDATION = HOLD
G6 = HOLD
```

STOP / return 00.9 independent review. M-S02/M-S03/M-S04/M-S05/M-S06/M-S10, HumanGate M-S07/M-S08/M-S09, Windows B2 and PKG1 were not entered and are not authorized by this result.
