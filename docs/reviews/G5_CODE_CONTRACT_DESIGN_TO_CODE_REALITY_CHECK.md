# G5 CodeContract Design-to-Code Reality Check

**WorkItem:** `10.G5｜Defect Truth & Autonomous Defect Hunter`  
**Status:** `DESIGN_TO_CODE_REALITY_CHECK = PASS_AFTER_CANDIDATE_REPAIR`  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical frozen main:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Engineering branch:** `work/g5-defect-truth`  
**Contract Review candidate:** `docs/governance/G5_DEFECT_TRUTH_AND_AUTONOMOUS_DEFECT_HUNTER_CODE_CONTRACT_CANDIDATE_V2.md`  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`

> This review validates the candidate against raw repository reality. It does not freeze the CodeContract and does not authorize construction.

---

## 1. Review scope

The check was performed against the exact engineering branch and verified the candidate against:

- G2/G2.1 Router and autonomous orchestration;
- frozen R2.5 LogicalAgent/Session rotation semantics;
- frozen R2.6 HumanGate enums, binding and continuation semantics;
- frozen R3.6 investigation/RCA contracts and handlers;
- frozen R4.3 ConfirmedDefectLifecycle adapter/service/state;
- current G4 observation/evidence boundary and evidence safety;
- canonical runtime composition;
- canonical `product_entry.py` and OpenCode `aitest.ts` patterns;
- legacy defect implementation and actual test topology.

---

## 2. Source identity and construction boundary

Verified:

- Engineering source remains the authorized `work/g5-defect-truth` branch.
- Main was not used as a write target.
- No G5 runtime/product code has been constructed during Recon/Candidate formation.
- Current work is governance/review documentation only.

Result: `SOURCE_BOUNDARY = PASS`.

---

## 3. Canonical runtime composition confirms integration-only G5

`canonical_runtime.py` already composes the same RuntimeService with:

```text
r2_5_extension
r2_6_extension
g2_1_extension
g3_extension
g4_extension
r3_6_extension
r4_3_extension
```

The sole runtime database is the canonical R1 Event Stream spine; legacy `aitest.db` is explicitly migration/reference only and product writes are forbidden.

Therefore Candidate V2 correctly forbids a new G5 Event extension/DB and uses G5 only as an application/integration facade.

Result: `NO_SECOND_DURABLE_G5_TRUTH = PASS`.

---

## 4. R3.6 mapping reality

Raw source confirms:

- frozen R3.6 already owns `TestAnomaly`, `DefectCandidate`, bounded WorkSet, EvidenceAssessment, CrossSourceCorrelation, ReproducibilityAssessment, FalsePositiveAssessment, DefectAssessment, RCARecord, InvestigationCheckpoint and SemanticReuse;
- `CONFIRMED_DEFECT` is fail-closed unless final class is PRODUCT_DEFECT, evidence is sufficient, false-positive is excluded, reproduction/causal proof exists and unresolved contradiction refs are empty;
- raw/secret-bearing fields are rejected;
- R3.6 historical local baseline constant remains `v5`;
- R36 service accepts caller-supplied `origin_lineage`, so G5 can preserve frozen R3.6 and explicitly supply `architecture_baseline_ref=v7`.

Candidate V2 matches this reality.

Result: `R3_6_MAPPING = PASS`.

---

## 5. R4.3 handoff reality

Raw source confirms:

- `r4_3/r3_6_adapter.py` resolves an exact same-Mission R3.6 DefectAssessment and digest and independently revalidates candidate/evidence/reproducibility/false-positive facts;
- `R43ApplicationService.open_confirmed_defect_lifecycle(...)` is the canonical post-confirmation seam;
- R4.3 lifecycle identity is deterministic from confirmed assessment + QualityVersion + Campaign scope;
- fix-link and fix-detection operations are separate R4.3 APIs and are not G5 authority.

Candidate V2 limits G5 to the exact open-lifecycle handoff and explicitly excludes fix operations/G6.

Result: `R4_3_HANDOFF = PASS`.

---

## 6. G4 observation/evidence boundary reality

Current G4 source records a governed `EXECUTION_STEP_RESULT`; for current `FAIL/INCONCLUSIVE/ERROR` results it additionally emits:

```text
fact_kind = UNEXPECTED_OBSERVATION
status = OBSERVATION_ONLY
g5_defect_truth = HOLD
step_result_ref = exact G4 result fact
```

G4 rejects direct confirmed-defect mutation and already redacts credential-bearing evidence before durability.

Candidate V2 therefore correctly:

- admits exact G4 facts only;
- keeps G4 observation immutable as Observation;
- creates only R3.6 TestAnomaly at first G5 mutation;
- never treats TEST_FAIL as defect confirmation;
- permits other design-level anomaly triggers only when a typed durable G4 fact actually exists.

Result: `G4_TO_G5_BOUNDARY = PASS`.

---

## 7. G2.1 capability-name conflict found and repaired

Initial candidate incorrectly used an invented `OPENCODE_AGENT` capability.

Raw source defines:

```text
OPENCODE_AGENT_CAPABILITY = "OPENCODE_AGENT_SESSION"
```

and G2.1 Router uses the same `OPENCODE_AGENT_SESSION` capability.

Candidate V2 was repaired to the exact existing capability spelling and adds only G5-specific additive capabilities.

Result: `G2_1_CAPABILITY_REALITY = PASS_AFTER_REPAIR`.

---

## 8. R2.5 Session-rotation binding conflict found and repaired

Initial candidate incorrectly required the R2.5 LogicalAgentBinding's attempt/session fields to equal the current successor Attempt/Session after rotation.

Raw source proves frozen semantics are different:

- R2.5 `LogicalAgentBinding` is immutable to the root Attempt;
- G2 rotation deliberately does **not** create a second binding;
- successor Attempt/Session is new, but logical agent identity survives through the unchanged root_attempt_id;
- current G2 outcome admission validates current Attempt/Session separately and validates the logical-agent root binding separately.

Candidate V2 now freezes the correct composite authority:

```text
current R1.3B latest Attempt + current Session
PLUS
same-root immutable R2.5 LogicalAgentBinding
PLUS
G2.1 DEFECT_HUNTER route
```

Stale predecessor worker actions remain rejected.

Result: `WORKER_BINDING_REALITY = PASS_AFTER_REPAIR`.

---

## 9. New evidence-work routing conflict found and repaired

Repository reality contains no G5-owned Task creator and no canonical durable `GovernedEvidenceRequest` extension. R2.5 delegation can dispatch existing child work but does not create new WorkGraph task truth.

Therefore a G5 worker needing a fresh UI/API/CAT/DB/reproduction/G3 action cannot invent a task and cannot execute a provider directly.

Candidate V2 now freezes:

```text
existing suitable Task
    -> return EXISTING_GOVERNED_TASK
