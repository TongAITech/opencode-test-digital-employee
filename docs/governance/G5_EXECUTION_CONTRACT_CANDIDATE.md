# G5 — Execution Contract Candidate

**Status:** `EXECUTION_CONTRACT_CANDIDATE / REVIEW_REQUIRED / NOT_FROZEN`  
**WorkItem:** `10.G5｜Defect Truth & Autonomous Defect Hunter`  
**Governance Authority:** `00.9｜ChatGPT Harness 总控与架构治理｜G5-G6` as successor to all still-effective `00.8` Governance Authority  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical frozen main:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Engineering branch:** `work/g5-defect-truth`  
**Draft PR:** `#2 / MUST_REMAIN_DRAFT_OPEN_UNMERGED`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`  
**Frozen G5 CodeContract identity:** `584b86980c7b0ce93353a37f4e1b76891ca639e0`  
**Frozen CodeContract file:** `docs/governance/G5_DEFECT_TRUTH_AND_AUTONOMOUS_DEFECT_HUNTER_CODE_CONTRACT_CANDIDATE_V2.md`  
**Contract Review evidence:** PR #2 comment `00.9 — G5 CONTRACT REVIEW PASS / CODE CONTRACT FROZEN`  
**Reviewed pre-Execution-Contract branch head:** `296b9408c2a11261ea4541454a4b88347cc7d05d`  

```text
G5_CONTRACT_REVIEW = PASS
G5_CODE_CONTRACT_FROZEN = YES
FROZEN_CODE_CONTRACT_IDENTITY = 584b86980c7b0ce93353a37f4e1b76891ca639e0
EXECUTION_CONTRACT = AUTHORIZED_TO_DRAFT
IMPLEMENTATION_STARTED = NO
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
G6 = HOLD
BANK_INTERNAL_PILOT_READY = NO
```

> This Execution Contract Candidate may sequence and operationalize the frozen CodeContract. It MUST NOT reinterpret, weaken, extend, or replace any frozen G5 CodeContract requirement. Construction remains forbidden until this Execution Contract is reviewed/frozen and the subsequent Pre-Execution Drift Check passes.

---

# 1. Execution objective

The implementation objective is to realize the frozen G5 integration/application layer exactly as contracted:

```text
G2/G2.1 governed Task + Router + Session
        ↓
G4 Observation / Oracle / Evidence
        ↓
R3.6 TestAnomaly
        ↓
DefectCandidate + alternatives
        ↓
bounded evidence deepening
        ↓
cross-source correlation
        ↓
reproducibility OR durable causal proof
        ↓
false-positive exclusion
        ↓
DefectAssessment
        ↓
RCA
        ↓
R4.3 ConfirmedDefectLifecycle
```

When frozen policy requires human confirmation, canonical R2.6 HumanGate is inserted before the R3.6 `CONFIRMED_DEFECT` write and must become canonically allowing before G5 continues.

This Execution Contract is specifically designed to prevent the previously observed failure mode where runtime code, tests, and frozen contract drift apart. The execution order is therefore:

```text
freeze truthful RED oracle
-> add minimum authorized integration surfaces
-> make each frozen behavior GREEN in dependency order
-> prove negative/adversarial boundaries
-> prove same-Mission E2E
-> run full frozen regression
-> return Engineering PASS candidate for independent closure review
```

---

# 2. Frozen invariants carried into execution

Every construction wave MUST preserve:

```text
TEST_FAIL != CONFIRMED_DEFECT
SINGLE_500 != CONFIRMED_DEFECT
ERROR_STRING != DEFECT_IDENTITY
LLM_CONFIDENCE != DEFECT_TRUTH
STATIC_CODE_JUDGMENT != DEFECT_TRUTH
G4_EXECUTION_OBSERVATION != G5_DEFECT_TRUTH
G5 != G4_EXECUTOR
G5 != G3_CASE_AUTHORITY
G5 != R4_3_FIX_AUTHORITY
G5 != G6_CLOSED_LOOP
AGENT != SESSION_LIFECYCLE_OWNER
R1_EVENT_STREAM = SOLE_DURABLE_RUNTIME_TRUTH
```

Forbidden as G5 Product Truth/write authority:

```text
aitest_runtime/defects.py
legacy defect SQL tables
aitest.db
new G5 SQLite/SQL/JSON defect store
new G5 durable Event extension duplicating R3.6/R4.3
AUTO_CONFIRMED heuristic path
```

`canonical_runtime.canonical_extension_manifests()` MUST NOT gain a G5 durable extension.

Any implementation pressure to weaken these rules is `STOP / REPLAN_REQUIRED`, not an engineering workaround.

---

# 3. Authorized construction surface

## 3.1 New G5 integration package

Construction may add exactly:

```text
workspace-template/ai-test/runtime/aitest_runtime/g5/
    __init__.py
    contracts.py
    admission.py
    policy.py
    service.py
