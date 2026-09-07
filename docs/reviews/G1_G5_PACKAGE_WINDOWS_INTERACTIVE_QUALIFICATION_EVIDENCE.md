# G1-G5 Package Windows Interactive Qualification Evidence

WorkItem: `10.PKG.5 | PKG0.6B2 Post-B1 Real Windows Interactive Qualification`  
Date: 2026-09-07  
Governance Authority: `00.9` only  
Scope: `POST_B1_REAL_WINDOWS_INTERACTIVE_QUALIFICATION`  
Disposition: **`PKG0_6B2 = BLOCKED` / STOP before interactive execution / return to 00.9.**

This is a preflight blocker record, not a Windows execution report, a replacement B2 contract, a package identity freeze, or a B2 PASS candidate. No real OpenCode user turn was executed in this WorkItem.

## 1. Exact Git recovery

| Item | Live observation |
|---|---|
| Repository | `TongAITech/opencode-test-digital-employee` |
| Canonical main | `58e5e1259cd26846b31ea21a8a87df0bcf071edc` |
| Packaging branch | `work/local-validation-package` |
| Authorized and observed starting head | `c11208af52d085296494dc26e86ed587be6cef0d` |
| Starting commit parent / B1 Windows authority | `9a52e33204c51f8e5f15ea8b6c2c60d533103d95` |
| Starting commit message | `docs(pkg): record repaired Windows qualification evidence` |
| Starting tree | `fe50c9033a890ca40bf3de41b94a01efa74cf597` |
| Starting commit diff | Only `docs/reviews/G1_G5_PACKAGE_WINDOWS_QUALIFICATION_EVIDENCE.md`, added, 225 lines |
| Recovery divergence | NONE |

These observations came from live GitHub connector reads. The local container's `git ls-remote` attempt failed with `Could not resolve host: github.com`; that did not invalidate the successful connector reads and is not classified as a product defect.

The current WorkItem authorization reports the 00.9 B1/B1R closure and B2 authorization. Those dispositions are carried forward, not re-reviewed or rewritten here. The existing B1 document's earlier PASS_CANDIDATE wording is not modified. No historical conversation is used to reconstruct the missing B2 contract.

## 2. B1 carry-forward, not B2 evidence

Live run metadata for `34079065820` returned `completed / success`, branch `work/local-validation-package`, exact execution head `9a52e33204c51f8e5f15ea8b6c2c60d533103d95`. Existing B1 Evidence records Windows job `101610757980`, runner self-tests `22/22 PASS`, qualification matrix `24/24 PASS`, and `WINDOWS_INTERACTIVE_QUALIFICATION = NOT_EXECUTED / PKG0.6B2`. Cleanup job `101610723780` is carried from the current WorkItem instruction; it was not re-executed here.

Existing dependency versions, archive identities and the Chromium identity remain the B1-qualified candidates. They were not downloaded again, remeasured, reselected, or frozen here. `debug config`, `agent list`, `debug agent`, tool discovery and B1 process probes are not counted as real B2 user turns.

## 3. Blocker A: required frozen contract not retrieved

Required record: **`10.1.PKG.2.1 | PKG0.6B2 Gate Authorization & Evidence Contract`**.

The exact-head repository root and the `docs/governance`, `docs/reviews`, `docs/history`, `packaging`, and `tools` trees were inspected; `workspace-template` root was also inspected. No retrievable record matching the required B2 title was identified in those inventories. Relevant package-identity and B1 documents, plus the historical OpenCode User-Turn Probe, were read. They do not supply the referenced full B2 contract.

Supplementary GitHub default-branch code search for `PKG0.6B2`, repository issue search for `"PKG0.6B2"`, and commit-message search for `B2` returned no matches. Default-branch search is not represented as exhaustive packaging-branch content search. Three File Library search batches using the exact title, B2 identifier and English/Chinese qualification terms returned no relevant contract. Locator-only context recovery supplied no retrievable formal source; no conversation text was promoted to contract authority.

This is **a retrieval gap, not a claim that the contract does not exist or that B2 authorization is invalid**. Its immutable locator, complete scenarios, required real user turns and original evidence schema were not available for mapping. The WorkItem therefore did not invent scenario IDs, scenario counts, replacement acceptance criteria, or a substitute runner.

Report-local classification: `B2_FROZEN_CONTRACT_NOT_RETRIEVED / GOVERNANCE_INPUT_RECOVERY_BLOCKER`. This label does not amend any frozen contract.

## 4. Blocker B: real Windows interactive execution channel not established

The current local execution environment actually returned `Linux` from `uname -s`; a second local platform observation also returned `Linux`. No authorized real-Windows interactive device/session channel was established in this session. Capability discovery found an optional unconnected remote-execution integration; nothing was installed or connected and no device access was assumed.

The existing B1 Actions workflow is a compatibility runner, not an established B2 interactive channel. It was neither modified nor dispatched. Its push filter covers only its workflow file and `tools/package_windows_qualification.ps1`, not these evidence-only files. A Linux run, a new compatibility-only CI job, replay fixtures, direct Python calls, an OpenCode startup, or debug-agent output were not substituted for B2.

Report-local classification: `B2_REAL_WINDOWS_INTERACTIVE_CHANNEL_NOT_ESTABLISHED / EXECUTION_SUBSTRATE_BLOCKER`. No OpenCode compatibility, Agent routing, Tool invocation, HumanGate or other product-semantic failure was established. No product repair was attempted.

