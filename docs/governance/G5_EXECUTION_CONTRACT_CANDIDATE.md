# G5 — Execution Contract Candidate

**Status:** `EXECUTION_CONTRACT_CANDIDATE / REPAIRED_AFTER_00.9_REVIEW / REVIEW_REQUIRED / NOT_FROZEN`  
**WorkItem:** `10.G5｜Defect Truth & Autonomous Defect Hunter`  
**Governance Authority:** `00.9｜ChatGPT Harness 总控与架构治理｜G5-G6` as successor to all still-effective `00.8` Governance Authority  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical frozen main:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Engineering branch:** `work/g5-defect-truth`  
**Draft PR:** `#2 / MUST_REMAIN_DRAFT_OPEN_UNMERGED`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`  
**Frozen G5 CodeContract identity:** `584b86980c7b0ce93353a37f4e1b76891ca639e0`  
**Frozen CodeContract blob:** `fd0c85ef7ecbe01e990609b3e7e6f7f6490d5842`  
**Frozen CodeContract file:** `docs/governance/G5_DEFECT_TRUTH_AND_AUTONOMOUS_DEFECT_HUNTER_CODE_CONTRACT_CANDIDATE_V2.md`  
**CodeContract Review evidence:** PR #2 comment `00.9 — G5 CONTRACT REVIEW PASS / CODE CONTRACT FROZEN`  
**Execution Contract review evidence:** PR #2 comment `00.9 — G5 EXECUTION CONTRACT REVIEW / REPAIR REQUIRED`  
**Reviewed Execution Contract candidate head:** `ed405ae6dad2bf72ee0dafb3cecde734c23005b9`  

```text
G5_CONTRACT_REVIEW = PASS
G5_CODE_CONTRACT_FROZEN = YES
FROZEN_CODE_CONTRACT_IDENTITY = 584b86980c7b0ce93353a37f4e1b76891ca639e0
FROZEN_CODE_CONTRACT_BLOB = fd0c85ef7ecbe01e990609b3e7e6f7f6490d5842
G5_EXECUTION_CONTRACT_REVIEW = REPAIR_REQUIRED
EXECUTION_CONTRACT_FROZEN = NO
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
IMPLEMENTATION_STARTED = NO
EC0_RED_ORACLE = NOT_STARTED
G6 = HOLD
BANK_INTERNAL_PILOT_READY = NO
```

This repaired candidate addresses only the three blocking precision/ordering issues identified by 00.9:

1. confirmation sequencing between EC3 and EC5;
2. exact G5 validation runner and immutable G1-G4 regression runner authority;
3. exact implementation/evidence path allowlist.

It does **not** modify, reinterpret, weaken, extend, or reopen the Frozen G5 CodeContract. It does **not** authorize runtime construction, test construction, EC0, Pre-Execution Drift Check, or Codex execution.

---

# 1. Execution objective

The implementation objective remains the frozen G5 integration/application layer:

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

When frozen policy requires human confirmation, canonical R2.6 HumanGate is inserted **before** the R3.6 `CONFIRMED_DEFECT` write and must become canonically allowing before G5 continues.

Execution order:

```text
freeze truthful RED oracle
-> add minimum authorized integration surfaces
-> make pre-confirmation investigation GREEN
-> make confirmation policy + ordinary autonomous confirmation + mandatory HumanGate confirmation GREEN together
-> make exact R4.3 handoff GREEN
-> prove negative/adversarial boundaries
-> prove same-Mission E2E
-> run additive G5 validation
-> run immutable frozen G1-G4 regression separately
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

# 3. Exact construction allowlist and immutable regression authority

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

Only:

```text
workspace-template/ai-test/runtime/aitest_runtime/product_entry.py
workspace-template/ai-test/runtime/aitest_runtime/g2_1/router.py
workspace-template/.opencode/tools/aitest.ts
workspace-template/.opencode/agents/aitest-diagnosis.md   # wording/actions only if required by Frozen CodeContract
```

## 3.3 Exact G5 test allowlist

Only these additive G5 suites are authorized during EC0-EC7:

```text
workspace-template/.pfc-internal-field-validation/tests/test_g5_product_path.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_worker_binding_and_recovery.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_adversarial_defect_truth.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_human_gate_and_duplicate_correlation.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_same_mission_e2e.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_opencode_surface.py
```

No existing G1-G4 test file may be modified, removed, renamed, weakened, skipped, or replaced.

## 3.4 Exact additive G5 validation runner

The only G5 validation runner authorized for construction is:

```text
tools/run_g5_validation.py
```

