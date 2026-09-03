# G5 — Defect Truth & Autonomous Defect Hunter CodeContract Candidate

**Status:** `CODE_CONTRACT_CANDIDATE / REALITY_CHECK_REPAIRED / CONTRACT_REVIEW_REQUIRED`  
**WorkItem:** `10.G5｜Defect Truth & Autonomous Defect Hunter`  
**Governance authority:** `00.8` only  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical frozen main:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Engineering branch:** `work/g5-defect-truth`  
**Repository Reality Recon commit:** `2892efa3c9b212facdc588f5f690fa44284cb0bc`  
**Initial candidate commit:** `9c7bc8bca4d8d74aa32dad732cc188012595b23c`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`  
**Design Authority:**

1. `docs/governance/G5_DEFECT_TRUTH_AND_AUTONOMOUS_DEFECT_HUNTER_FORMAL_DETAILED_DESIGN_V1.md`
2. `docs/governance/00.8_G5_DETAILED_DESIGN_REVIEW_AND_ENGINEERING_AUTHORIZATION.md`

> This candidate is not frozen authority. Construction remains forbidden until Contract Review, CodeContract freeze, ExecutionContract and Pre-Execution Drift Check all pass.

## Reality-check repairs already incorporated

The first candidate was deliberately checked against raw source before review. This repaired candidate corrects three implementation-critical assumptions:

1. the real G2/G2.1 capability is `OPENCODE_AGENT_SESSION`, not an invented `OPENCODE_AGENT` capability;
2. frozen R2.5 keeps one immutable LogicalAgentBinding anchored to the **root Attempt** across Session rotation, so G5 exact worker admission must compose **current R1.3B Attempt/Session** validation with the **root R2.5 LogicalAgentBinding**, rather than demand a new R2.5 binding for every successor Session;
3. when investigation needs new real work, G5 cannot invent a new task/request truth: it must return a bounded `GOVERNED_WORK_REQUIRED` request which is materialized by the existing G2 Planner/PlanRevision/Scheduler path and then executed by G3/G4 according to the resulting Router-bound Task.

---

# 0. Contract objective

G5 shall add the product integration required to turn exact G4 observations/evidence into defensible Defect Truth by composing the existing frozen authorities in the existing canonical RuntimeService:

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
      +---- policy requiring human decision ----> R2.6 HumanGate
      |
      v
R4.3 ConfirmedDefectLifecycle
```

G5 is an integration/application layer. It is not a new durable defect database, not a new Event extension, not a new fix lifecycle, and not a direct execution provider.

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

R1 Event Stream remains the sole durable Runtime Truth.

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
    policy.py
    service.py
