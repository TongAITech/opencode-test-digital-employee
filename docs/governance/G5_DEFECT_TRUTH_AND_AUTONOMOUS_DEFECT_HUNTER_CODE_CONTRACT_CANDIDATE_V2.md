# G5 — Defect Truth & Autonomous Defect Hunter CodeContract Candidate V2

**Status:** `CODE_CONTRACT_CANDIDATE / CONTRACT_REVIEW_REQUIRED`  
**WorkItem:** `10.G5｜Defect Truth & Autonomous Defect Hunter`  
**Governance Authority:** `00.8` only  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical frozen main:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Engineering branch:** `work/g5-defect-truth`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`  
**Repository Reality Recon:** `2892efa3c9b212facdc588f5f690fa44284cb0bc`  
**Supersedes for Contract Review:** the initial candidate file/commits `9c7bc8b...` and `88cbc5a...`; those remain Git history only and are not review authority.  

**Only Design Authority:**

1. `docs/governance/G5_DEFECT_TRUTH_AND_AUTONOMOUS_DEFECT_HUNTER_FORMAL_DETAILED_DESIGN_V1.md`
2. `docs/governance/00.8_G5_DETAILED_DESIGN_REVIEW_AND_ENGINEERING_AUTHORIZATION.md`

> V2 incorporates raw-source reality corrections for G2.1 capability naming, R2.5 Session-rotation binding semantics, governed evidence-work routing, and the exact frozen R2.6 HumanGate enums/continuation model. It is still a candidate, not a frozen CodeContract.

---

# 1. Product invariant and construction shape

G5 SHALL be an **integration/application layer over the existing canonical RuntimeService**:

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

When policy requires human decision, canonical R2.6 HumanGate is inserted **before** the R3.6 `CONFIRMED_DEFECT` write.

Mechanical invariants:

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
```

R1 Event Stream remains sole durable Runtime Truth.

Forbidden as Product Truth/write authority:

- `aitest_runtime/defects.py`
- legacy defect SQL tables
- `aitest.db`
- any new G5 SQL/SQLite/JSON defect store
- any new G5 durable Event extension duplicating R3.6/R4.3

`canonical_runtime.canonical_extension_manifests()` SHALL remain without a new G5 durable extension.

---

# 2. Required code surface

Construction SHALL add only an integration package:

```text
workspace-template/ai-test/runtime/aitest_runtime/g5/
    __init__.py
    contracts.py
    admission.py
    policy.py
    service.py
```

Responsibilities:

- `contracts.py`: non-durable G5 integration envelopes/results;
- `admission.py`: exact G4 fact admission and R3.6 mapping;
- `policy.py`: confirmation, HumanGate, duplicate/canonical-defect policies;
- `service.py`: facade composing the shared RuntimeService + frozen R3.6/R4.3/R2.6/G2/G4 authorities;
- `__init__.py`: stable imports.

Authorized additive integration surfaces:

```text
workspace-template/ai-test/runtime/aitest_runtime/product_entry.py
workspace-template/ai-test/runtime/aitest_runtime/g2_1/router.py
workspace-template/.opencode/tools/aitest.ts
workspace-template/.opencode/agents/aitest-diagnosis.md  # wording only if required
workspace-template/.pfc-internal-field-validation/tests/test_g5_*.py
tools/<G5 validation runner or additive extension of canonical runner>
```

Frozen R3.6/R4.3/G3/G4 domain semantics SHALL NOT be rewritten. Any need to weaken them is `REPLAN`.

---

# 3. Non-durable G5 integration contracts

## 3.1 `G5WorkerBinding`

```text
mission_id
task_id
current_attempt_id
root_attempt_id
current_session_id
logical_agent_id
router_role = DEFECT_HUNTER
agent_name = aitest-diagnosis
r2_5_binding_id
r2_5_anchor_attempt_id
r2_5_anchor_session_id
```

This is a validated view only, never stored as a second binding.

## 3.2 `G4ObservationAdmission`