```

Responsibilities remain frozen:

- `contracts.py` — non-durable integration envelopes/results only;
- `admission.py` — exact G4 fact admission and R3.6 mapping;
- `policy.py` — confirmation, HumanGate, duplicate/canonical-defect policy;
- `service.py` — facade composing the existing shared RuntimeService and frozen authorities;
- `__init__.py` — stable imports only.

## 3.2 Existing product/integration files allowed to change

```text
workspace-template/ai-test/runtime/aitest_runtime/product_entry.py
workspace-template/ai-test/runtime/aitest_runtime/g2_1/router.py
workspace-template/.opencode/tools/aitest.ts
workspace-template/.opencode/agents/aitest-diagnosis.md   # wording only if required
workspace-template/.pfc-internal-field-validation/tests/test_g5_*.py
tools/<additive G5 validation runner or additive canonical-runner extension>
```

Governance/review evidence files under `docs/governance/` and `docs/reviews/` may be added as non-runtime evidence.

## 3.3 Frozen source that is not authorized for semantic change

No semantic rewrite is authorized in:

```text
aitest_runtime/r3_6/**
aitest_runtime/r4_3/**
aitest_runtime/r2_6/**
aitest_runtime/g3/**
aitest_runtime/g4/**
canonical Runtime/Event Stream truth semantics
existing G1-G4 test oracle semantics
```

If an implementation cannot satisfy the frozen CodeContract without changing any of these semantics, construction MUST stop and report exact source conflict for governance review.

---

# 4. Branch, commit, and working-tree discipline

All construction occurs only on:

`work/g5-defect-truth`

Rules:

1. `main` MUST remain exactly `4edd78536633d4258705c6083fe55b44e51f54bb` during G5 construction.
2. PR #2 MUST remain Draft / OPEN / UNMERGED.
3. Do not create or switch to another engineering/planning branch.
4. Do not merge, rebase onto a changed main, or rewrite frozen governance history during implementation.
5. Each execution wave below MUST end in an independently auditable commit.
6. A repair may be a separate follow-up commit for the same wave; it MUST NOT silently rewrite or weaken the frozen test oracle.
7. No wave may include unrelated cleanup/refactoring.
8. No generated package/ZIP or local Construction copy becomes Engineering Truth; Git commit/diff remains the sole engineering source truth.

Recommended commit prefixes:

```text
test(g5): freeze ...
feat(g5): add ...
fix(g5): repair ...
docs(g5): record ...
```

---

# 5. Execution state machine

The authorized state progression is:

```text
EXECUTION_CONTRACT_CANDIDATE
-> EXECUTION_CONTRACT_REVIEW
-> EXECUTION_CONTRACT_FROZEN
-> PRE_EXECUTION_DRIFT_CHECK
-> READY_FOR_CODEX
-> EC0_RED_ORACLE
-> EC1_ROUTER_AND_CONTRACTS
-> EC2_PRODUCT_SEAM_AND_WORKER_BINDING
-> EC3_G4_ADMISSION_AND_R3_6_PIPELINE
-> EC4_GOVERNED_EVIDENCE_AND_RECOVERY
-> EC5_HUMAN_GATE_DUPLICATE_R4_3
-> EC6_OPENCODE_DIAGNOSIS_SURFACE
-> EC7_E2E_ADVERSARIAL_FULL_REGRESSION
-> ENGINEERING_EVIDENCE_REVIEW
-> ENGINEERING_PASS_CANDIDATE
```

The WorkItem MUST NOT skip directly from Execution Contract drafting to implementation.

---

# 6. EC0 — Freeze truthful RED oracle before product construction

**Purpose:** make the frozen CodeContract executable as tests before product implementation, preventing stale-oracle drift.

## Allowed changes

Only additive tests and, if needed solely to invoke those tests, additive test helpers/runner registration:

```text
workspace-template/.pfc-internal-field-validation/tests/test_g5_product_path.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_worker_binding_and_recovery.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_adversarial_defect_truth.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_human_gate_and_duplicate_correlation.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_same_mission_e2e.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_opencode_surface.py
```

No G5 runtime/product implementation is allowed in EC0.

## Required RED truth

The fresh tests MUST fail for real missing G5 product integration, not because of syntax/import-fixture mistakes. At minimum the RED suite must demonstrate current HOLD/missing behavior for:

- canonical `g5_command` product seam;
- Router-persisted `DEFECT_HUNTER` role;
- exact current Task/Attempt/Session + root R2.5 binding admission;
- G4 `UNEXPECTED_OBSERVATION` -> R3.6 TestAnomaly mapping;
- governed evidence request path;
- exact R2.6 G5 confirmation policy;
- exact R4.3 handoff;
- OpenCode diagnosis canonical G5 wiring;
- same-Mission E2E.

## EC0 gate

```text
G5_RED_ORACLE_PRESENT = YES
RED_FAILURES_MATCH_MISSING_G5_INTEGRATION = YES
FROZEN_G1_G4_TESTS_MODIFIED = NO
RUNTIME_PRODUCT_CODE_MODIFIED = NO
```

If tests encode behavior different from the frozen CodeContract, repair the tests before any implementation.

---

# 7. EC1 — Router role and non-durable integration contracts

**Purpose:** establish the smallest type/role surface without defect mutation.

## Allowed implementation

1. Add `aitest_runtime/g5/contracts.py` and package `__init__.py`.
2. Add canonical G2.1 Router role:

```text
role = DEFECT_HUNTER
agent_name = aitest-diagnosis
```

with exact required capabilities:

```text
OPENCODE_AGENT_SESSION
TASK_OUTCOME_REPORT
DEFECT_ANOMALY_INTAKE
DEFECT_CANDIDATE_FORMATION
EVIDENCE_GAP_ANALYSIS
CROSS_SOURCE_CORRELATION
REPRODUCIBILITY_REASONING
FALSE_POSITIVE_EXCLUSION
DEFECT_TRUTH_ASSESSMENT
RCA_ANALYSIS
DUPLICATE_CORRELATION
```

3. Preserve `DIAGNOSIS` only as product compatibility spelling; newly persisted G5 route role is `DEFECT_HUNTER`.
4. Define only the frozen non-durable envelopes:
   - `G5WorkerBinding`
   - `G4ObservationAdmission`
   - `GovernedEvidenceRequest`
   - `DuplicateCorrelationDecision`
   - `G5OperationResult`

## Forbidden in EC1

- R3.6 mutation;
- R4.3 mutation;
- HumanGate mutation;
- provider execution;
- Session lifecycle ownership;
- new durable extension/store.

## EC1 evidence gate

Focused tests must prove Router resolution and envelope validation while all unavailable later-stage actions still fail closed.

---

# 8. EC2 — Canonical product seam and exact worker binding

**Purpose:** establish fail-closed admission before enabling any defect mutation.

## Required implementation

In `product_entry.py` and G5 service composition:

```python
g5_command(role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]
```

CLI:

```text
python -m aitest_runtime.product_entry g5 --role <ROLE> --action <ACTION> --payload <JSON>
```

Allowed roles:

```text
DIRECTOR
DEFECT_HUNTER
DIAGNOSIS -> DEFECT_HUNTER compatibility normalization
```

Add `_require_g5_worker_binding(...)` implementing the frozen composite authority.

## Current action authority — R1.3B + G2.1

For every Mission-scoped live worker action, require:

1. route exists;
2. route role = `DEFECT_HUNTER`;
3. route agent = `aitest-diagnosis`;
4. supplied Attempt exists;
5. supplied Attempt is current/latest for Task;
6. Attempt Mission/Task match;
7. Attempt runtime Session equals supplied Session;
8. Session exists and is OPEN;
9. present Session agent equals `aitest-diagnosis`;
10. stale predecessor Attempt/Session is rejected.

## LogicalAgent authority — frozen root R2.5 binding

Require:

1. expected logical agent = `SessionRouter.logical_agent_id("aitest-diagnosis", task_id)`;
2. current root Attempt resolves;
3. immutable R2.5 binding exists for the same root;
4. binding Mission/Task/root/logical_agent_id are exact;
5. anchor Attempt/Session belong to that same execution lineage.

Do not create a successor R2.5 binding merely to equal a rotated current Session.

## Required deterministic failures

At least:

```text
G5_ROLE_FORBIDDEN
G5_ACTION_FORBIDDEN
G5_ROUTE_REQUIRED
G5_ROUTE_ROLE_MISMATCH
G5_ATTEMPT_NOT_FOUND
G5_ATTEMPT_NOT_CURRENT
G5_ATTEMPT_TASK_MISMATCH
G5_ATTEMPT_SESSION_MISMATCH
G5_LOGICAL_AGENT_BINDING_MISSING
G5_LOGICAL_AGENT_BINDING_MISMATCH
G5_SESSION_NOT_OPEN
```

No defect mutation is considered accepted until worker binding tests are GREEN.

---

# 9. EC3 — Exact G4 admission and frozen R3.6 investigation pipeline

**Purpose:** make G5 form Defect Truth only from exact governed G4 evidence and frozen R3.6 objects.

## 9.1 G4 -> TestAnomaly admission

Add `g5/admission.py` and required service composition.

For current concrete G4 execution facts, `record_anomaly` must:

1. resolve exact same-Mission G4 fact;
2. require `fact_kind = UNEXPECTED_OBSERVATION`;
3. require `status = OBSERVATION_ONLY`;
4. require `g5_defect_truth = HOLD`;
5. admit current concrete G4 trigger `FAIL | ERROR | INCONCLUSIVE`;
6. resolve exact linked `step_result_ref` digest/fingerprint;
7. validate Mission/Task/Attempt/Session/case/execution lineage;
8. validate QV/Campaign and required case/strategy refs;
9. map refs/digests only.

Design-permitted additional triggers may be admitted only when an exact durable G4 fact exists:

```text
EVIDENCE_INSUFFICIENT
ORACLE_CONTRADICTION
PAGE_RUNTIME_CONFLICT
JOURNEY_ANOMALY
```

Do not fabricate upstream G4 facts.

G5-originated R3.6 commands must carry explicit `architecture_baseline_ref = v7`; frozen R3.6 historical `v5` constant remains untouched.

## 9.2 Candidate/investigation stages

Implement thin mappings only to frozen `R36ApplicationService` operations:

```text
record_anomaly
create_candidate
request_evidence_deepening  # existing typed refs mode
record_evidence_assessment
correlate_sources
evaluate_reproducibility
assess_false_positive
assess_defect_truth
record_rca
record_checkpoint
```

No G5 shadow entity schema is permitted.

## EC3 GREEN gate

Tests must prove:

- G4 FAIL is still observation only;
- missing/incorrect lineage cannot create TestAnomaly;
- `PRODUCT_DEFECT_CANDIDATE` remains hypothesis;
- applicable alternative classifications remain explicit;
- insufficient/conflicted evidence cannot confirm;
- `NOT_FALSE_POSITIVE` is required;
- reproduction or typed causal basis is required;
- unresolved contradictions block confirmation;
- single 500/error string/LLM confidence/static suspicion cannot confirm.

---

# 10. EC4 — Governed evidence work and restart/rotation recovery

**Purpose:** ensure Defect Hunter deepens evidence without becoming Executor/Planner/Session owner.

## 10.1 Existing typed evidence

Use frozen R3.6 bounded `InvestigationWorkSetRequest/Receipt` and secret rejection. Raw CAT/API/UI/DB/browser payloads are not bulk injected into model context.

## 10.2 New real work

For fresh reproduction/UI/API/CAT/DB/deployment/G3 work, G5 returns only:

```text
status = GOVERNED_WORK_REQUIRED
truth_source = R1_EVENT_STREAM
next_required_action = EXISTING_GOVERNED_TASK | G2_PLAN_REVISION_REQUIRED
requested_work = GovernedEvidenceRequest
```

Rules:

1. G5 cannot create WorkGraph Task truth.
2. G5 cannot call G3/G4 providers/services as a mutation shortcut.
3. Existing dependency-valid Task may be referenced.
4. Otherwise existing G2 Planner must create/revise Plan/Task.
5. Scheduler/Router provisions Session.
6. G3/G4 executes under its existing authority/safety/HumanGate contracts.
7. G5 resumes only after resulting durable refs exist and are re-admitted.

Required bypass failure: `G5_DIRECT_EXECUTION_FORBIDDEN`.

## 10.3 Recovery

`work_context` reconstructs only from:

```text
R1 Mission/Goal/Plan/Task/current Attempt
G2.1 current route/Session
root R2.5 LogicalAgentBinding
G4 refs
G3 refs
R3.6 candidate state + latest valid checkpoint
R4.1 QualityVersion/Campaign refs
R4.3 lifecycle if present
R2.6 gate state
provider/evidence availability statuses
```

Recovery must select latest valid checkpoint by Event order, validate WorkSet digest/cursor, treat historical checkpoint Session as provenance only, then continue in the current Router-assigned Session.

Conversation history is never recovery truth.

---

# 11. EC5 — Human confirmation, duplicate/canonical-defect correlation, exact R4.3 handoff

**Purpose:** complete Defect Truth without inventing confirmation/fix authority.

## 11.1 Human review policy

Add `g5/policy.py` and service integration.

Mandatory HumanGate before `CONFIRMED_DEFECT` when any frozen trigger applies:

```text
highest severity
Security-sensitive
Performance-sensitive
Regulatory-sensitive
multiple plausible candidates with unresolved critical contradiction
ambiguous canonical-defect merge
policy-required confirmation source unavailable
high-risk/destructive reproduction required
explicit project confirmation policy
```

Human approval is additional policy only; it never bypasses frozen R3.6 evidence rules.

## 11.2 Exact R2.6 encoding

Use only frozen R2.6 values:

```text
gate_kind = CHOICE
decision_policy_id = g5-defect-confirmation-policy
decision_policy_version = 1
allowed_outcomes = [CHOICE_SELECTED, REJECTED]
```

`allowed_routes_by_outcome` must define every frozen R2.6 outcome and preserve at least:

```text
APPROVED                  -> [RESUME_EXECUTION]
REJECTED                  -> [BLOCK]
CHOICE_SELECTED           -> [RESUME_EXECUTION, PLAN_REVISION]
INFORMATION_PROVIDED      -> [NONE]
EXTERNAL_ACTION_COMPLETED -> [NONE]
```

Semantic choice exists only in decision payload:

```text
CONFIRM_DEFECT
REQUEST_MORE_EVIDENCE
REJECT_DEFECT
```

Continuation requiring `RESUME_EXECUTION` or `PLAN_REVISION` must become canonically APPLIED / `HumanGateRecord.is_allowing == True` before G5 continues. A resumed worker must again pass current EC2 binding.

## 11.3 Duplicate/canonical identity

Never deduplicate by HTTP code, exception/error text, stack trace, component name, or model similarity/confidence.

Before confirmation use frozen R3.6 correlation/semantic reuse.

Automatic `SAME_CONFIRMED_LIFECYCLE` reuse requires same Mission + exact lifecycle id/digest + typed proof of same mechanism/root cause + no unresolved contradiction.

Cross-Mission silent lifecycle merge remains forbidden.

## 11.4 Exact R4.3 handoff

Only:

`R43ApplicationService.open_confirmed_defect_lifecycle(...)`

may open the lifecycle after exact R3.6 assessment/digest, QV/Campaign scope, worker binding, any mandatory HumanGate, and duplicate policy pass.

G5 must never call:

```text
record_fix_link
request_fix_detection
record_fix_detection_assessment
```

## EC5 GREEN gate

Prove autonomous ordinary functional confirmation, mandatory-human cases, continuation semantics, exact handoff/idempotency, same-Mission reuse and ambiguous/cross-Mission blocking.

---

# 12. EC6 — OpenCode Diagnosis canonical surface

**Purpose:** remove the pre-G5 HOLD only after canonical Python/runtime path is real and tested.

In `workspace-template/.opencode/tools/aitest.ts`, add G5 helper following existing G3/G4 subprocess pattern:

```text
canonical workspace
portable Python
-m aitest_runtime.product_entry g5
--role DIAGNOSIS
--action <action>
--payload <json>
```

Requirements:

- require JSON output;
- require `truth_source = R1_EVENT_STREAM`;
- fail closed on subprocess/JSON/truth-source error;
- no TypeScript defect storage;
- no TypeScript provider execution;
- no TypeScript confirmation heuristic.

The existing diagnosis tool may stop returning G5 HOLD only when the canonical runtime path is available.

`aitest-diagnosis.md` may be edited only to align wording/actions with the frozen contract; it cannot create new runtime semantics.

---

# 13. EC7 — Adversarial, same-Mission E2E, full regression and closure evidence

## 13.1 Positive contract

Fresh tests must prove all frozen positive gates, including:

1. G4 FAIL remains observation only.
2. Exact G4 lineage is required.
3. G5 v7 origin lineage does not rewrite R3.6 v5 history.
4. Router role/capability identity is exact.
5. Current Task/Attempt/Session + root R2.5 binding are exact.
6. Rotation accepts successor current identity and rejects stale predecessor.
7. WorkSet is bounded and raw-payload-free.
8. New real evidence returns governed work requirement and comes back only through G2/G3/G4.
9. alternatives/contradictions stay explicit.
10. NOT_FALSE_POSITIVE required.
11. reproduction or causal basis required.
12. contradiction blocks confirmation even with human approval.
13. ordinary evidence-complete functional defect can autonomously confirm.
14. highest/Security/Performance/Regulatory confirmation uses exact R2.6 CHOICE policy.
15. R2.6 continuation must be APPLIED.
16. exact R3.6 assessment opens R4.3 lifecycle.
17. restart/rotation recovers from durable checkpoint.
18. exact assessment/QV/Campaign handoff is idempotent.
19. same proven same-Mission root cause can reuse lifecycle; ambiguous/cross-Mission silent merge is blocked.

## 13.2 Mandatory adversarial contract

Reject or keep non-confirmed for:

```text
single API 500
error/exception string only
LLM 99% confidence only
static code suspicion only
stale deployment/build
wrong test data
stale/wrong expected result
automation selector failure
auth/session expiry
CAT unavailable
reproduction blocked without causal proof
conflicted DB vs API evidence
same error text from different components
ambiguous duplicate merge
cross-Mission silent lifecycle reuse
stale predecessor Session
wrong Task
wrong Attempt
wrong current Session
wrong LogicalAgent root binding
raw secret/evidence injection
custom/nonexistent R2.6 gate kind/outcome
HumanGate decision without continuation proof
legacy defects.py AUTO_CONFIRMED path
direct G4/provider bypass
G3 Standard Case mutation from G5
R4.3 fix mutation from G5
G6 action from G5
```

## 13.3 Same-Mission E2E

One durable Mission must prove:

```text
G2 Plan/Task + DEFECT_HUNTER route
-> G4 governed FAIL / UNEXPECTED_OBSERVATION
-> G5 exact admission
-> R3.6 TestAnomaly
-> DefectCandidate + alternatives
-> bounded evidence deepening
-> governed reproduction OR typed causal proof
-> cross-source correlation
-> EvidenceAssessment
-> reproducibility
-> false-positive exclusion
-> DefectAssessment CONFIRMED_DEFECT
-> RCA
-> exact R4.3 ConfirmedDefectLifecycle
```

Companion same-Mission path must first return `GOVERNED_WORK_REQUIRED`, route evidence work through existing G2/G3/G4, then resume G5 from durable refs.

---

# 14. Test execution policy

## 14.1 Targeted tests by wave

- EC0: all six G5 suites must demonstrate truthful RED.
- EC1: Router/contracts portions of product-path and worker-binding suites.
- EC2: complete worker-binding/rotation negative matrix.
- EC3: product-path + adversarial defect-truth suites.
- EC4: worker recovery + governed-evidence tests.
- EC5: HumanGate/duplicate + relevant adversarial tests.
- EC6: OpenCode surface suite.
- EC7: all G5 suites + same-Mission E2E + full frozen regression.

## 14.2 Existing frozen regression

Run the repository's canonical existing G1-G4 validation runner from the actual branch source. Do not hard-code a stale historical count into G5; the Pre-Execution Drift Check must pin the exact current canonical runner/source identity, and EC7 must prove every existing frozen suite still passes.

No existing G1-G4 test may be removed, skipped, weakened, renamed out of the canonical runner, or replaced with static-source assertions merely to obtain GREEN.

## 14.3 Runtime integrity

Before Engineering PASS candidate:

```text
runtime.verify_projection = PASS
all existing frozen G1-G4 suites = PASS
all G5 focused suites = PASS
all G5 adversarial suites = PASS
G5 same-Mission E2E = PASS
```

---

# 15. Static negative audit

Final canonical G5 product source fails closure if it imports/uses as write authority:

```text
aitest_runtime.defects
legacy defect SQL tables
aitest.db
AUTO_CONFIRMED
direct CAT/browser/DB/API provider execution from g5 package
G3 Standard Case mutation from g5 package
R4.3 fix-link/fix-detection mutation from g5 package
G6 mutation
```

Also prove:

- no new G5 durable extension is registered;
- `canonical_runtime.canonical_extension_manifests()` has no new G5 extension;
- frozen R3.6/R4.3 semantics were not modified;
- errors and test output do not leak raw secrets/evidence.

---

# 16. Legacy-store immutability evidence

The G5 validation protocol must record legacy-store state before and after G5 product-path tests.

Required result:

```text
legacy aitest.db created by G5 = NO
legacy aitest.db modified by G5 = NO
legacy defect SQL used as product truth = NO
```

If the legacy file already exists as migration/reference material, its identity must remain unchanged by G5 tests/implementation.

---

# 17. Engineering evidence package

Before returning an Engineering PASS candidate, create auditable non-authoritative evidence containing at minimum:

```text
canonical main identity
active branch
PR identity/state
frozen CodeContract identity
frozen ExecutionContract identity
implementation commit list in wave order
changed-file list by wave
test command + result for each wave
full frozen regression result
G5 focused/adversarial/E2E result
runtime.verify_projection result
static-negative audit result
legacy-store before/after identity
main unchanged proof
PR Draft/UNMERGED proof
G6 HOLD proof
```

Recommended evidence files:

```text
docs/reviews/G5_ENGINEERING_EXECUTION_EVIDENCE.md
docs/reviews/G5_ENGINEERING_VALIDATION_RESULT.json
```

These are review evidence only; they do not become Runtime/Defect Truth.

---

# 18. Repair and STOP policy

A failed targeted test may enter an in-scope repair only when the repair stays within this frozen Execution Contract and CodeContract.

Immediate `STOP / REPLAN_REQUIRED` when any repair would require:

- modifying the frozen CodeContract content;
- changing ArchitectureBaseline v7;
- weakening R3.6 confirmation rules;
- rewriting R4.3 lifecycle admission/fix authority;
- changing G3/G4 frozen domain semantics;
- creating second Defect/Fix/durable truth;
- adding a G5 Session lifecycle owner;
- direct provider execution by G5;
- custom R2.6 enums/semantics;
- silent cross-Mission canonical defect identity;
- weakening/removing existing frozen regression;
- opening G6.

Codex must report the exact file/symbol/contract conflict instead of improvising a workaround.

---

# 19. Pre-Execution Drift Check required after ExecutionContract freeze

After this Candidate is independently reviewed/frozen, construction is still forbidden until a fresh Git-native Pre-Execution Drift Check proves all of the following:

1. `main == 4edd78536633d4258705c6083fe55b44e51f54bb`.
2. PR #2 is Draft / OPEN / UNMERGED and base remains `main` at the canonical baseline.
3. active engineering branch remains `work/g5-defect-truth`.
4. frozen CodeContract identity remains exactly `584b86980c7b0ce93353a37f4e1b76891ca639e0`.
5. frozen CodeContract file content/blob remains unchanged from that identity.
6. 00.9 Contract Review freeze evidence remains present.
7. no runtime/source/test construction occurred before authorization; changes since reviewed head are governance/review evidence only.
8. G1/G2/G2R-1/G2.1/G3/G4 remain PASS/FROZEN and no reopen authority exists.
9. ArchitectureBaseline remains v7 / FROZEN / UNCHANGED.
10. canonical existing G1-G4 validation runner and source topology are pinned for regression.
11. no alternative engineering branch or planning/design branch has become Engineering Truth.
12. G6 remains HOLD.

Only after all checks pass may governance set:

```text
PRE_EXECUTION_DRIFT_CHECK = PASS
READY_FOR_CODEX = YES
```

---

# 20. Codex execution authority after READY_FOR_CODEX

Only after `READY_FOR_CODEX = YES`, Codex is authorized to implement the frozen contract on `work/g5-defect-truth`.

Codex execution rules:

1. execute EC0 -> EC7 in order;
2. do not skip RED-oracle freeze;
3. use exact frozen file/action/role/failure semantics;
4. keep changes minimal and wave-scoped;
5. run mandatory targeted tests before proceeding to the next wave;
6. never modify main;
7. never mark PR ready-for-review/merge without separate governance authority;
8. never freeze G5 or open G6;
9. if source reality contradicts the frozen contract, STOP and return evidence rather than changing the contract;
10. final result is only an `ENGINEERING_PASS_CANDIDATE`, not canonical closure.

---

# 21. Engineering PASS candidate gate

10.G5 may return Engineering PASS candidate only when all are true:

```text
EC0_RED_ORACLE = PASS
EC1_ROUTER_AND_CONTRACTS = PASS
EC2_PRODUCT_SEAM_AND_WORKER_BINDING = PASS
EC3_G4_ADMISSION_AND_R3_6_PIPELINE = PASS
EC4_GOVERNED_EVIDENCE_AND_RECOVERY = PASS
EC5_HUMAN_GATE_DUPLICATE_R4_3 = PASS
EC6_OPENCODE_DIAGNOSIS_SURFACE = PASS
EC7_E2E_ADVERSARIAL_FULL_REGRESSION = PASS
RUNTIME_VERIFY_PROJECTION = PASS
LEGACY_TRUTH_BYPASS = NONE
ARCHITECTURE_DRIFT = NO
MAIN_UNCHANGED = YES
PR_2 = DRAFT / OPEN / UNMERGED
G6 = HOLD
```

The result must then return to `00.9` for independent Git-native Raw Source Closure Review. 10.G5 cannot self-freeze G5, merge PR #2, move canonical main, or authorize G6.

---

# 22. Candidate decision

```text
G5_CODE_CONTRACT_FROZEN = YES
FROZEN_CODE_CONTRACT_IDENTITY = 584b86980c7b0ce93353a37f4e1b76891ca639e0
G5_EXECUTION_CONTRACT_CANDIDATE = FORMED
EXECUTION_CONTRACT_REVIEW = REQUIRED
EXECUTION_CONTRACT_FROZEN = NO
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
IMPLEMENTATION_STARTED = NO
ARCHITECTURE_DRIFT = NO
G1_G2_G2R1_G2_1_G3_G4_REOPEN_REQUIRED = NO
PR_2 = MUST_REMAIN_DRAFT_OPEN_UNMERGED
MAIN = MUST_REMAIN_4edd78536633d4258705c6083fe55b44e51f54bb
G6 = HOLD
BANK_INTERNAL_PILOT_READY = NO
NEXT_GATE = EXECUTION_CONTRACT_REVIEW
```