```

Purpose:

- `contracts.py`: non-durable integration envelopes/results only;
- `admission.py`: exact G4 -> R3.6 admission validation/mapping;
- `policy.py`: human-review, duplicate/correlation and confirmation policy decisions;
- `service.py`: integration facade over the already-composed canonical RuntimeService and frozen R3.6/R4.3/R2.6/G2/G4 facts;
- `__init__.py`: stable product imports only.

The package SHALL NOT register a new Event extension, SQL schema, projection database, evidence store or defect store. `canonical_runtime.canonical_extension_manifests()` SHALL remain without a G5 durable extension.

## 2.2 Existing files authorized for additive integration changes

Expected integration surfaces:

```text
workspace-template/ai-test/runtime/aitest_runtime/product_entry.py
workspace-template/ai-test/runtime/aitest_runtime/g2_1/router.py
workspace-template/.opencode/tools/aitest.ts
workspace-template/.opencode/agents/aitest-diagnosis.md   # only if wording must match frozen action semantics
workspace-template/.pfc-internal-field-validation/tests/test_g5_*.py
tools/<canonical G5 validation runner or additive extension of existing runner>
```

Frozen R3.6/R4.3/G3/G4 domain modules SHALL be reused without semantic rewrite. Any discovered need to weaken or alter a frozen invariant is `REPLAN`, not implementation scope expansion.

---

# 3. Integration contract types

`g5/contracts.py` SHALL define only non-authoritative integration envelopes.

## 3.1 `G5WorkerBinding`

Fields:

```text
mission_id
task_id
current_attempt_id
root_attempt_id
current_session_id
logical_agent_id
router_role = DEFECT_HUNTER
agent_name = aitest-diagnosis
route_source
r2_5_binding_id
r2_5_anchor_attempt_id
r2_5_anchor_session_id
```

This is a validated composite view of current R1.3B execution lineage + G2.1 route + immutable R2.5 root LogicalAgentBinding. It is never stored as a second binding.

## 3.2 `G4ObservationAdmission`

Fields:

```text
mission_id
g4_goal_id
observation_ref + exact digest/fingerprint
step_result_ref + exact digest/fingerprint
oracle_result
scope(project_id, environment_id, version_scope)
quality_version_ref
campaign_refs[]
case_ref + case_version
case_value_link_ref
strategy_refs[]
execution_batch_ref
execution_attempt_ref
step_cursor_ref
expected_ref
actual_ref/evidence_refs[]
source_identity_ref
execution_node_ref
```

Missing mandatory exact lineage fails closed.

## 3.3 `GovernedEvidenceRequest`

Fields:

```text
request_id
mission_id
candidate_id
requested_channels[]
reason / evidence_gap
mode = EXISTING_TYPED_REFS | NEW_GOVERNED_ACTION
required_scope
risk_class
preferred_role = EXECUTOR | TEST_STRATEGIST | CASE_DESIGNER | other already-registered canonical G2.1 role
existing_task_refs[]
planner_constraints[]
```

This envelope is never durable Task truth. For `NEW_GOVERNED_ACTION`, canonical truth begins only after the existing G2 Planner accepts a Plan/PlanRevision containing the requested governed work.

## 3.4 `DuplicateCorrelationDecision`

```text
NONE
SAME_OPEN_CANDIDATE
SAME_CONFIRMED_LIFECYCLE
AMBIGUOUS_REVIEW_REQUIRED
```

Decision evidence must contain typed structural/causal refs. Error text/HTTP status/model similarity alone is invalid.

## 3.5 `G5OperationResult`

Every product result SHALL include:

```text
truth_source = R1_EVENT_STREAM
status
mission_id when scoped
head_seq when available
canonical_refs[]
next_required_action when blocked/pending
```

No result may claim a new truth source.

---

# 4. DEFECT_HUNTER Logical Agent contract

## 4.1 Canonical Router role

`AgentRoleRegistry.default()` SHALL expose one canonical persisted G5 routing role:

```text
role = DEFECT_HUNTER
agent_name = aitest-diagnosis
```

Required capabilities use the actual existing Router capability spelling:

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

The existing `DIAGNOSIS` spelling SHALL remain compatibility-only. Resolution of `DIAGNOSIS` for product compatibility must normalize to the same canonical DEFECT_HUNTER role/agent/capabilities; newly registered G5 `TaskRouteRequirement.role` SHALL be `DEFECT_HUNTER`, never a second durable `DIAGNOSIS` role identity.

No other existing G2.1 role semantics are changed.

## 4.2 Session lifecycle

The G5 package and Diagnosis Agent SHALL have no API that creates, closes, rotates, observes or chooses Sessions.

All Session creation/rotation/reconciliation remains G2.1 Session Router/Supervisor/R2.5 authority.

---

# 5. Exact worker admission contract

Every `DEFECT_HUNTER`/`DIAGNOSIS` Mission-scoped worker action SHALL require:

```text
mission_id
task_id
attempt_id
session_id
```

`product_entry._require_g5_worker_binding(...)` SHALL fail closed unless all checks pass.

## 5.1 Current execution identity — exact R1.3B binding

1. durable G2.1 TaskRouteRequirement exists for `task_id`;
2. persisted route role is exactly `DEFECT_HUNTER`;
3. route agent is exactly `aitest-diagnosis`;
4. supplied `attempt_id` resolves in R1.3B;
5. supplied Attempt is the current/latest Attempt for this Task;
6. Attempt Mission/Task equal supplied Mission/Task;
7. Attempt `runtime_session_id` equals supplied `session_id`;
8. current Core Session exists and is OPEN for a live worker action;
9. a stale predecessor Session/Attempt after rotation is rejected.

## 5.2 LogicalAgent identity — immutable R2.5 root binding

10. expected logical agent id is the Router deterministic identity for `aitest-diagnosis + task_id`;
11. current Attempt root_attempt_id is resolved;
12. R2.5 state contains the immutable LogicalAgentBinding for that same root Attempt;
13. that binding has the same Mission, Task, root_attempt_id and logical_agent_id;
14. the binding's anchor Attempt exists, belongs to the same root Attempt and Task, and its anchor Session belongs to that same execution lineage;
15. after Session rotation, the R2.5 anchor Attempt/Session MAY be the predecessor because frozen R2.5 intentionally keeps one root binding; **the current Attempt/Session authority remains the exact R1.3B checks in 5.1**;
16. any present current Session `opencode_agent` attribute must be exactly `aitest-diagnosis`; omission is tolerated only where frozen R2.5 successor semantics already permit it.

This composite check is the exact governed action binding. G5 SHALL NOT create a second R2.5 binding merely to make a rotated successor look like the root anchor.

Required failure codes include:

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

# 6. Canonical `g5_command` product seam

Add:

```python
g5_command(role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]
```

and CLI surface:

```text
python -m aitest_runtime.product_entry g5 --role <ROLE> --action <ACTION> --payload <JSON>
```

## 6.1 Product role normalization

Allowed product roles:

```text
DIRECTOR
DEFECT_HUNTER
DIAGNOSIS   # product alias -> DEFECT_HUNTER
```

Any other role fails closed.

## 6.2 DIRECTOR actions and exact responsibility

```text
status
intake_observations
investigation_status
open_investigation
request_human_review
canonical_defects
```

Semantics:

- `status`: read-only G5/R3.6/R4.3 counts/status;
- `intake_observations`: read-only enumeration of exact G4 facts eligible for G5 intake and whether each already maps to R3.6; it does not create TestAnomaly;
- `investigation_status`: read-only R3.6 candidate/checkpoint/HumanGate/R4.3 status;
- `open_investigation`: prepares a bounded Planner work request for a `DEFECT_HUNTER` Task if no suitable canonical Task exists; it does not write WorkGraph/Plan truth itself;
- `request_human_review`: opens/reuses the canonical R2.6 gate only from exact candidate/current Task/Attempt/Session lineage;
- `canonical_defects`: read-only same-Mission R4.3 ConfirmedDefectLifecycle view.

DIRECTOR may coordinate durable authorities but may not write R3.6 investigation stages pretending to be the worker and may not execute G4 providers directly.

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

Every Mission-scoped worker action uses Section 5 binding. A global `status` may be read without mutation; any candidate/Mission-scoped status/work_context requires binding.

No generic passthrough action or arbitrary command name is allowed.

---

# 7. G4 -> R3.6 exact anomaly admission

`g5/admission.py` SHALL accept only exact durable G4 facts from the same canonical RuntimeService.

## 7.1 Current concrete G4 observation path

For current `UNEXPECTED_OBSERVATION` intake:

1. resolve the supplied G4 fact from the same Mission;
2. require `fact_kind = UNEXPECTED_OBSERVATION`;
3. require `status = OBSERVATION_ONLY`;
4. require `g5_defect_truth = HOLD` at the G4 fact;
5. require current concrete G4 oracle trigger `FAIL | ERROR | INCONCLUSIVE`;
6. resolve linked `step_result_ref` and validate its exact fact identity/digest;
7. validate execution lineage against supplied Mission/Task/Attempt/Session and case/execution scope;
8. validate QualityVersion/Campaign and case/strategy refs required by the source execution;
9. map only typed refs/digests into R3.6; never copy raw evidence bodies.

## 7.2 Other Design-authorized anomaly triggers

The frozen design also recognizes:

```text
EVIDENCE_INSUFFICIENT
ORACLE_CONTRADICTION
PAGE_RUNTIME_CONFLICT
JOURNEY_ANOMALY
```

G5 may admit such a trigger **only when an exact durable G4 fact/ref exists for it**. G5 SHALL NOT fabricate a G4 anomaly fact merely because R3.6 accepts the trigger. If the required G4 fact does not yet exist, G5 returns a governed evidence/execution gap and routes new work through Section 9.2.

## 7.3 Deterministic R3.6 mapping

R3.6 `TestAnomaly` identity SHALL be deterministic from the G4 fact identity/digest. Mapping:

```text
scope = exact project/environment/version scope
trigger = admitted G4 trigger
upstream_refs = exact G4 observation + step result + case/execution refs
source_refs = exact source/build/deployment/quality-version/campaign refs as available
evidence_refs = safe G4 EvidenceRecord/fact IDs only
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