Must carry exact typed/digested lineage for:

```text
mission_id
g4_goal_id
observation_ref
step_result_ref
oracle_result
project/environment/version scope
quality_version_ref
campaign_refs[]
case_ref + case_version
case_value_link_ref
strategy_refs[]
execution_batch_ref
execution_attempt_ref
step_cursor_ref
expected_ref
actual/evidence refs[]
source_identity_ref
execution_node_ref
```

## 3.3 `GovernedEvidenceRequest`

```text
request_id
mission_id
candidate_id
mode = EXISTING_TYPED_REFS | NEW_GOVERNED_ACTION
requested_channels[]
evidence_gap
required_scope
risk_class
preferred_role
existing_task_refs[]
planner_constraints[]
```

This object is not Task/Plan truth.

## 3.4 `DuplicateCorrelationDecision`

```text
NONE
SAME_OPEN_CANDIDATE
SAME_CONFIRMED_LIFECYCLE
AMBIGUOUS_REVIEW_REQUIRED
```

## 3.5 `G5OperationResult`

All product results include:

```text
truth_source = R1_EVENT_STREAM
status
mission_id when scoped
head_seq when available
canonical_refs[]
next_required_action when pending/blocked
```

---

# 4. DEFECT_HUNTER Router role

`AgentRoleRegistry.default()` SHALL expose the canonical persisted G5 role:

```text
role = DEFECT_HUNTER
agent_name = aitest-diagnosis
```

Required capabilities use the **actual frozen capability name**:

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

The existing `DIAGNOSIS` spelling is compatibility-only. Product resolution may accept `DIAGNOSIS`, but newly persisted G5 `TaskRouteRequirement.role` SHALL be `DEFECT_HUNTER`; it must not create a second durable diagnosis role identity.

No G5 API may create/close/rotate/observe/choose Session. Session lifecycle remains G2.1/R2.5/Supervisor-owned.

---

# 5. Exact worker-action binding

Every Mission-scoped `DEFECT_HUNTER` / `DIAGNOSIS` worker action SHALL require:

```text
mission_id
task_id
attempt_id
session_id
```

`product_entry._require_g5_worker_binding(...)` SHALL fail closed unless the following composite authority is exact.

## 5.1 Current action identity — R1.3B + G2.1

1. G2.1 route exists for `task_id`;
2. persisted route role = `DEFECT_HUNTER`;
3. route agent = `aitest-diagnosis`;
4. supplied Attempt exists in R1.3B;
5. supplied Attempt is current/latest for that Task;
6. Attempt Mission/Task match supplied Mission/Task;
7. Attempt runtime Session = supplied Session;
8. current Session exists and is OPEN for live worker action;
9. current Session agent, when present, is `aitest-diagnosis`;
10. stale predecessor Attempt/Session after rotation is rejected.

## 5.2 LogicalAgent identity — immutable root R2.5 binding

11. expected logical_agent_id = `SessionRouter.logical_agent_id("aitest-diagnosis", task_id)`;
12. current Attempt root_attempt_id is resolved;
13. R2.5 contains the immutable LogicalAgentBinding for that same root Attempt;
14. binding Mission/Task/root/logical_agent_id are exact;
15. binding anchor Attempt exists and belongs to the same root/Task;
16. binding anchor Session belongs to the same execution lineage.

Frozen R2.5 intentionally keeps one root binding across Session rotation. Therefore the R2.5 anchor Attempt/Session MAY be the predecessor; G5 SHALL NOT create a successor binding merely to equal the current Session. Exact current Attempt/Session authority comes from 5.1.

Required failures:

```text
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

---

# 6. Canonical `product_entry` G5 seam

Add:

```python
g5_command(role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]
```

CLI:

```text
python -m aitest_runtime.product_entry g5 --role <ROLE> --action <ACTION> --payload <JSON>
```

Allowed product roles:

```text
DIRECTOR
DEFECT_HUNTER
DIAGNOSIS  # alias -> DEFECT_HUNTER
```

## 6.1 DIRECTOR actions

```text
status
intake_observations
investigation_status
open_investigation
request_human_review
canonical_defects
```

Exact semantics:

- `status`: read-only;
- `intake_observations`: enumerate eligible exact G4 facts + already-admitted status; no R3.6 mutation;
- `investigation_status`: read-only R3.6/checkpoint/HumanGate/R4.3 view;
- `open_investigation`: prepare a bounded Planner work request for a DEFECT_HUNTER Task if no suitable governed Task exists; no Plan/Task mutation by G5;
- `request_human_review`: open/reuse canonical R2.6 gate from exact candidate/current execution lineage;
- `canonical_defects`: read-only same-Mission R4.3 lifecycle view.

## 6.2 DEFECT_HUNTER / DIAGNOSIS actions

```text
status
work_context
record_anomaly
create_candidate
request_evidence_deepening
record_evidence_assessment
correlate_sources
evaluate_reproducibility
assess_false_positive
assess_defect_truth
record_rca
record_checkpoint
handoff_confirmed_defect
```

No generic passthrough action is allowed. Mission-scoped actions require Section 5 binding.

---

# 7. Exact G4 admission -> R3.6 TestAnomaly

For the current concrete G4 path, `record_anomaly` SHALL:

1. resolve exact same-Mission G4 fact;
2. require `fact_kind = UNEXPECTED_OBSERVATION`;
3. require `status = OBSERVATION_ONLY`;
4. require `g5_defect_truth = HOLD`;
5. require current G4 oracle trigger `FAIL | ERROR | INCONCLUSIVE`;
6. resolve linked `step_result_ref` and its exact digest/fingerprint;
7. validate Mission/Task/Attempt/Session/case/execution lineage;
8. validate QualityVersion/Campaign and required case/strategy refs;
9. map refs/digests only — never raw evidence body.

The frozen design also permits triggers:

```text
EVIDENCE_INSUFFICIENT
ORACLE_CONTRADICTION
PAGE_RUNTIME_CONFLICT
JOURNEY_ANOMALY
```

G5 may use these only when an exact durable G4 fact/ref exists. It must not fabricate a G4 fact simply because R3.6 accepts the trigger.

R3.6 mapping:

```text
scope = exact project/environment/version
trigger = admitted G4 trigger
upstream_refs = exact G4 observation/step/case/execution refs
source_refs = typed source/build/deployment/QV/campaign refs
evidence_refs = safe G4 evidence/fact IDs
observed_digests = oracle/expected/actual/evidence digests
candidate_signal = observation signal, not defect conclusion
origin_lineage = {
  mission_id,
  architecture_baseline_ref: "v7",
  source: "G5_G4_ADMISSION",
  g4_observation_ref,
  task_id,
  attempt_id
}
```

Frozen R3.6 still contains historical `ARCHITECTURE_BASELINE_REF = "v5"`; G5 SHALL NOT edit it. G5 explicitly supplies v7 lineage on every G5-originated R3.6 command.

`record_anomaly` creates only `TestAnomaly`.

---

# 8. Candidate + alternative hypothesis contract

`create_candidate` SHALL call frozen `R36ApplicationService.create_defect_candidate`.

`PRODUCT_DEFECT_CANDIDATE` is hypothesis only. Alternatives must explicitly consider applicable frozen R3.6 classes, including:

```text
ENVIRONMENT_PROBLEM
TEST_DATA_PROBLEM
AUTOMATION_DEFECT
CASE_SPEC_DEFECT
KNOWLEDGE_FACT_ERROR
UNKNOWN_INCONCLUSIVE
```

Supporting and contradicting refs remain visible. No new competing G5 classification enum is authorized.

---

# 9. Evidence deepening and new-real-work routing

## 9.1 Existing typed evidence

Use frozen R3.6 `InvestigationWorkSetRequest/Receipt` bounds and secret rejection. `request_evidence_deepening(mode=EXISTING_TYPED_REFS)` records only the R3.6 EvidenceDeepeningReceipt and returns receipt/digest/cursor.

## 9.2 New real action required

For a fresh reproduction, browser/UI action, API call, CAT/log query, DB query, deployment observation, or new G3 case/strategy work, DEFECT_HUNTER SHALL NOT directly call providers, G4 execution adapters, G3 mutation services, or WorkGraph commands.

Instead:

```text
status = GOVERNED_WORK_REQUIRED
truth_source = R1_EVENT_STREAM
next_required_action = EXISTING_GOVERNED_TASK | G2_PLAN_REVISION_REQUIRED
requested_work = GovernedEvidenceRequest
```

Rules:

1. an already-planned dependency-valid Task may be referenced as `EXISTING_GOVERNED_TASK`;
2. otherwise only existing G2 `PLANNER/propose_plan` may create a PlanRevision/Task;
3. the accepted Task declares the existing G2.1 Router role/capabilities — e.g. `EXECUTOR` for G4 real execution or a registered G3 specialist for testing-intelligence work;
4. only Scheduler/Router dispatches and provisions Sessions;
5. G4 provider/safety/HumanGate contracts remain authoritative;
6. G5 resumes only after resulting G2/G3/G4 durable refs exist and are re-admitted.

G5 requests plan revision; it does not silently become the Planner.

Required bypass failure: `G5_DIRECT_EXECUTION_FORBIDDEN`.

---

# 10. Evidence assessment -> correlation -> reproducibility -> false-positive -> RCA

Thin governed mappings only:

```text
record_evidence_assessment -> R36ApplicationService.record_evidence_assessment
correlate_sources          -> R36ApplicationService.record_cross_source_correlation
evaluate_reproducibility   -> R36ApplicationService.evaluate_reproducibility
assess_false_positive      -> R36ApplicationService.assess_false_positive
record_rca                 -> R36ApplicationService.record_rca
record_checkpoint          -> R36ApplicationService.record_investigation_checkpoint
```

G5 SHALL NOT weaken R3.6 validation.

- `SUFFICIENT | INSUFFICIENT | CONFLICTED` remain exact evidence states.
- unavailable/not-configured/blocked/invalid/redacted sources remain explicit and never become support.
- `REPRODUCED` requires typed attempt/evidence refs.
- where reproduction is unsafe/impossible, confirmation requires durable causal-basis refs.
- `NOT_FALSE_POSITIVE` requires evidence that relevant alternatives were actually considered/excluded.
- RCA `ESTABLISHED` requires a bounded causal chain; error text/stack trace alone is insufficient.

---

# 11. Defect confirmation and exact canonical R2.6 HumanGate contract

## 11.1 Base R3.6 confirmation gate

`assess_defect_truth` SHALL call frozen R3.6 and never bypass its handler. `CONFIRMED_DEFECT` requires:

```text
final_classification = PRODUCT_DEFECT
>= 1 SUFFICIENT EvidenceAssessment
false_positive.status = NOT_FALSE_POSITIVE
reproducibility = REPRODUCED OR causal_basis_refs not empty
unresolved_contradiction_refs = empty
```

## 11.2 Mandatory human-review triggers

Before writing `CONFIRMED_DEFECT`, require canonical R2.6 when any holds:

```text
highest severity (S0/S1 or project-equivalent highest tier)
Security-sensitive
Performance-sensitive
Regulatory-sensitive
multiple plausible candidates with unresolved critical contradiction
ambiguous canonical-defect merge
policy-required confirmation source unavailable
high-risk/destructive reproduction required
explicit project confirmation policy
```

Human review cannot override frozen R3.6 evidence/contradiction rules; it is an additional gate.

## 11.3 Exact frozen R2.6 encoding

G5 SHALL use existing R2.6 enums only:

```text
gate_kind = CHOICE
decision_policy_id = g5-defect-confirmation-policy
decision_policy_version = 1
allowed_outcomes = [CHOICE_SELECTED, REJECTED]
```

`allowed_routes_by_outcome` must define **all** frozen R2.6 outcomes, with at least:

```text
APPROVED                 -> [RESUME_EXECUTION]   # policy-complete but not in allowed_outcomes
REJECTED                 -> [BLOCK]
CHOICE_SELECTED          -> [RESUME_EXECUTION, PLAN_REVISION]
INFORMATION_PROVIDED     -> [NONE]
EXTERNAL_ACTION_COMPLETED-> [NONE]
```

`response_schema` / decision payload carries the G5 semantic choice:

```text
choice = CONFIRM_DEFECT | REQUEST_MORE_EVIDENCE | REJECT_DEFECT
```

Canonical mapping:

```text
CHOICE_SELECTED + RESUME_EXECUTION + choice=CONFIRM_DEFECT
    => human confirmation path