It is additive and G5-owned. EC0-EC7 G5 focused/adversarial/E2E orchestration MUST go through this runner.

No placeholder runner path remains authorized. No alternative `tools/run_*g5*` runner may be created.

## 3.5 Immutable G1-G4 regression runner

The canonical frozen G1-G4 regression authority is pinned exactly as:

```text
path = tools/run_wave2_validation.py
canonical_main = 4edd78536633d4258705c6083fe55b44e51f54bb
blob = b006cecb48673a5b8735dda9e1b645ebafe7f1fc
authority = G1_G4_REGRESSION_ONLY
mutation = FORBIDDEN
```

Rules:

1. `tools/run_wave2_validation.py` is **read/execute only** throughout G5.
2. Its blob MUST remain exactly `b006cecb48673a5b8735dda9e1b645ebafe7f1fc`.
3. EC0-EC7 MUST NOT modify, replace, extend, wrap by source rewrite, or add G5 suites into this runner.
4. The historical result field `g5_defect_truth = "HOLD"` inside this runner is frozen historical G1-G4 runner metadata only.
5. That literal is **not** G5 gate truth, MUST NOT be changed to `PASS`, and MUST NOT be used to decide G5 Engineering PASS.
6. EC7 invokes this runner separately from the additive G5 runner.
7. Any diff in this file is immediate `STOP / EXECUTION_CONTRACT_VIOLATION`.

## 3.6 Exact docs/evidence allowlist

This present repair is a governance-candidate repair before Execution Contract freeze and may modify only:

```text
docs/governance/G5_EXECUTION_CONTRACT_CANDIDATE.md
```

After the repaired Execution Contract is independently frozen:

- **no EC0-EC7 implementation-wave addition/modification is allowed under `docs/governance/**`;**
- no arbitrary `docs/reviews/**` file is allowed;
- Codex engineering evidence output is pinned exactly to:

```text
docs/reviews/G5_ENGINEERING_EXECUTION_EVIDENCE.md
docs/reviews/G5_ENGINEERING_VALIDATION_RESULT.json
```

These two files may be created/updated only as the G5 engineering evidence package. They are not Runtime/Defect Truth.

Any additional governance/review record is a `00.9` governance action outside Codex implementation scope.

## 3.7 Frozen source not authorized for semantic change

No semantic rewrite is authorized in:

```text
workspace-template/ai-test/runtime/aitest_runtime/r3_6/**
workspace-template/ai-test/runtime/aitest_runtime/r4_3/**
workspace-template/ai-test/runtime/aitest_runtime/r2_6/**
workspace-template/ai-test/runtime/aitest_runtime/g3/**
workspace-template/ai-test/runtime/aitest_runtime/g4/**
canonical Runtime/Event Stream truth semantics
existing G1-G4 test oracle semantics
```

If implementation cannot satisfy the Frozen CodeContract without changing these semantics, construction MUST stop and report exact source conflict for governance review.

## 3.8 Closed construction-path union

After `READY_FOR_CODEX = YES`, a Git diff outside the following union is forbidden unless 00.9 explicitly reopens the Execution Contract:

```text
workspace-template/ai-test/runtime/aitest_runtime/g5/__init__.py
workspace-template/ai-test/runtime/aitest_runtime/g5/contracts.py
workspace-template/ai-test/runtime/aitest_runtime/g5/admission.py
workspace-template/ai-test/runtime/aitest_runtime/g5/policy.py
workspace-template/ai-test/runtime/aitest_runtime/g5/service.py
workspace-template/ai-test/runtime/aitest_runtime/product_entry.py
workspace-template/ai-test/runtime/aitest_runtime/g2_1/router.py
workspace-template/.opencode/tools/aitest.ts
workspace-template/.opencode/agents/aitest-diagnosis.md
workspace-template/.pfc-internal-field-validation/tests/test_g5_product_path.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_worker_binding_and_recovery.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_adversarial_defect_truth.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_human_gate_and_duplicate_correlation.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_same_mission_e2e.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_opencode_surface.py
tools/run_g5_validation.py
docs/reviews/G5_ENGINEERING_EXECUTION_EVIDENCE.md
docs/reviews/G5_ENGINEERING_VALIDATION_RESULT.json
```

`tools/run_wave2_validation.py` is deliberately excluded from the mutable union because it is immutable regression authority.

---

# 4. Branch, commit, and working-tree discipline

All construction occurs only on:

`work/g5-defect-truth`

Rules:

1. `main` MUST remain exactly `4edd78536633d4258705c6083fe55b44e51f54bb` during G5 construction.
2. PR #2 MUST remain Draft / OPEN / UNMERGED.
3. Do not create or switch to another engineering/planning branch.
4. Do not merge, rebase onto a changed main, or rewrite frozen governance history during implementation.
5. Each execution wave MUST end in an independently auditable commit.
6. A repair may be a separate follow-up commit for the same wave; it MUST NOT silently rewrite or weaken the frozen test oracle.
7. No wave may include unrelated cleanup/refactoring.
8. No generated package/ZIP or local Construction copy becomes Engineering Truth; Git commit/diff remains sole engineering source truth.
9. Every wave diff MUST be checked against Section 3.8 before advancing.
10. `tools/run_wave2_validation.py` blob identity MUST be rechecked before EC0 and again at EC7 closure.

Recommended implementation commit prefixes:

```text
test(g5): freeze ...
feat(g5): add ...
fix(g5): repair ...
```

Only the final exact engineering evidence package may use:

```text
docs(g5): record engineering evidence
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
-> EC3_G4_ADMISSION_AND_R3_6_PRECONFIRMATION
-> EC4_GOVERNED_EVIDENCE_AND_RECOVERY
-> EC5_CONFIRMATION_HUMAN_GATE_DUPLICATE_R4_3
-> EC6_OPENCODE_DIAGNOSIS_SURFACE
-> EC7_E2E_ADVERSARIAL_FULL_REGRESSION
-> ENGINEERING_EVIDENCE_REVIEW
-> ENGINEERING_PASS_CANDIDATE
```

The WorkItem MUST NOT skip directly from Execution Contract drafting to implementation.

Current state remains:

```text
EXECUTION_CONTRACT_FROZEN = NO
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
EC0_RED_ORACLE = NOT_STARTED
IMPLEMENTATION_STARTED = NO
```

---

# 6. EC0 — Freeze truthful RED oracle before product construction

**Purpose:** make the Frozen CodeContract executable as tests before product implementation, preventing stale-oracle drift.

**Important:** this section defines a future execution wave only. This repair commit does **not** start EC0 and does not create/modify tests.

## Allowed EC0 changes

Only:

```text
workspace-template/.pfc-internal-field-validation/tests/test_g5_product_path.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_worker_binding_and_recovery.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_adversarial_defect_truth.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_human_gate_and_duplicate_correlation.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_same_mission_e2e.py
workspace-template/.pfc-internal-field-validation/tests/test_g5_opencode_surface.py
tools/run_g5_validation.py
```

No G5 runtime/product implementation is allowed in EC0.

`tools/run_wave2_validation.py` is immutable and is not an EC0 change surface.

## Required RED truth

The six fresh suites, orchestrated by `tools/run_g5_validation.py`, MUST fail for real missing G5 integration rather than syntax/import-fixture mistakes. At minimum RED must demonstrate current missing/HOLD behavior for:

- canonical `g5_command` product seam;
- Router-persisted `DEFECT_HUNTER` role;
- exact current Task/Attempt/Session + root R2.5 binding admission;
- G4 `UNEXPECTED_OBSERVATION` -> R3.6 TestAnomaly mapping;
- governed evidence request path;
- confirmation sequencing that cannot write `CONFIRMED_DEFECT` without EC5 policy;
- exact R2.6 G5 confirmation policy;
- exact R4.3 handoff;
- OpenCode diagnosis canonical G5 wiring;
- same-Mission E2E.

## EC0 gate

```text
G5_RED_ORACLE_PRESENT = YES
RED_FAILURES_MATCH_MISSING_G5_INTEGRATION = YES
G5_RUNNER = tools/run_g5_validation.py
FROZEN_G1_G4_TESTS_MODIFIED = NO
FROZEN_WAVE2_RUNNER_BLOB = b006cecb48673a5b8735dda9e1b645ebafe7f1fc
RUNTIME_PRODUCT_CODE_MODIFIED = NO
```

If tests encode behavior different from the Frozen CodeContract, repair the tests before any implementation.

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

Focused tests through `tools/run_g5_validation.py` must prove Router resolution and envelope validation while unavailable later-stage actions fail closed.

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
3. immutable R2.5 binding exists for same root;
4. binding Mission/Task/root/logical_agent_id are exact;
5. anchor Attempt/Session belong to the same execution lineage.

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

No defect mutation is considered accepted until worker-binding tests are GREEN.

---

# 9. EC3 — Exact G4 admission and frozen R3.6 pre-confirmation investigation