The implementation SHALL NOT modify frozen R3.6 `ARCHITECTURE_BASELINE_REF = "v5"`; G5 explicitly supplies v7 lineage for every G5-originated R3.6 command.

`record_anomaly` may create only `TestAnomaly`. It cannot create `DefectAssessment` or R4.3 lifecycle in the same call.

---

# 8. Candidate formation and alternative hypotheses

`create_candidate` SHALL delegate to `R36ApplicationService.create_defect_candidate`.

A candidate may use `PRODUCT_DEFECT_CANDIDATE`, but it must include explicit alternatives appropriate to the signal. The implementation must support at least frozen R3.6 alternatives:

```text
ENVIRONMENT_PROBLEM
TEST_DATA_PROBLEM
AUTOMATION_DEFECT
CASE_SPEC_DEFECT
KNOWLEDGE_FACT_ERROR
UNKNOWN_INCONCLUSIVE
```

Auth/session runtime and deployment/build mismatch are represented through the correct frozen non-product class plus typed evidence basis; no competing G5 classification enum is introduced.

`hypothesis` is not truth. Supporting and contradicting evidence refs remain visible.

---

# 9. Evidence deepening contract

## 9.1 Existing bounded evidence

For already available typed evidence, G5 SHALL use frozen R3.6 `InvestigationWorkSetRequest/Receipt` and its existing item/byte/cursor limits.

