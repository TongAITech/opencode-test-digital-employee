# G5 — Defect Truth & Autonomous Defect Hunter CodeContract Candidate

**Status:** `CODE_CONTRACT_CANDIDATE / CONTRACT_REVIEW_REQUIRED`  
**WorkItem:** `10.G5｜Defect Truth & Autonomous Defect Hunter`  
**Governance authority:** `00.8` only  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical frozen main:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Engineering branch:** `work/g5-defect-truth`  
**Candidate parent recon commit:** `2892efa3c9b212facdc588f5f690fa44284cb0bc`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`  
**Design Authority:**

1. `docs/governance/G5_DEFECT_TRUTH_AND_AUTONOMOUS_DEFECT_HUNTER_FORMAL_DETAILED_DESIGN_V1.md`
2. `docs/governance/00.8_G5_DETAILED_DESIGN_REVIEW_AND_ENGINEERING_AUTHORIZATION.md`

> This candidate is not frozen authority yet. Construction remains forbidden until Contract Review, CodeContract freeze, ExecutionContract and Pre-Execution Drift Check all pass.

---

## 0. Contract objective

G5 shall add the product integration required to turn exact G4 observations/evidence into defensible Defect Truth by composing the existing frozen authorities:

```text
G2/G2.1 Task + Router + Session governance
      |
      v
G4 observation/oracle/evidence
      |
      v
R3.6 TestAnomaly -> Candidate -> Evidence -> Correlation
     -> Reproducibility/Causal Proof -> False Positive -> DefectAssessment -> RCA
      |
      +---- required policy ----> R2.6 HumanGate
      |
      v
R4.3 ConfirmedDefectLifecycle
```

G5 is an integration/application layer. It is not a new durable defect database, not a new fix lifecycle, and not a direct execution provider.

---

# 1. Non-negotiable invariants

The implementation SHALL preserve mechanically:

```text
TEST_FAIL != CONFIRMED_DEFECT
G4_EXECUTION_OBSERVATION != G5_DEFECT_TRUTH
SINGLE_500 != CONFIRMED_DEFECT
ERROR_STRING != DEFECT_IDENTITY
LLM_CONFIDENCE != DEFECT_TRUTH
STATIC_CODE_JUDGMENT != DEFECT_TRUTH
RCA_GUESS != RCA_ESTABLISHED
DUPLICATE_SYMPTOM != NEW_DEFECT
AGENT != SESSION_LIFECYCLE_OWNER
G5 != G4_EXECUTOR
G5 != G3_CASE_AUTHORITY
G5 != R4_3_FIX_AUTHORITY
G5 != G6_CLOSED_LOOP
```

R1 Event Stream remains sole durable Runtime Truth.

Forbidden Product Truth/write paths:

- `aitest_runtime/defects.py`
- legacy `observations/diagnoses/defects/defect_observations` SQL tables
- `aitest.db`
- any new G5 SQLite/JSON defect store
- any new G5 durable extension duplicating R3.6/R4.3 objects

---

# 2. Required code shape

## 2.1 New integration package

Construction SHALL add:

```text
workspace-template/ai-test/runtime/aitest_runtime/g5/
    __init__.py
    contracts.py
    admission.py
    service.py
    policy.py