**Purpose:** make G5 build exact pre-confirmation investigation truth from governed G4 evidence and frozen R3.6 objects **without enabling a `CONFIRMED_DEFECT` write path**.

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

## 9.2 Pre-confirmation candidate/investigation stages

EC3 may enable only thin mappings for:

```text
record_anomaly
create_candidate
request_evidence_deepening  # existing typed refs mode
record_evidence_assessment
correlate_sources
evaluate_reproducibility
assess_false_positive
record_rca
record_checkpoint
```

`assess_defect_truth` is deliberately **not enabled as a G5 product mutation in EC3**.

No G5 shadow entity schema is permitted.

## 9.3 Hard confirmation barrier in EC3

Until EC5 is complete:

```text
G5_CONFIRMATION_WRITE_ENABLED = NO
R3_6_CONFIRMED_DEFECT_WRITE_VIA_G5 = FORBIDDEN
R4_3_CONFIRMED_LIFECYCLE_OPEN_VIA_G5 = FORBIDDEN
```

Rules:

1. no EC3 product path may call frozen `R36ApplicationService.assess_defect_truth(...)` in a way that can persist `CONFIRMED_DEFECT`;
2. no highest-severity/Security/Performance/Regulatory-sensitive path may become confirmable before EC5 policy exists;
3. no ordinary functional path may become confirmable before EC5 either;
4. both ordinary autonomous confirmation and policy-mandatory HumanGate confirmation are intentionally deferred to EC5 and become GREEN together;
5. frozen R3.6 handlers/semantics are not changed to implement this barrier — G5 simply does not expose the confirmation write yet.

## EC3 GREEN gate

Tests through `tools/run_g5_validation.py` must prove:

- G4 FAIL is still observation only;
- missing/incorrect lineage cannot create TestAnomaly;
- `PRODUCT_DEFECT_CANDIDATE` remains hypothesis;
- applicable alternative classifications remain explicit;
- bounded evidence/correlation/reproducibility/false-positive facts can be constructed only through frozen R3.6 authority;
- single 500/error string/LLM confidence/static suspicion remain insufficient investigation signals;
- **no G5 `CONFIRMED_DEFECT` exists after EC3 tests;**
- **all G5 confirmation attempts remain fail-closed until EC5.**

EC3 PASS is invalid if any G5 path can persist `CONFIRMED_DEFECT`.

---

# 10. EC4 — Governed evidence work and restart/rotation recovery

**Purpose:** ensure Defect Hunter deepens evidence without becoming Executor/Planner/Session owner while the EC3 confirmation barrier remains active.

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
6. G3/G4 executes under existing authority/safety/HumanGate contracts.
7. G5 resumes only after resulting durable refs exist and are re-admitted.
8. EC4 does not lift the EC3 confirmation barrier.

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

Recovery must select latest valid checkpoint by Event order, validate WorkSet digest/cursor, treat historical checkpoint Session as provenance only, then continue in current Router-assigned Session.

Conversation history is never recovery truth.

---

# 11. EC5 — Confirmation policy, HumanGate, duplicate/canonical-defect correlation, exact R4.3 handoff

**Purpose:** enable the G5 confirmation write for the first time, with ordinary autonomous confirmation and all mandatory-human confirmation rules becoming GREEN in the same wave.

EC5 is the **only** wave that may lift the EC3/EC4 confirmation barrier.

## 11.1 Confirmation sequencing invariant

The required order for every requested `CONFIRMED_DEFECT` outcome is:

```text
current worker binding
-> exact candidate/evidence/reproducibility/false-positive/contradiction facts
-> G5 confirmation-policy classification
-> [mandatory HumanGate if policy requires]
-> continuation APPLIED / is_allowing when required
-> revalidate current worker binding after continuation
-> frozen R36ApplicationService.assess_defect_truth(...)
-> exact persisted DefectAssessment == CONFIRMED_DEFECT
-> duplicate/canonical correlation decision
-> exact R4.3 handoff
```

No step may reorder the R2.6 policy gate after the R3.6 `CONFIRMED_DEFECT` write.

## 11.2 Human review policy

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

## 11.3 Exact R2.6 encoding

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

No custom R2.6 gate kind, outcome, route, or durable G5 decision enum is authorized.

## 11.4 Mandatory-human confirmation path

For a policy-mandatory case:

1. evaluate mandatory-review triggers **before** invoking R3.6 `assess_defect_truth` for a requested confirmed outcome;
2. absent required gate -> return `G5_HUMAN_GATE_REQUIRED`; do not write confirmed assessment;
3. pending/non-allowing gate -> return `G5_HUMAN_GATE_PENDING`; do not write confirmed assessment;
4. `REJECTED + BLOCK + REJECT_DEFECT` -> return `G5_HUMAN_GATE_REJECTED`; do not write confirmed assessment;
5. `CHOICE_SELECTED + PLAN_REVISION + REQUEST_MORE_EVIDENCE` -> return to governed evidence work; do not write confirmed assessment;
6. `CHOICE_SELECTED + RESUME_EXECUTION + CONFIRM_DEFECT` still does not permit immediate write while continuation is pending;
7. canonical continuation must become APPLIED and `HumanGateRecord.is_allowing == True`;
8. resumed DEFECT_HUNTER must pass EC2 binding against the new current Attempt/Session;
9. revalidate frozen R3.6 prerequisites and contradiction state;
10. only then invoke frozen `R36ApplicationService.assess_defect_truth(...)`.

## 11.5 Ordinary autonomous confirmation path

For an evidence-complete ordinary functional case that matches **none** of the mandatory-human triggers:

1. current worker binding passes;
2. exact R3.6 evidence/reproducibility/false-positive/contradiction prerequisites are present;
3. G5 policy explicitly determines no mandatory HumanGate applies;
4. only then invoke frozen `R36ApplicationService.assess_defect_truth(...)`;
5. frozen R3.6 handler remains final truth authority and may still reject confirmation.

HumanGate bypass is permitted only because frozen policy does not require the gate for that exact ordinary case, not because G5 weakens R3.6.

## 11.6 Frozen R3.6 confirmation requirements remain exact

A `CONFIRMED_DEFECT` write remains valid only when frozen R3.6 requirements pass, including:

```text
final_classification = PRODUCT_DEFECT
>= 1 SUFFICIENT EvidenceAssessment
false_positive.status = NOT_FALSE_POSITIVE
reproducibility = REPRODUCED OR causal_basis_refs not empty
unresolved_contradiction_refs = empty
```

Human approval cannot override these requirements.

## 11.7 Atomic EC5 wave gate

Ordinary autonomous confirmation and policy-mandatory HumanGate confirmation MUST become GREEN together.

No intermediate EC5 commit may be treated as an advanceable wave state if it enables ordinary confirmation but not mandatory policy, or enables mandatory policy but exposes another confirmation bypass.

Until the complete EC5 gate passes:

```text
EC5_CONFIRMATION_POLICY_COMPLETE = NO
G5_CONFIRMATION_WRITE_AUTHORIZED_FOR_NEXT_WAVE = NO
```

## 11.8 Duplicate/canonical identity

Never deduplicate by HTTP code, exception/error text, stack trace, component name, or model similarity/confidence.

Before confirmation use frozen R3.6 correlation/semantic reuse.

Automatic `SAME_CONFIRMED_LIFECYCLE` reuse requires same Mission + exact lifecycle id/digest + typed proof of same mechanism/root cause + no unresolved contradiction.

Cross-Mission silent lifecycle merge remains forbidden.

## 11.9 Exact R4.3 handoff

Only:

```text
R43ApplicationService.open_confirmed_defect_lifecycle(...)
```

may open a lifecycle after all of the following:

1. exact EC2 worker binding;
2. exact persisted R3.6 assessment/digest resolves;
3. assessment outcome is `CONFIRMED_DEFECT`;
4. frozen R4.3 R3.6 adapter revalidates candidate/evidence/reproducibility/false-positive facts;
5. exact QV/Campaign scope resolves;
6. any mandatory HumanGate is canonically allowing;
7. duplicate policy passes.

G5 must never call:

```text
record_fix_link
request_fix_detection
record_fix_detection_assessment
```

## EC5 GREEN gate

Through `tools/run_g5_validation.py`, prove together:

- insufficient/conflicted evidence cannot confirm;
- `NOT_FALSE_POSITIVE` is required;
- reproduction or typed causal basis is required;
- unresolved contradiction blocks confirmation even with HumanGate approval;
- single 500/error string/LLM confidence/static suspicion cannot confirm;
- ordinary evidence-complete functional defect may autonomously confirm only after policy says no HumanGate is mandatory;
- highest/Security/Performance/Regulatory-sensitive confirmation uses exact R2.6 `CHOICE` policy;
- HumanGate decision without required continuation proof cannot confirm;
- `REQUEST_MORE_EVIDENCE` returns to governed work rather than confirming;
- resumed confirmation revalidates successor current Attempt/Session;
- exact confirmed assessment opens R4.3 lifecycle;
- exact handoff is idempotent;
- same-Mission typed reuse works only when exact proof exists;
- ambiguous/cross-Mission silent merge is blocked.