else
    -> return G2_PLAN_REVISION_REQUIRED + bounded GovernedEvidenceRequest
    -> existing PLANNER/propose_plan creates PlanRevision/Task
    -> Scheduler/Router dispatches
    -> G3/G4 performs governed work
    -> G5 resumes from new durable refs
```

Result: `GOVERNED_EVIDENCE_WORK_ROUTE = PASS_AFTER_REPAIR`.

---

## 10. R2.6 HumanGate enum/continuation conflict found and repaired

Initial candidate used semantic names as if they were R2.6 gate/outcome enums.

Raw frozen R2.6 allows only:

```text
GATE_KINDS = APPROVAL | CHOICE | ADDITIONAL_INFORMATION | EXTERNAL_ACTION
OUTCOMES = APPROVED | REJECTED | CHOICE_SELECTED | INFORMATION_PROVIDED | EXTERNAL_ACTION_COMPLETED
ROUTES = NONE | RESUME_EXECUTION | GOAL_REVISION | PLAN_REVISION | BLOCK
```

R2.6 also requires `allowed_routes_by_outcome` to define every frozen outcome, and `RESUME_EXECUTION/PLAN_REVISION` decisions remain `CONTINUATION_PENDING` until canonical successor/PlanRevision continuation proof is recorded.

Candidate V2 now uses:

```text
gate_kind = CHOICE
allowed_outcomes = CHOICE_SELECTED | REJECTED