CHOICE_SELECTED + PLAN_REVISION + choice=REQUEST_MORE_EVIDENCE
    => additional governed evidence work

REJECTED + BLOCK + choice=REJECT_DEFECT
    => block G5 confirmation
```

No custom R2.6 outcome such as `CONFIRM_DEFECT` is allowed.

For `RESUME_EXECUTION` or `PLAN_REVISION`, R2.6 decision recording creates `CONTINUATION_PENDING`. G5 SHALL treat the gate as allowing only after the canonical continuation has been recorded/applied (`HumanGateRecord.is_allowing == True`) using the required successor Attempt/Session or PlanRevision proof.

After a confirm decision, the resumed DEFECT_HUNTER action must again pass Section 5 against the **new current** Attempt/Session before writing R3.6 `CONFIRMED_DEFECT`.

---

# 12. Duplicate and canonical-defect correlation

Never deduplicate solely by HTTP status, exception text, stack trace, component name, or model similarity/confidence.

Correlation evidence should use typed refs for requirement/business rule, changed code/root component, causal mechanism, Journey state transition, API/data contract, build/deployment identity, reproduction signature and cross-layer manifestations.

## 12.1 Before confirmation

Use frozen R3.6 `CrossSourceCorrelation`. Reuse immutable prior R3.6 facts only through frozen `SemanticReuse` with exact entity id/digest/original command id.

## 12.2 Exact same assessment/scope handoff

R4.3 lifecycle identity is deterministic from same-Mission R3.6 assessment + QualityVersion + Campaign scope. Replaying the exact handoff is idempotent and must not create a second lifecycle.

## 12.3 Later same-Mission manifestation

`SAME_CONFIRMED_LIFECYCLE` automatic reuse is allowed only when:

1. lifecycle is in the same Mission;
2. exact lifecycle id/digest exists;
3. typed causal/correlation refs prove the same defect mechanism/root cause;
4. no unresolved contradiction remains.

Record relation via R3.6 correlation/semantic-reuse facts; do not open a second R4.3 lifecycle.

Cross-Mission silent lifecycle merge is not authorized because current R4.3 admission is same-Mission. Suspected cross-Mission duplicates remain distinct or `AMBIGUOUS_REVIEW_REQUIRED` unless an existing canonical cross-Mission identity authority is proven.

---

# 13. Exact R4.3 handoff

`handoff_confirmed_defect` accepts only exact typed/digested refs for:

```text
mission_id
candidate_id
defect_assessment_ref + digest
quality_version_ref
campaign_refs[]
optional severity_refs[]
optional priority_refs[]
optional rca_refs[]
optional evidence_refs[]
optional required R2.6 gate ref
optional duplicate-correlation decision/ref
```

Before handoff:

1. Section 5 worker binding passes;
2. replay same-Mission R3.6;
3. exact assessment/digest resolves;
4. outcome is `CONFIRMED_DEFECT`;
5. frozen R4.3 R3.6 adapter revalidates candidate/evidence/reproducibility/false-positive facts;
6. any mandatory HumanGate is canonically allowing;
7. duplicate decision passes;
8. only `R43ApplicationService.open_confirmed_defect_lifecycle(...)` may open a new lifecycle.

G5 SHALL NOT call:

```text
record_fix_link
request_fix_detection
record_fix_detection_assessment
```

G5 does not close defects, detect fixes, dispatch retests or perform G6.

---

# 14. Restart/checkpoint/Session-rotation recovery

`work_context` reconstructs from durable truth only:

```text
R1 Mission/Goal/Plan/Task/current Attempt
G2.1 route + current Session
immutable root R2.5 LogicalAgentBinding
G4 observation/execution/evidence refs
G3 requirement/change/case/strategy refs
R3.6 candidate stages + latest checkpoint
R4.1 QualityVersion/Campaign refs
R4.3 lifecycle if present
R2.6 gate state
provider/evidence availability statuses
```

Algorithm:

1. validate current composite worker binding;
2. replay R3.6 candidate state;
3. choose latest valid checkpoint by Event order;
4. validate checkpoint WorkSet digest/cursor;
5. treat checkpoint `session_ref` as historical provenance only;
6. continue in current Router-assigned Session without rewriting candidate.

Conversation history is never required for resume.

---

# 15. Evidence/secret safety

G5 SHALL reuse G4/R3.6 bounded reference and redaction rules.

Never durably persist raw passwords, OTP/captcha/face/secret answers, authorization/cookies/tokens/session secrets, credential-bearing browser storage, or unredacted CAT/API/UI/DB payload solely for diagnosis convenience.

`work_context` receives bounded typed refs/digests/safe summaries.

Forbidden raw/secret key injection fails closed.

---

# 16. OpenCode Diagnosis tool

`workspace-template/.opencode/tools/aitest.ts` SHALL add a `g5(...)` helper following the existing `g3(...)` / `g4(...)` subprocess pattern:

```text
portable Python
-m aitest_runtime.product_entry g5
--role DIAGNOSIS
--action <action>
--payload <json>
```

It SHALL:

- run from canonical workspace;
- use canonical portable Python/runtime env;
- require JSON;
- require `truth_source = R1_EVENT_STREAM`;
- fail closed on subprocess/JSON/truth-source error.

The existing `diagnosis` tool stops returning G5 HOLD only after authorized implementation and calls this canonical seam. TypeScript must not own defect storage, providers or confirmation heuristics.

---

# 17. Required deterministic failures

At minimum:

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
G5_G4_ADMISSION_INVALID
G5_G4_LINEAGE_MISSING
G5_EVIDENCE_REF_INVALID
G5_DIRECT_EXECUTION_FORBIDDEN
G5_GOVERNED_WORK_REQUIRED
G5_HUMAN_GATE_REQUIRED
G5_HUMAN_GATE_PENDING
G5_HUMAN_GATE_REJECTED
G5_DUPLICATE_AMBIGUOUS
G5_CONFIRMATION_UNSUPPORTED
G5_R4_3_HANDOFF_REJECTED
G5_LEGACY_DEFECT_TRUTH_FORBIDDEN
G5_SENSITIVE_EVIDENCE_REJECTED
G5_G6_HOLD
```