---

# 12. EC6 — OpenCode Diagnosis canonical surface

**Purpose:** remove the pre-G5 HOLD only after canonical Python/runtime path and EC5 confirmation policy are real and tested.

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

The existing diagnosis tool may stop returning G5 HOLD only when the canonical runtime path including EC5 confirmation policy is available.

`aitest-diagnosis.md` may be edited only to align wording/actions with the Frozen CodeContract; it cannot create new runtime semantics.

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
13. ordinary evidence-complete functional defect can autonomously confirm only after EC5 policy evaluation.
14. highest/Security/Performance/Regulatory confirmation uses exact R2.6 CHOICE policy before R3.6 confirmed write.
15. R2.6 continuation must be APPLIED.
16. exact R3.6 assessment opens R4.3 lifecycle.
17. restart/rotation recovers from durable checkpoint.
18. exact assessment/QV/Campaign handoff is idempotent.
19. same proven same-Mission root cause can reuse lifecycle; ambiguous/cross-Mission silent merge is blocked.
20. no EC3/EC4 intermediate path can write `CONFIRMED_DEFECT`.

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
repro blocked without causal proof
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
confirmation attempt before EC5 policy is complete
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
-> EC5 confirmation-policy evaluation
-> [R2.6 HumanGate + APPLIED continuation when required]
-> DefectAssessment CONFIRMED_DEFECT
-> RCA
-> exact R4.3 ConfirmedDefectLifecycle
```

Companion same-Mission path must first return `GOVERNED_WORK_REQUIRED`, route evidence work through existing G2/G3/G4, then resume G5 from durable refs.

---

# 14. Exact validation-runner policy

## 14.1 G5 runner authority

All G5-focused execution is orchestrated only by:

```text
tools/run_g5_validation.py
```

It owns only G5 validation orchestration for the six exact G5 test files. It must not mutate product truth, invoke legacy defect stores, or rewrite G1-G4 regression authority.

Wave expectations:

- EC0: all six G5 suites demonstrate truthful RED.
- EC1: Router/contracts relevant assertions become GREEN.
- EC2: worker-binding/rotation matrix becomes GREEN.
- EC3: admission + pre-confirmation investigation becomes GREEN while all confirmation remains blocked.
- EC4: governed-evidence + recovery becomes GREEN while confirmation remains blocked.
- EC5: ordinary autonomous confirmation + mandatory HumanGate confirmation + duplicate/R4.3 handoff become GREEN together.
- EC6: OpenCode surface becomes GREEN.
- EC7: all six G5 suites + adversarial + same-Mission E2E are GREEN.

The G5 runner's final structured result MUST be written exactly to:

```text
docs/reviews/G5_ENGINEERING_VALIDATION_RESULT.json
```

No alternate committed G5 validation-result path is authorized.

## 14.2 Frozen G1-G4 regression command/authority

EC7 MUST separately execute the immutable runner:

```text
python tools/run_wave2_validation.py --root . --output G5_WAVE2_VALIDATION_RESULT.tmp.json
```

Requirements:

1. before execution, verify blob = `b006cecb48673a5b8735dda9e1b645ebafe7f1fc`;
2. `G5_WAVE2_VALIDATION_RESULT.tmp.json` is ephemeral/untracked only;
3. capture its structured PASS/failure evidence into the exact engineering evidence package;
4. delete the temporary file before the final Git diff/closure check;
5. do not interpret historical `g5_defect_truth = HOLD` as G5 failure or G5 PASS;
6. G1-G4 regression PASS is determined only by that runner's own canonical regression `status/groups/combined` result;
7. any source diff in `tools/run_wave2_validation.py` is failure even if regression output is green.

No existing G1-G4 test may be removed, skipped, weakened, renamed out of this runner, or replaced with static-source assertions merely to obtain GREEN.

## 14.3 Runtime integrity

Before Engineering PASS candidate:

```text
runtime.verify_projection = PASS
all existing frozen G1-G4 suites = PASS
all G5 focused suites = PASS
all G5 adversarial suites = PASS
G5 same-Mission E2E = PASS
FROZEN_WAVE2_RUNNER_BLOB = b006cecb48673a5b8735dda9e1b645ebafe7f1fc
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
- frozen R3.6/R4.3/R2.6/G3/G4 semantics were not modified;
- errors and test output do not leak raw secrets/evidence;
- `tools/run_wave2_validation.py` blob remains pinned exactly;
- no changed path escapes Section 3.8.

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