CHOICE_SELECTED + RESUME_EXECUTION + payload(choice=CONFIRM_DEFECT)
CHOICE_SELECTED + PLAN_REVISION   + payload(choice=REQUEST_MORE_EVIDENCE)
REJECTED        + BLOCK           + payload(choice=REJECT_DEFECT)
```

and requires `HumanGateRecord.is_allowing == True` before G5 proceeds. Human approval does not override R3.6 evidence/contradiction rules.

Result: `R2_6_HUMAN_GATE_REALITY = PASS_AFTER_REPAIR`.

---

## 11. Duplicate/canonical-defect reality

R4.3 provides deterministic same-Mission lifecycle identity but no general cross-Mission canonical-defect merge authority.

Candidate V2 therefore:

- uses R3.6 CrossSourceCorrelation/SemanticReuse for typed same-Mission correlation;
- treats exact assessment/QV/Campaign replay as idempotent;
- permits later same-Mission lifecycle reuse only with exact lifecycle id/digest + causal proof + no contradiction;
- refuses silent cross-Mission merging;
- sends ambiguous merges to review/keeps them distinct.

Result: `DUPLICATE_CORRELATION_SCOPE = PASS`.

---

## 12. OpenCode product seam reality

Current `aitest.ts` already has canonical `g3(...)`/`g4(...)` subprocess helpers that:

- use portable Python;
- invoke `aitest_runtime.product_entry`;
- require JSON;
- require `truth_source = R1_EVENT_STREAM`.

`diagnosis` currently remains explicit G5 HOLD.

Candidate V2 correctly specifies an additive `g5(...)` helper using the same product-entry pattern and forbids TypeScript-side defect truth/provider execution.

Result: `OPENCODE_DIAGNOSIS_SEAM = REAL / CONSTRUCTION_PENDING`.

---

## 13. Legacy negative reality

`aitest_runtime/defects.py` is confirmed legacy and contains behavior incompatible with G5 invariants, including legacy SQL defect tables, deterministic product-defect heuristics, `AUTO_CONFIRMED`, direct CAT access and old fix/retest operations.

Candidate V2 makes canonical dependency on this path an explicit static/adversarial failure.

Result: `LEGACY_DEFECT_PATH = FORBIDDEN / NEGATIVE_GATE_DEFINED`.

---

## 14. Test topology reality

Actual construction tests are under:

`workspace-template/.pfc-internal-field-validation/tests/`

The existing aggregate Wave 2 runner holds G5/G6 today. Candidate V2 places fresh G5 product/adversarial/binding/HumanGate/E2E tests in the real topology and requires all frozen G1-G4 suites to remain intact.

Result: `TEST_TOPOLOGY = PASS`.

---

# 15. Final Design-to-Code result

```text
G5_DESIGN_TO_CODE_REALITY_CHECK = PASS_AFTER_CANDIDATE_REPAIR
INITIAL_CANDIDATE_CONFLICTS_FOUND = 4
  - G2.1 capability-name mismatch
  - R2.5 rotation-binding mismatch
  - new governed evidence-work path under-specified
  - R2.6 gate/outcome/continuation mismatch
ALL_IDENTIFIED_CONFLICTS_REPAIRED_IN_V2 = YES
DESIGN_AUTHORITY_DRIFT = NO
ARCHITECTURE_DRIFT = NO
FROZEN_G1_G2_G2_1_G3_G4_REOPEN_REQUIRED = NO
SECOND_DEFECT_TRUTH_REQUIRED = NO
SECOND_FIX_TRUTH_REQUIRED = NO
RUNTIME_CONSTRUCTION_PERFORMED = NO
CODE_CONTRACT_FROZEN = NO
EXECUTION_CONTRACT = NOT_STARTED
PRE_EXECUTION_DRIFT_CHECK = NOT_STARTED
READY_FOR_CODEX = NO
CONTRACT_REVIEW = READY_TO_REQUEST
```

Only 00.8 / the authorized Contract Review may advance this candidate to `CODE_CONTRACT_FROZEN`.