Errors must not leak raw evidence/secrets.

---

# 18. Static negative gates

Canonical G5 product source SHALL fail static review if it imports/uses as write authority:

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

Legacy files may remain physically present; canonical dependency on them is failure.

---

# 19. Fresh test contract

Tests live under the real topology:

`workspace-template/.pfc-internal-field-validation/tests/`

Required suites equivalent to:

```text
test_g5_product_path.py
test_g5_worker_binding_and_recovery.py
test_g5_adversarial_defect_truth.py
test_g5_human_gate_and_duplicate_correlation.py
test_g5_same_mission_e2e.py
test_g5_opencode_surface.py
```

## 19.1 Positive gates

Fresh tests prove:

1. G4 FAIL remains observation only.
2. exact G4 lineage required for TestAnomaly.
3. G5 supplies v7 origin lineage while frozen R3.6 v5 constant remains unchanged.
4. DEFECT_HUNTER resolves to `aitest-diagnosis` with real `OPENCODE_AGENT_SESSION` capability.
5. exact current Mission/Task/Attempt/Session plus root R2.5 LogicalAgent binding required.
6. Session rotation accepts only successor current Attempt/Session while preserving root binding; stale predecessor rejected.
7. bounded WorkSet contains no raw payload.
8. new real evidence returns `GOVERNED_WORK_REQUIRED`; only G2 Planner/Scheduler + G3/G4 governed task can supply it.
9. alternatives and contradictions remain explicit.
10. `NOT_FALSE_POSITIVE` required.
11. reproduction or causal proof required.
12. unresolved contradiction blocks confirmation even with HumanGate approval.
13. ordinary evidence-complete functional defect may autonomously confirm.
14. highest/security/performance/regulatory confirmation uses exact R2.6 `CHOICE` gate and frozen outcome/route enums.
15. R2.6 `RESUME_EXECUTION`/`PLAN_REVISION` continuation must be APPLIED before G5 proceeds.
16. exact confirmed assessment opens R4.3 lifecycle.
17. restart/rotation resumes from durable checkpoint in current Session.
18. exact same assessment/QV/Campaign handoff is idempotent.
19. same proven same-Mission root cause may reuse one lifecycle; ambiguous/cross-Mission silent merge is blocked.