# 17. Exact engineering evidence package

Before returning an Engineering PASS candidate, the only Codex-created/modified documentation evidence files are:

```text
docs/reviews/G5_ENGINEERING_EXECUTION_EVIDENCE.md
docs/reviews/G5_ENGINEERING_VALIDATION_RESULT.json
```

`G5_ENGINEERING_EXECUTION_EVIDENCE.md` must record at minimum:

```text
canonical main identity
active branch
PR identity/state
Frozen CodeContract commit/blob identity
Frozen ExecutionContract identity
implementation commit list in EC0-EC7 order
changed-file list by wave
Section 3.8 allowlist audit
G5 runner path and result
immutable wave2 runner path/blob proof
wave2 regression command + canonical PASS/failure result
runtime.verify_projection result
G5 focused/adversarial/E2E result
static-negative audit result
legacy-store before/after identity
main unchanged proof
PR Draft/UNMERGED proof
G6 HOLD proof
```

`G5_ENGINEERING_VALIDATION_RESULT.json` is the single committed structured G5 validation result and must contain/correlate:

```text
frozen_code_contract_identity
frozen_execution_contract_identity
branch_head
G5 suite results
same-Mission E2E result
adversarial result
runtime projection result
wave2 runner path
wave2 runner blob
wave2 canonical regression status/groups/combined summary
legacy-store immutability result
allowlist audit result
main/PR/G6 closure state
```

These files are review evidence only; they do not become Runtime/Defect Truth.

Any further governance record remains a 00.9 action outside Codex scope.

---

# 18. Repair and STOP policy

A failed targeted test may enter an in-scope repair only when the repair stays within this Frozen Execution Contract and Frozen CodeContract.

Immediate `STOP / REPLAN_REQUIRED` when any repair would require:

- modifying Frozen CodeContract content/blob;
- changing ArchitectureBaseline v7;
- weakening R3.6 confirmation rules;
- enabling a G5 confirmation write before EC5 policy is complete;
- rewriting R4.3 lifecycle admission/fix authority;
- changing R2.6 frozen enums/routes/continuation semantics;
- changing G3/G4 frozen domain semantics;
- creating second Defect/Fix/durable truth;
- adding a G5 Session lifecycle owner;
- direct provider execution by G5;
- custom R2.6 enums/semantics;
- silent cross-Mission canonical defect identity;
- weakening/removing existing frozen regression;
- modifying `tools/run_wave2_validation.py` from blob `b006cecb48673a5b8735dda9e1b645ebafe7f1fc`;
- creating an alternate G5 validation runner;
- writing implementation docs outside the two exact evidence files;
- modifying any path outside Section 3.8;
- opening G6.

Codex must report the exact file/symbol/contract conflict instead of improvising a workaround.

---

# 19. Pre-Execution Drift Check required after ExecutionContract freeze

After this repaired Candidate is independently reviewed/frozen, construction is still forbidden until a fresh Git-native Pre-Execution Drift Check proves all of the following:

1. `main == 4edd78536633d4258705c6083fe55b44e51f54bb`.
2. PR #2 is Draft / OPEN / UNMERGED and base remains `main` at the canonical baseline.
3. active engineering branch remains `work/g5-defect-truth`.
4. Frozen CodeContract identity remains exactly `584b86980c7b0ce93353a37f4e1b76891ca639e0`.
5. Frozen CodeContract blob remains exactly `fd0c85ef7ecbe01e990609b3e7e6f7f6490d5842`.
6. 00.9 CodeContract freeze evidence remains present.
7. this repaired Execution Contract has been independently reviewed/frozen by 00.9.
8. no runtime/source/test construction occurred before authorization; changes since reviewed Execution Contract head are governance/review evidence only.
9. G1/G2/G2R-1/G2.1/G3/G4 remain PASS/FROZEN and no reopen authority exists.
10. ArchitectureBaseline remains v7 / FROZEN / UNCHANGED.
11. `tools/run_wave2_validation.py` exists at blob `b006cecb48673a5b8735dda9e1b645ebafe7f1fc`.
12. exact mutable construction union is Section 3.8; no open-ended paths remain.
13. no alternative engineering/planning branch has become Engineering Truth.
14. G6 remains HOLD.

Only after all checks pass may governance set:

```text
PRE_EXECUTION_DRIFT_CHECK = PASS
READY_FOR_CODEX = YES
```

---

# 20. Codex execution authority after READY_FOR_CODEX