```

Purpose:

- `contracts.py`: non-durable integration envelopes/results only;
- `admission.py`: exact G4 -> R3.6 admission validation/mapping;
- `policy.py`: human-review, duplicate/correlation and confirmation policy decisions;
- `service.py`: composition facade over frozen R3.6/R4.3/R2.6/G2/G4 facts;
- `__init__.py`: stable product imports only.

The package SHALL NOT register a new Event extension, SQL schema, projection database, evidence store or defect store.

## 2.2 Existing files allowed to change by this CodeContract

The final implementation is expected to require only these integration surfaces plus tests/validation runner:

```text
workspace-template/ai-test/runtime/aitest_runtime/product_entry.py
workspace-template/ai-test/runtime/aitest_runtime/g2_1/router.py
workspace-template/.opencode/tools/aitest.ts
workspace-template/.opencode/agents/aitest-diagnosis.md   # only if wording must match frozen action semantics
workspace-template/.pfc-internal-field-validation/tests/test_g5_*.py
tools/<canonical G5 validation runner or extension of existing runner>
```

Frozen R3.6/R4.3/G3/G4 domain modules SHALL be reused without semantic rewrite. Any discovered need to change a frozen invariant is `REPLAN`, not implementation scope expansion.

---

# 3. Integration contract types

`g5/contracts.py` SHALL define only non-authoritative integration envelopes. At minimum:

### `G5WorkerBinding`

Fields:

```text
mission_id
task_id
attempt_id
root_attempt_id
session_id
logical_agent_id
router_role = DEFECT_HUNTER
agent_name = aitest-diagnosis
route_source
```

It is a validated view of G2.1/R2.5 facts, not a new stored binding.

### `G4ObservationAdmission`

Fields:

```text
mission_id
observation_ref + exact digest/fingerprint
step_result_ref + exact digest/fingerprint
oracle_result
scope(project_id, environment_id, version_scope)
quality_version_ref
campaign_refs
case_ref + case_version
case_value_link_ref
strategy_refs
execution_batch_ref
execution_attempt_ref
step_cursor_ref
expected_ref
actual_ref/evidence_refs
source_identity_ref
execution_node_ref
```

Missing mandatory exact lineage fails closed.

### `GovernedEvidenceRequest`

Fields:

```text
request_id
mission_id
candidate_id
requested_channels[]
reason/evidence_gap
mode = EXISTING_TYPED_REFS | NEW_GOVERNED_ACTION
required_scope
risk_class
planner_or_task_refs[]
```

This envelope is not durable truth by itself. For `NEW_GOVERNED_ACTION`, canonical truth is the resulting G2/G3/G4 Task/Attempt/Observation/Evidence refs.

### `DuplicateCorrelationDecision`

```text
NONE
SAME_OPEN_CANDIDATE
SAME_CONFIRMED_LIFECYCLE
AMBIGUOUS_REVIEW_REQUIRED
```

Decision evidence must contain typed structural/causal refs. Error text/HTTP status alone is invalid.

### `G5OperationResult`

Every product result SHALL include:

```text
truth_source = R1_EVENT_STREAM
status
mission_id when scoped
head_seq when available
canonical_refs
next_required_action when blocked/pending
```

No result may claim a new truth source.

---

# 4. DEFECT_HUNTER Logical Agent contract

## 4.1 Canonical Router role

`AgentRoleRegistry.default()` SHALL add one canonical role:

```text
role = DEFECT_HUNTER
agent_name = aitest-diagnosis
```

Required capabilities:

```text
OPENCODE_AGENT
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

`DIAGNOSIS` SHALL NOT become a second Router identity. It is only a product/OpenCode compatibility alias normalized to `DEFECT_HUNTER`.

## 4.2 Session lifecycle

The G5 package and Diagnosis Agent SHALL have no API that creates, closes, rotates or chooses Sessions.

All such actions remain G2.1 Session Router/Supervisor/R2.5 authority.

---

# 5. Exact worker admission contract

Every `DEFECT_HUNTER`/`DIAGNOSIS` product action, including read-only `work_context`, SHALL require payload fields:

```text
mission_id
task_id
attempt_id
session_id
```

`product_entry._require_g5_worker_binding(...)` SHALL fail closed unless all checks pass:

1. durable G2.1 TaskRouteRequirement exists for `task_id`;
2. route role is exactly `DEFECT_HUNTER`;
3. route agent is exactly `aitest-diagnosis`;
4. exact R1.3B ExecutionAttempt exists for supplied `attempt_id`;
5. Attempt Mission/Task equal supplied Mission/Task;
6. Attempt runtime Session equals supplied `session_id`;
7. expected logical agent id is the Router deterministic identity for `aitest-diagnosis + task_id`;
8. R2.5 state contains a `LogicalAgentBinding` matching the active Attempt lineage:
   - same mission_id;
   - same task_id;
   - same attempt_id or current rotated successor Attempt under the same root_attempt_id;
   - same root_attempt_id;
   - same current session_id;
   - same logical_agent_id;