## 5. Unresolved boundaries and zero-execution accounting

| Required boundary | B2 result |
|---|---|
| `OPENCODE_WEB_REQUIRED` | UNRESOLVED / NOT_EXECUTED |
| `OPENCODE_SIDECAR_REQUIRED` | UNRESOLVED / NOT_EXECUTED |
| `DIRECT_INTERACTIVE_ENTRYPOINT_SUPPORTED` | UNRESOLVED / NOT_EXECUTED |

The required final domain remains `YES | NO`. Because execution is blocked, the accompanying JSON records `null` with explicit unresolved status; **null must never be coerced to NO**. This is not a relaxation allowing an unresolved PASS. The older package-identity candidate's source-backed direct-entry `YES` is retained as historical candidate evidence, not upgraded into a B2 real-Windows result.

`REAL_WINDOWS_RUNS = 0`; `REAL_OPENCODE_USER_TURNS = 0`; `INTERACTIVE_SCENARIOS_EXECUTED = 0`. The contract scenario total is unknown, not zero. There is no B2 execution commit, run/job ID, OpenCode session ID, user-turn ID, tool-call ID, screenshot, recording or raw Windows execution artifact. No empty matrix is treated as PASS.

The historical HumanGate capability probe remains historical evidence only: user text such as `完成` requests verification, not completion authority; fresh Browser Runtime verification remains necessary. No new HumanGate verification was performed here.

## 6. Evidence identity and scope

Machine-readable stop record: `G1_G5_PACKAGE_WINDOWS_INTERACTIVE_QUALIFICATION_RESULT.json`  
SHA256: `37238d7959dda1c2d94e966f7f1a9ae79eb1b13598961fc1809c595b6882ad8c`

The JSON format is local to this blocker report. It does not claim to implement or replace the unavailable frozen B2 evidence schema. Its observations are normalized records of the described tool reads, not byte-for-byte raw Windows logs.

The evidence commit is intended to contain exactly these two added files:

- `docs/reviews/G1_G5_PACKAGE_WINDOWS_INTERACTIVE_QUALIFICATION_EVIDENCE.md`
- `docs/reviews/G1_G5_PACKAGE_WINDOWS_INTERACTIVE_QUALIFICATION_RESULT.json`

Its parent must be `c11208af52d085296494dc26e86ed587be6cef0d`. The enclosing Git commit and its diff identify the report; they are not a Windows execution authority. Publication uses a non-forced fast-forward after rechecking the authorized branch head. No main, runtime lock, PACKAGE_MANIFEST, final launcher, Agent/Tool, G1-G5 source, workflow, runner, dependency candidate or governance record is modified. Protected starting Git object IDs are recorded in the JSON for independent scope comparison.

Only local JSON/record consistency is checked. No product test or PKG0-through-B1 qualification is re-run.

## 7. Return to 00.9

00.9 must review this BLOCKED record and restore the original frozen B2 contract through a retrievable formal source with immutable identity, together with an authorized execution channel that can satisfy that contract's actual Windows/OpenCode/user-turn scenarios. The request is to recover existing inputs, not redesign B2 or reduce its requirements. Credentials must not be pasted into evidence.

After those prerequisites are restored, resume against the accepted exact source/candidate identities and the unchanged original contract. Any real compatibility or semantic blocker must STOP and be classified rather than hidden by changing tests.

```ini
PKG0_6B2 = BLOCKED
B2_REAL_INTERACTIVE_EXECUTION = NOT_EXECUTED
B2_INDEPENDENT_REVIEW = REQUESTED_FROM_00.9
PACKAGE_IDENTITY_FREEZE = NOT_AUTHORIZED
PKG1 = HOLD
LOCAL_VALIDATION = HOLD
G1_G5_REOPEN_REQUIRED = NO
G6 = HOLD
```

## 8. Git-native source locators

All repository file references below are pinned to `c11208af52d085296494dc26e86ed587be6cef0d` unless another exact authority is shown.

- Starting commit: https://github.com/TongAITech/opencode-test-digital-employee/commit/c11208af52d085296494dc26e86ed587be6cef0d
- B1 Evidence: https://github.com/TongAITech/opencode-test-digital-employee/blob/c11208af52d085296494dc26e86ed587be6cef0d/docs/reviews/G1_G5_PACKAGE_WINDOWS_QUALIFICATION_EVIDENCE.md
- Successful B1 run: https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/34079065820
- Package identity candidate, sections 6-7: https://github.com/TongAITech/opencode-test-digital-employee/blob/c11208af52d085296494dc26e86ed587be6cef0d/docs/governance/G1_G5_LOCAL_VALIDATION_PACKAGE_IDENTITY_CANDIDATE.md
- Historical User-Turn Probe: https://github.com/TongAITech/opencode-test-digital-employee/blob/c11208af52d085296494dc26e86ed587be6cef0d/docs/reviews/OPENCODE_1_18_3_USER_TURN_CAPABILITY_PROBE.md
- B1 workflow: https://github.com/TongAITech/opencode-test-digital-employee/blob/c11208af52d085296494dc26e86ed587be6cef0d/.github/workflows/g1-g5-package-windows-qualification.yml
- Governance tree: https://api.github.com/repos/TongAITech/opencode-test-digital-employee/git/trees/851897873e82b9624c42de54aab124002560f3c8
- Review tree: https://api.github.com/repos/TongAITech/opencode-test-digital-employee/git/trees/3c26f5c64a8d429651ce383a63303bdf5b5440ae