Only after `READY_FOR_CODEX = YES`, Codex is authorized to implement on `work/g5-defect-truth`.

Codex execution rules:

1. execute EC0 -> EC7 in order;
2. do not skip truthful RED-oracle freeze;
3. use exact Frozen CodeContract file/action/role/failure semantics;
4. keep changes minimal and wave-scoped;
5. run mandatory G5 targeted validation through `tools/run_g5_validation.py` before proceeding to the next wave;
6. keep EC3 and EC4 confirmation barrier closed until EC5;
7. make ordinary autonomous confirmation and mandatory HumanGate confirmation GREEN together in EC5;
8. never modify `tools/run_wave2_validation.py`;
9. invoke the immutable wave2 runner separately at EC7;
10. never modify main;
11. never mark PR ready-for-review/merge without separate governance authority;
12. never freeze G5 or open G6;
13. never write docs outside the two exact engineering evidence paths;
14. if source reality contradicts Frozen CodeContract/ExecutionContract, STOP and return evidence rather than changing contract;
15. final result is only an `ENGINEERING_PASS_CANDIDATE`, not canonical closure.

---

# 21. Engineering PASS candidate gate

10.G5 may return Engineering PASS candidate only when all are true:

```text
EC0_RED_ORACLE = PASS
EC1_ROUTER_AND_CONTRACTS = PASS
EC2_PRODUCT_SEAM_AND_WORKER_BINDING = PASS
EC3_G4_ADMISSION_AND_R3_6_PRECONFIRMATION = PASS
EC3_G5_CONFIRMATION_WRITE_ENABLED = NO
EC4_GOVERNED_EVIDENCE_AND_RECOVERY = PASS
EC5_CONFIRMATION_HUMAN_GATE_DUPLICATE_R4_3 = PASS
EC5_ORDINARY_AND_MANDATORY_CONFIRMATION_GREEN_TOGETHER = YES
EC6_OPENCODE_DIAGNOSIS_SURFACE = PASS
EC7_E2E_ADVERSARIAL_FULL_REGRESSION = PASS
G5_VALIDATION_RUNNER = tools/run_g5_validation.py
G1_G4_REGRESSION_RUNNER = tools/run_wave2_validation.py
G1_G4_REGRESSION_RUNNER_BLOB = b006cecb48673a5b8735dda9e1b645ebafe7f1fc
RUNTIME_VERIFY_PROJECTION = PASS
LEGACY_TRUTH_BYPASS = NONE
EXECUTION_ALLOWLIST_VIOLATION = NONE
ARCHITECTURE_DRIFT = NO
MAIN_UNCHANGED = YES
PR_2 = DRAFT / OPEN / UNMERGED
G6 = HOLD
```

The result must then return to `00.9` for independent Git-native Raw Source Closure Review. 10.G5 cannot self-freeze G5, merge PR #2, move canonical main, or authorize G6.

---

# 22. Repaired candidate decision

```text
G5_CODE_CONTRACT_FROZEN = YES
FROZEN_CODE_CONTRACT_IDENTITY = 584b86980c7b0ce93353a37f4e1b76891ca639e0
FROZEN_CODE_CONTRACT_BLOB = fd0c85ef7ecbe01e990609b3e7e6f7f6490d5842
G5_EXECUTION_CONTRACT_CANDIDATE = REPAIRED
REPAIR_1_CONFIRMATION_SEQUENCE = APPLIED
REPAIR_2_G5_RUNNER_PATH = tools/run_g5_validation.py / PINNED
REPAIR_2_G1_G4_RUNNER = tools/run_wave2_validation.py@b006cecb48673a5b8735dda9e1b645ebafe7f1fc / IMMUTABLE
REPAIR_3_DOCS_ALLOWLIST = CLOSED
EXECUTION_CONTRACT_REVIEW = REQUIRED
EXECUTION_CONTRACT_FROZEN = NO
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
EC0_RED_ORACLE = NOT_STARTED
IMPLEMENTATION_STARTED = NO
ARCHITECTURE_DRIFT = NO
CODE_CONTRACT_REOPEN_REQUIRED = NO
G1_G2_G2R1_G2_1_G3_G4_REOPEN_REQUIRED = NO
PR_2 = MUST_REMAIN_DRAFT_OPEN_UNMERGED
MAIN = MUST_REMAIN_4edd78536633d4258705c6083fe55b44e51f54bb
G6 = HOLD
BANK_INTERNAL_PILOT_READY = NO
NEXT_GATE = 00.9_EXECUTION_CONTRACT_REVIEW
```