Raw browser/CAT/API/DB bodies SHALL NOT be bulk-injected into model context.

`request_evidence_deepening(mode=EXISTING_TYPED_REFS)` records only the canonical R3.6 EvidenceDeepeningReceipt and returns the bounded WorkSet receipt/digest/cursor.

## 9.2 New real action required — exact governed return path

If the evidence gap requires any new real action, including:

- rerunning/reproducing a case;
- UI/browser action;
- focused API call;
- CAT/log query;
- DB query;
- new environment/deployment observation;
- additional G3 case/strategy work;

G5 SHALL NOT call provider adapters, `G4RealExecutionService` capability execution, G3 mutation services, or WorkGraph commands directly from the DEFECT_HUNTER worker.

`request_evidence_deepening(mode=NEW_GOVERNED_ACTION)` SHALL instead return:

```text
status = GOVERNED_WORK_REQUIRED
truth_source = R1_EVENT_STREAM
next_required_action = G2_PLAN_REVISION_REQUIRED | EXISTING_GOVERNED_TASK
requested_work = GovernedEvidenceRequest
```

Rules:

1. if an existing current Plan already contains an exact dependency-valid Task that satisfies the request, G5 may return its Task ref as `EXISTING_GOVERNED_TASK`;
2. otherwise, `G2_PLAN_REVISION_REQUIRED` is mandatory;
3. only the existing G2 `PLANNER/propose_plan` path may create/revise WorkGraph task truth;
4. the accepted task must declare its G2.1 Router role/capabilities, e.g. `EXECUTOR` for new G4 real execution or an existing G3 specialist role for new testing-intelligence work;
5. only the existing Scheduler/Router may dispatch the task and provision/rotate Sessions;
6. G4 providers/safety/HumanGate contracts remain authoritative for real execution;
7. G5 resumes only after the resulting G2/G3/G4 durable Task/Attempt/Observation/Evidence refs are available and re-admitted.

The Diagnosis Agent's context already forbids silent replanning; therefore it may **request** the plan revision but shall not masquerade as the Planner.

No G5 code may import/call local provider adapters (`browser-action`, `api-http`, `cat-log-query`, `db-select`, etc.) as an execution shortcut.

For mutating/destructive reproduction, existing G4 safety/approval gates remain mandatory.

Required failure code for bypass: `G5_DIRECT_EXECUTION_FORBIDDEN`.

---

# 10. Evidence assessment / correlation / reproducibility / false-positive / RCA

These actions are thin governed mappings to frozen R3.6 operations:

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

`REPRODUCED` requires typed reproduction refs. If reproduction is unsafe/impossible, confirmation requires non-empty durable typed causal-basis refs.

`NOT_FALSE_POSITIVE` must reference evidence showing relevant alternatives were actually considered/excluded. It may not be generated from model confidence alone.

RCA uses only frozen R3.6 classes/states. `ESTABLISHED` requires a bounded causal chain; one error string/stack trace cannot establish RCA.

---

# 11. Defect confirmation + canonical R2.6 HumanGate policy

## 11.1 Base confirmation

`assess_defect_truth` delegates to frozen `R36ApplicationService.assess_defect_truth` and SHALL never bypass the R3.6 handler gate.

Normal functional defects may be autonomously confirmed only after all frozen R3.6 conditions pass:

```text
final_classification = PRODUCT_DEFECT
>= 1 SUFFICIENT EvidenceAssessment
false_positive = NOT_FALSE_POSITIVE
reproducibility = REPRODUCED OR causal_basis_refs not empty
unresolved_critical_contradictions = 0
```

## 11.2 Mandatory human-review triggers