9. current Core Session exists and is OPEN for the action;
10. any present `opencode_agent` Session attribute is either absent by frozen R2.5 rotation semantics or exactly `aitest-diagnosis`.

A stale predecessor Session after rotation SHALL be rejected even if its conversation still exists.

Required failure codes include:

```text
G5_ROUTE_REQUIRED
G5_ROUTE_ROLE_MISMATCH
G5_ATTEMPT_NOT_FOUND
G5_ATTEMPT_TASK_MISMATCH
G5_ATTEMPT_SESSION_MISMATCH
G5_LOGICAL_AGENT_BINDING_MISSING
G5_LOGICAL_AGENT_BINDING_MISMATCH
G5_SESSION_NOT_OPEN
```

---

# 6. Canonical `g5_command` product seam

Add:

```python
g5_command(role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]
```

and CLI surface:

```text
python -m aitest_runtime.product_entry g5 --role <ROLE> --action <ACTION> --payload <JSON>
```

## 6.1 Role normalization

Allowed product roles:

```text
DIRECTOR
DEFECT_HUNTER
DIAGNOSIS   # alias -> DEFECT_HUNTER
```

Any other role fails closed.

## 6.2 DIRECTOR actions

Exact candidate action set:

```text
status
intake_observations
investigation_status
open_investigation
request_human_review
canonical_defects
```

DIRECTOR may coordinate/read durable truth but may not write R3.6 investigation stages pretending to be the worker and may not execute G4 providers directly.

## 6.3 DEFECT_HUNTER / DIAGNOSIS actions

Exact candidate action set:

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

All non-status worker actions use the exact binding in Section 5. `status` is allowed without mutation; when candidate/Mission-scoped worker context is requested it still requires exact binding.

No generic passthrough action or arbitrary command name is allowed.

---

# 7. G4 -> R3.6 exact anomaly admission

`g5/admission.py` SHALL accept only exact durable G4 facts.

For `record_anomaly`:

1. resolve the supplied G4 observation ref from the same Mission;
2. require event/fact type `UNEXPECTED_OBSERVATION`;
3. require `status = OBSERVATION_ONLY`;
4. require `g5_defect_truth = HOLD` at the G4 fact;
5. require eligible trigger derived from G4 oracle/observation:
   `FAIL | ERROR | INCONCLUSIVE | EVIDENCE_INSUFFICIENT | ORACLE_CONTRADICTION | PAGE_RUNTIME_CONFLICT | JOURNEY_ANOMALY`;
6. resolve `step_result_ref` and validate exact digest/fingerprint;
7. validate G4 execution lineage against supplied Mission/Task/Attempt/Session and case/execution scope;
8. validate QualityVersion/Campaign and case/strategy refs when required by the source execution;
9. map only typed refs/digests into R3.6; never copy raw evidence bodies.

R3.6 `TestAnomaly` mapping SHALL be deterministic from the G4 identity. The anomaly shall include:

```text
scope = exact project/environment/version scope
trigger = normalized eligible trigger
upstream_refs = exact G4 observation + step result + case/execution refs
source_refs = exact source/build/deployment/quality-version/campaign refs as available
evidence_refs = safe G4 EvidenceRecord IDs only
observed_digests = G4 oracle/expected/actual/evidence digests
candidate_signal = observation trigger/signature without claiming product defect
origin_lineage = {
  mission_id,
  architecture_baseline_ref: "v7",
  source: "G5_G4_ADMISSION",
  g4_observation_ref,
  task_id,
  attempt_id
}
```

The implementation SHALL NOT modify frozen R3.6 `ARCHITECTURE_BASELINE_REF = v5`; G5 explicitly supplies v7 lineage for G5-originated commands.

`record_anomaly` may create only `TestAnomaly`. It cannot create `DefectAssessment` or R4.3 lifecycle in the same call.

---

# 8. Candidate formation and alternative hypotheses

`create_candidate` SHALL delegate to `R36ApplicationService.create_defect_candidate`.

A candidate may use initial classification `PRODUCT_DEFECT_CANDIDATE`, but it must include explicit alternative classifications appropriate to the signal. The implementation must support at least:

```text
ENVIRONMENT_PROBLEM
TEST_DATA_PROBLEM
AUTOMATION_DEFECT
CASE_SPEC_DEFECT
KNOWLEDGE_FACT_ERROR
UNKNOWN_INCONCLUSIVE
```

Auth/session runtime and deployment/build mismatch are expressed through the correct frozen R3.6 non-product class plus typed evidence basis; no new competing final-classification enum is introduced.

`hypothesis` is a hypothesis, never truth. Supporting and contradicting evidence refs remain visible.

---

# 9. Evidence deepening contract

## 9.1 Existing bounded evidence

For already available typed evidence, G5 SHALL use frozen R3.6 `InvestigationWorkSetRequest/Receipt` and bounded retrieval limits.

It SHALL preserve R3.6 limits and secret-field rejection. Raw browser/CAT/API/DB bodies SHALL NOT be bulk-injected into model context.

`request_evidence_deepening` in this mode records the R3.6 EvidenceDeepeningReceipt and returns the bounded WorkSet receipt/digest/cursor.

## 9.2 New real action required

If the evidence gap requires any new real action, including:

- rerunning/reproducing a case;
- UI/browser action;
- focused API call;
- CAT/log query;
- DB query;
- new environment/deployment observation;
- additional G3 case/strategy work;

G5 SHALL NOT call provider adapters or G4 execution service directly.

Instead it SHALL produce a `GovernedEvidenceRequest` and hand it to the existing G2/G3/G4 governed orchestration path. Canonical proof of completion is the resulting Task/Attempt/Session + G3/G4 durable refs. G5 resumes investigation only after those refs are admitted.

No G5 code may import/call local provider adapters (`browser-action`, `api-http`, `cat-log-query`, `db-select`, etc.) as an execution shortcut.

For mutating/destructive reproduction, existing G4 safety/approval gates remain mandatory.

Required failure code when bypass is attempted:

`G5_DIRECT_EXECUTION_FORBIDDEN`.

---

# 10. Evidence assessment / correlation / reproducibility

The following actions are thin governed mappings to frozen R3.6 operations:

```text
record_evidence_assessment -> R36ApplicationService.record_evidence_assessment
correlate_sources          -> R36ApplicationService.record_cross_source_correlation
evaluate_reproducibility   -> R36ApplicationService.evaluate_reproducibility
assess_false_positive      -> R36ApplicationService.assess_false_positive
record_rca                 -> R36ApplicationService.record_rca
record_checkpoint          -> R36ApplicationService.record_investigation_checkpoint
```

G5 SHALL NOT weaken R3.6 schema validation.

Evidence sufficiency remains:

```text
SUFFICIENT | INSUFFICIENT | CONFLICTED
```

Unavailable evidence remains explicit `UNAVAILABLE/NOT_CONFIGURED/BLOCKED/INVALID/REDACTED`; it is never converted to supportive evidence.

Reproducibility states remain frozen R3.6 values. `REPRODUCED` requires typed reproduction refs. If reproduction is unsafe/impossible, confirmation requires non-empty durable typed causal-basis refs.

`NOT_FALSE_POSITIVE` must reference evidence showing relevant alternatives were actually excluded. It may not be generated solely from model confidence.

---

# 11. Defect confirmation + canonical R2.6 HumanGate policy

## 11.1 Base confirmation

`assess_defect_truth` delegates to the frozen R3.6 `DefectAssessment` gate and SHALL never bypass its handler validation.

Normal functional defects may be autonomously confirmed only after all frozen R3.6 confirmation conditions pass.

## 11.2 Mandatory human-review triggers

Before a proposed `CONFIRMED_DEFECT` is written to R3.6, G5 SHALL require a resolved canonical R2.6 HumanGate when any condition is true:

```text
highest severity (S0/S1 or project-equivalent highest tier)
Security-sensitive
Performance-sensitive
Regulatory-sensitive
ambiguous canonical-defect merge
required confirmation evidence source unavailable
high-risk/destructive reproduction required
explicit project confirmation policy
```