## 19.2 Mandatory adversarial gates

Reject/non-confirm for:

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
custom/nonexistent R2.6 gate kind or outcome
HumanGate decision without required continuation proof
legacy `defects.py` AUTO_CONFIRMED path
direct G4/provider bypass
G3 Standard Case mutation from G5
R4.3 fix mutation from G5
G6 action from G5
```

## 19.3 Same-Mission E2E

Fresh E2E in one durable Mission:

```text
G2 Plan/Task + DEFECT_HUNTER route
-> G4 governed execution FAIL/UnexpectedObservation
-> G5 exact admission
-> R3.6 TestAnomaly
-> DefectCandidate + alternatives
-> bounded evidence deepening
-> governed reproduction OR durable causal proof
-> cross-source correlation
-> EvidenceAssessment
-> reproducibility
-> false-positive exclusion
-> DefectAssessment CONFIRMED_DEFECT
-> RCA
-> exact R4.3 ConfirmedDefectLifecycle
```

A companion path SHALL prove a new evidence gap first returns `GOVERNED_WORK_REQUIRED`, then only G2-created/G3-or-G4-executed durable work allows G5 to resume.

---

# 20. Regression / closure gates

Before Engineering PASS candidate:

```text
runtime.verify_projection = PASS
all existing frozen G1-G4 suites = PASS
G5 focused suites = PASS
G5 adversarial suites = PASS
G5 same-Mission E2E = PASS
legacy aitest.db not created/modified by G5 path
PR #2 remains Draft / UNMERGED
main remains unchanged
G6 remains HOLD
```

No existing G1-G4 test may be removed/weakened to make G5 pass.

---

# 21. Explicit non-scope

Not authorized:

- ArchitectureBaseline change;
- R3.6/R4.3 semantic rewrite;
- second Defect/Fix truth;
- silent cross-Mission canonical-defect merge;
- G5-owned provider execution;
- fix detection/retest/learning loop;
- G6;
- main write / PR merge;
- G5 freeze by 10.G5.

---

# 22. Candidate result

```text
G5_CODE_CONTRACT_CANDIDATE = FORMED_V2
REPOSITORY_REALITY_RECON = PASS
DESIGN_TO_CODE_CONFLICTS_FOUND = YES
DESIGN_TO_CODE_CONFLICTS_REPAIRED_IN_V2 = YES
ARCHITECTURE_DRIFT = NO
FROZEN_FOUNDATION_REOPEN_REQUIRED = NO
IMPLEMENTATION_STARTED = NO
CODE_CONTRACT_FROZEN = NO
EXECUTION_CONTRACT = NOT_STARTED
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
NEXT_GATE = CONTRACT_REVIEW
```