Before a proposed `CONFIRMED_DEFECT` write, G5 SHALL require a resolved canonical R2.6 HumanGate when any condition is true:

```text
highest severity (S0/S1 or project-equivalent highest tier)
Security-sensitive
Performance-sensitive
Regulatory-sensitive
multiple plausible candidates with unresolved critical contradiction
ambiguous canonical-defect merge
required confirmation evidence source unavailable where policy demands it
high-risk/destructive reproduction required
explicit project confirmation policy
```

If review is required and no resolved allow decision exists, G5 SHALL NOT call R3.6 with `CONFIRMED_DEFECT`.

It shall open/reuse one deterministic R2.6 gate bound to the exact Mission/Task/root Attempt/origin Attempt/origin Session.

Canonical G5 gate policy:

```text
gate_kind = G5_DEFECT_CONFIRMATION_REVIEW
decision_policy_id = g5-defect-confirmation-policy
decision_policy_version = 1
outcomes/routes:
  CONFIRM_DEFECT        -> RESUME_EXECUTION
  REJECT_DEFECT         -> BLOCK
  REQUEST_MORE_EVIDENCE -> PLAN_REVISION
```

The request contains only typed refs/digests to candidate/evidence/reproducibility/false-positive/correlation facts.

`CONFIRM_DEFECT` permits a subsequent exact R3.6 confirmation attempt; the HumanGate decision itself is not Defect Truth.

`REJECT_DEFECT` blocks confirmation and requires an explicit non-confirmed investigation outcome/next decision.

`REQUEST_MORE_EVIDENCE` follows Section 9.2.

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

## 12.1 Before confirmation: one candidate may correlate multiple sources/manifestations

Within one candidate, G5 records frozen R3.6 `CrossSourceCorrelation` facts. Candidate truth remains immutable; G5 must not mutate historical candidate bodies.

When an immutable prior R3.6 entity can be safely reused, G5 may record frozen R3.6 `SemanticReuse` with the exact entity id/digest/original command id.

## 12.2 Exact duplicate R4.3 handoff

R4.3 lifecycle identity is deterministic from same-Mission R3.6 assessment + QualityVersion + Campaign scope. Replaying the exact same assessment/scope must resolve idempotently to the same lifecycle rather than create a second one.

## 12.3 Later manifestation of an already confirmed same-Mission defect

Automatic `SAME_CONFIRMED_LIFECYCLE` reuse is allowed only when:

1. the lifecycle is in the same Mission;
2. exact lifecycle id/digest is available;
3. typed causal/correlation refs prove the new manifestation is the same defect mechanism/root cause;
4. there is no unresolved contradictory evidence.

G5 records the relationship through R3.6 correlation/semantic-reuse facts; it does not open a second lifecycle.

Cross-Mission canonical-defect merge is **not** silently authorized by this WorkItem because R4.3 admission is same-Mission. A cross-Mission suspected duplicate must remain distinct or become `AMBIGUOUS_REVIEW_REQUIRED` unless a pre-existing canonical cross-Mission identity authority is proven by repository reality.

Ambiguous correlation raises/reuses R2.6 HumanGate or keeps candidates distinct.

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

1. pass Section 5 current worker binding;
2. replay R3.6 in the same Mission;
3. resolve the exact DefectAssessment and digest;
4. require outcome `CONFIRMED_DEFECT`;
5. rely on/reuse the frozen R4.3 adapter to revalidate underlying candidate/evidence/reproducibility/false-positive truth;
6. enforce required HumanGate decision when applicable;
7. enforce duplicate-correlation decision;
8. call only `R43ApplicationService.open_confirmed_defect_lifecycle(...)` for a new canonical lifecycle.