If review is required and no resolved allow decision exists, G5 SHALL **not** call `R36ApplicationService.assess_defect_truth(... CONFIRMED_DEFECT ...)`.

It shall open/reuse one deterministic R2.6 gate bound to the exact Mission/Task/root Attempt/origin Attempt/origin Session.

Canonical gate contract:

```text
gate_kind = G5_DEFECT_CONFIRMATION_REVIEW
decision_policy_id = g5-defect-confirmation-policy
decision_policy_version = 1
allowed outcomes:
  CONFIRM_DEFECT        -> RESUME_EXECUTION
  REJECT_DEFECT         -> BLOCK
  REQUEST_MORE_EVIDENCE -> PLAN_REVISION
```

The gate request contains only typed refs/digests to candidate/evidence/reproducibility/false-positive/correlation facts; no raw secrets.

`CONFIRM_DEFECT` permits a subsequent exact `assess_defect_truth` call; it does not itself fabricate R3.6 DefectAssessment.

`REJECT_DEFECT` blocks confirmation and requires an explicit non-confirmed R3.6 outcome/next investigation decision.

`REQUEST_MORE_EVIDENCE` returns to governed investigation planning.

---

# 12. Duplicate / canonical-defect correlation

G5 SHALL never deduplicate solely by:

```text
HTTP status
exception/error string
stack-trace text
LLM similarity/confidence
single component name
```

Correlation evidence should consider typed refs for:

- requirement/business-rule identity;
- changed-code/root-component identity;
- causal chain/mechanism;
- Journey transition/state;
- API/data contract violation;
- build/deployment identity;
- reproduction signature;
- cross-layer L1-L7 manifestations.

## 12.1 Open candidate correlation

If a new anomaly is proven to be another manifestation of an existing open candidate, G5 SHALL avoid a second independent defect truth. It records R3.6 `CrossSourceCorrelation` against the canonical open candidate and may use R3.6 `SemanticReuse` for immutable prior facts.

## 12.2 Existing confirmed lifecycle correlation

If typed causal evidence proves the manifestation belongs to an existing R4.3 lifecycle, `handoff_confirmed_defect` SHALL return/reuse that lifecycle rather than opening a second canonical lifecycle. The reuse is recorded through R3.6 `SemanticReuse` with exact existing lifecycle id/digest and source command identity.

If correlation is ambiguous, decision = `AMBIGUOUS_REVIEW_REQUIRED`; G5 must keep candidates distinct or raise R2.6 HumanGate. It may not silently merge.

---

# 13. Exact R4.3 handoff

`handoff_confirmed_defect` SHALL accept only:

```text
mission_id
candidate_id
defect_assessment_ref
defect_assessment_digest
quality_version_ref
campaign_refs[]
optional severity_refs[]
optional priority_refs[]
optional rca_refs[]
optional evidence_refs[]
optional resolved HumanGate ref when policy required
optional canonical-correlation decision/ref
```

Before calling R4.3 it SHALL:

1. replay R3.6 in the same Mission;
2. resolve the exact DefectAssessment and digest;
3. require outcome `CONFIRMED_DEFECT`;
4. re-check underlying candidate/evidence/reproducibility/false-positive via the frozen R4.3 adapter path;
5. enforce required HumanGate decision when applicable;
6. enforce duplicate-correlation decision;
7. call only `R43ApplicationService.open_confirmed_defect_lifecycle(...)` for a new canonical lifecycle.

R4.3 remains session-independent for the durable lifecycle write (`session_id = None`). The triggering G5 worker action, however, must have passed the exact worker binding before handoff.

G5 SHALL NOT call:

```text
record_fix_link
request_fix_detection
record_fix_detection_assessment
```

G5 SHALL NOT close defects, detect fixes, dispatch retests or run G6 behavior.

---

# 14. Restart / checkpoint / Session-rotation recovery

`work_context` SHALL rebuild from durable truth only:

```text
R1 Mission/Goal/Plan/Task/Attempt
current G2.1 route + R2.5 binding/current Session
G4 observation/execution/evidence refs
G3 requirement/change/case/strategy refs
R3.6 candidate stages and latest checkpoint
R4.1 QualityVersion/Campaign refs
R4.3 lifecycle if present
open/resolved R2.6 HumanGates
provider/evidence availability statuses
```