R4.3 writes the lifecycle with its frozen session-independent semantics. The triggering G5 worker action must still have passed Section 5 before handoff.

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
R1 Mission/Goal/Plan/Task/current Attempt
current G2.1 route + current Session
immutable R2.5 root LogicalAgentBinding
G4 observation/execution/evidence refs
G3 requirement/change/case/strategy refs
R3.6 candidate stages and latest checkpoint
R4.1 QualityVersion/Campaign refs
R4.3 lifecycle if present
open/resolved R2.6 HumanGates
provider/evidence availability statuses
```

Recovery algorithm:

1. validate the **current** Router + R1.3B Attempt/Session and root R2.5 LogicalAgent binding using Section 5;
2. replay R3.6 state for the candidate;
3. select the latest valid checkpoint by Event order for that candidate;
4. validate checkpoint WorkSet digest/cursor against retrievable bounded evidence;
5. treat checkpoint `session_ref` as historical provenance only — it is not authority to resurrect a predecessor Session;
6. continue in the current G2.1-assigned Session without rewriting the candidate.

Conversation history is never required for resume.

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

Attempt to pass forbidden raw/secret keys into G5/R3.6 integration fails closed.

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

`diagnosis` SHALL stop returning the current G5 HOLD and call this canonical helper after CodeContract freeze/authorized implementation.

Allowed Diagnosis action description SHALL match Section 6.3 exactly.

No TypeScript-side defect storage, provider invocation or heuristic confirmation is permitted.

---

# 17. Legacy / direct-path static prohibitions

Fresh static/adversarial checks SHALL fail construction if canonical G5 product source imports or references as write authority:

```text
aitest_runtime.defects
from .defects
legacy observations/diagnoses/defects SQL
aitest.db
AUTO_CONFIRMED
direct CAT/browser/DB/API provider invocation from g5 package
G3 Standard Case mutation from g5 package
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

Exact filenames may be adjusted by Contract Review before freeze; the semantic nodes below are mandatory.

## 19.1 Positive/foundation gates

Fresh tests must prove:

1. G4 FAIL creates observation only, never confirmed defect.
2. exact G4 lineage is required to create R3.6 TestAnomaly.
3. v7 G5 origin lineage is present without modifying frozen R3.6 `v5` constant.
4. persisted DEFECT_HUNTER Router role resolves to physical agent `aitest-diagnosis` and actual `OPENCODE_AGENT_SESSION` capability.
5. exact current Mission/Task/Attempt/Session + immutable root R2.5 LogicalAgent binding is required.
6. after Session rotation, the successor current Attempt/Session is accepted only with the same root LogicalAgent binding, while stale predecessor action is rejected.
7. bounded WorkSet deepening records digest/cursor and no raw payload.
8. newly required real evidence returns `GOVERNED_WORK_REQUIRED` and cannot execute until G2 Planner/Scheduler creates/dispatches governed work.
9. alternative hypotheses and contradicting evidence remain explicit.
10. `NOT_FALSE_POSITIVE` is required.
11. reproduction or durable causal basis is required.
12. unresolved contradictions prevent confirmation.
13. normal functional evidence-complete defect may autonomously confirm.
14. highest-severity/security/performance/regulatory confirmation opens/reuses R2.6 HumanGate before R3.6 CONFIRMED_DEFECT write.
15. exact confirmed R3.6 assessment opens R4.3 lifecycle.
16. restart/Session rotation resumes from R1/R3.6 checkpoint in the current Session.
17. same proven root cause with multiple same-Mission manifestations can correlate/reuse one canonical lifecycle.
18. exact same R3.6 assessment + QualityVersion/Campaign handoff is idempotent.

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
cross-Mission silent lifecycle reuse
stale predecessor Session after rotation
wrong Task
wrong Attempt
wrong current Session
wrong LogicalAgent root binding
raw secret/evidence payload injection
legacy defects.py AUTO_CONFIRMED invocation
direct G4/provider bypass
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
-> governed reproduction OR durable causal proof
-> cross-source correlation
-> EvidenceAssessment
-> reproducibility
-> false-positive exclusion
-> DefectAssessment CONFIRMED_DEFECT
-> RCA
-> exact R4.3 ConfirmedDefectLifecycle
```

The E2E must verify canonical IDs/digests and must not call legacy defect truth.

At least one companion E2E/negative path SHALL show that when new evidence is required, G5 first emits `GOVERNED_WORK_REQUIRED`, then only a G2-created Router-bound G4/G3 task can provide the new durable evidence before investigation resumes.

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
- silent cross-Mission canonical-defect merging;
- defect UI/productization beyond the existing OpenCode/product entry seam;
- automatic fix detection/retest/learning loop;
- G6;
- direct main write or PR merge;
- G5 freeze by 10.G5.

---

# 22. Candidate gate result

```text
G5_CODE_CONTRACT_CANDIDATE = FORMED / REALITY_CHECK_REPAIRED
DESIGN_AUTHORITY_DRIFT = NOT_DETECTED
REPOSITORY_REALITY_CONFLICT = RESOLVED_IN_CANDIDATE
IMPLEMENTATION_STARTED = NO
CODE_CONTRACT_FROZEN = NO
EXECUTION_CONTRACT = NOT_STARTED
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
NEXT_GATE = FINAL_DESIGN_TO_CODE_REALITY_CHECK -> CONTRACT_REVIEW
```