Recovery algorithm:

1. validate the **current** Router/R2.5 worker binding;
2. replay R3.6 state for the candidate;
3. select the latest valid checkpoint by Event order for that candidate;
4. validate checkpoint WorkSet digest/cursor against retrievable bounded evidence;
5. treat checkpoint `session_ref` as historical provenance only;
6. continue in the current G2.1-assigned Session without rewriting the candidate.

Conversation history is never required for resume.

A stale predecessor Session cannot resume after Router rotation.

---

# 15. Evidence and secret safety

G5 SHALL reuse G4 and R3.6 redaction/reference rules.

Never durably persist raw:

```text
password / OTP / captcha / face / secret answer
Authorization / Cookie / access-token / refresh-token / session secret
credential-bearing browser storage state
unredacted customer/DB data solely for diagnosis convenience
raw CAT/API/UI payload merely because the model requested more context
```

`work_context` receives bounded typed refs/digests/safe summaries only.

Attempt to pass forbidden raw/secret keys into R3.6/G5 integration shall fail closed.

---

# 16. OpenCode Diagnosis tool contract

`workspace-template/.opencode/tools/aitest.ts` SHALL add a `g5(...)` helper matching the existing canonical `g3(...)` / `g4(...)` subprocess pattern:

```text
portable Python
-m aitest_runtime.product_entry g5
--role DIAGNOSIS
--action <action>
--payload <json>
```

The helper SHALL:

- run only in canonical workspace;
- use canonical portable Python/runtime env;
- require JSON response;
- require `truth_source = R1_EVENT_STREAM`;
- fail closed on nonzero exit/invalid JSON/truth-source drift.

`diagnosis` tool SHALL stop returning the current G5 HOLD and call this canonical helper.

Allowed Diagnosis action description SHALL match Section 6.3 exactly.

No TypeScript-side direct defect storage, provider invocation or heuristic confirmation is permitted.

---

# 17. Legacy / direct-path static prohibitions

Fresh static/adversarial checks SHALL fail construction if G5 product source imports or references as write authority:

```text
aitest_runtime.defects
from .defects
legacy observations/diagnoses/defects SQL
aitest.db
AUTO_CONFIRMED
direct cat.query/browser/db/api provider invocation from g5 package
G3 case mutation from g5 package
R4.3 fix-link/fix-detection mutation from g5 package
G6 mutation
```

Legacy files may remain physically present for compatibility/history; their existence alone is not failure. Canonical G5 source dependency on them is failure.

---

# 18. Required failure semantics

At minimum, the canonical product path SHALL expose deterministic failure codes for:

```text
G5_ROLE_FORBIDDEN
G5_ACTION_FORBIDDEN
G5_ROUTE_REQUIRED
G5_ROUTE_ROLE_MISMATCH
G5_ATTEMPT_NOT_FOUND
G5_ATTEMPT_TASK_MISMATCH
G5_ATTEMPT_SESSION_MISMATCH
G5_LOGICAL_AGENT_BINDING_MISSING
G5_LOGICAL_AGENT_BINDING_MISMATCH
G5_G4_ADMISSION_INVALID
G5_G4_LINEAGE_MISSING
G5_EVIDENCE_REF_INVALID
G5_DIRECT_EXECUTION_FORBIDDEN
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

Errors must not leak secrets/raw evidence.

---

# 19. Fresh test contract

New tests SHALL live in the real existing test topology:

`workspace-template/.pfc-internal-field-validation/tests/`

At minimum the implementation SHALL add focused suites equivalent to:

```text
test_g5_product_path.py
test_g5_worker_binding_and_recovery.py
test_g5_adversarial_defect_truth.py
test_g5_human_gate_and_duplicate_correlation.py
test_g5_same_mission_e2e.py
test_g5_opencode_surface.py
```

Exact filenames may be adjusted only by Contract Review before freeze; semantic nodes below are mandatory.

## 19.1 Positive/foundation gates

Fresh tests must prove:

1. G4 FAIL produces observation only, never confirmed defect.
2. exact G4 lineage is required to create R3.6 TestAnomaly.
3. v7 G5 origin lineage is present without modifying frozen R3.6 v5 constant.
4. DEFECT_HUNTER Router role resolves to `aitest-diagnosis`.
5. exact G2.1/R2.5 Mission/Task/Attempt/Session/LogicalAgent binding is required.
6. bounded WorkSet deepening records digest/cursor and no raw payload.
7. newly required real evidence returns to governed G2/G3/G4 path.
8. alternative hypotheses and contradicting evidence remain explicit.
9. `NOT_FALSE_POSITIVE` is required.
10. reproduction or durable causal basis is required.
11. unresolved contradictions prevent confirmation.
12. normal functional evidence-complete defect may autonomously confirm.
13. highest-severity/security/performance/regulatory confirmation opens/reuses R2.6 HumanGate before R3.6 CONFIRMED_DEFECT write.
14. exact confirmed R3.6 assessment opens R4.3 lifecycle.
15. Session rotation/restart resumes from R1/R3.6 checkpoint in the new current Session.
16. same proven root cause with multiple manifestations can reuse one canonical lifecycle.

## 19.2 Mandatory adversarial gates

Fresh tests must prove rejection/non-confirmation for:

```text
single API 500 without corroboration
exception/error string only
LLM 99% confidence only
static code suspicion only
stale deployment/build
wrong test data
stale/wrong case expected result
automation selector failure
auth/session expiry
CAT unavailable
repro blocked with no causal proof
conflicted DB vs API evidence
same error text from different components
ambiguous duplicate merge
stale predecessor Session after rotation
wrong Task
wrong Attempt
wrong Session
wrong LogicalAgent route
raw secret/evidence payload injection
legacy defects.py AUTO_CONFIRMED invocation
direct G4 provider bypass
G3 Standard Case mutation from G5
R4.3 fix mutation from G5
G6 action from G5
```

## 19.3 Same-Mission E2E

One fresh E2E SHALL execute in a single durable Mission:

```text
G2 plan/task with DEFECT_HUNTER route
-> G4 governed execution FAIL/UnexpectedObservation
-> G5 exact intake
-> R3.6 TestAnomaly
-> DefectCandidate with alternatives
-> bounded evidence deepening
-> governed reproduction or causal proof
-> cross-source correlation
-> EvidenceAssessment
-> reproducibility
-> false-positive exclusion
-> DefectAssessment CONFIRMED_DEFECT
-> RCA
-> exact R4.3 ConfirmedDefectLifecycle
```

The E2E must verify all canonical IDs/digests and must not call legacy defect truth.

---

# 20. Regression / closure gates

Before G5 can become Engineering PASS candidate, fresh evidence SHALL show:

```text
runtime.verify_projection = PASS
all pre-existing frozen G1-G4 validation suites = PASS
G5 focused suites = PASS
G5 adversarial suites = PASS
G5 same-Mission E2E = PASS
legacy aitest.db not created/modified by G5 test path
PR #2 remains Draft / UNMERGED
main remains unchanged
G6 remains HOLD
```

The canonical aggregate runner must include G5 suites without deleting or weakening existing G1-G4 suites.

---

# 21. Explicit non-scope

This CodeContract does not authorize:

- ArchitectureBaseline modification;
- R3.6/R4.3 semantic rewrite;
- new Defect/Fix durable schema;
- defect UI/productization beyond the existing OpenCode/product entry seam;
- automatic fix detection/retest/learning loop;
- G6;
- direct main write or PR merge;
- G5 freeze by 10.G5.

---

# 22. Candidate gate result

```text
G5_CODE_CONTRACT_CANDIDATE = FORMED
DESIGN_AUTHORITY_DRIFT = NOT_DETECTED_AT_CANDIDATE_FORMATION
IMPLEMENTATION_STARTED = NO
CODE_CONTRACT_FROZEN = NO
EXECUTION_CONTRACT = NOT_STARTED
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
NEXT_GATE = DESIGN_TO_CODE_REALITY_CHECK + CONTRACT_REVIEW
```
