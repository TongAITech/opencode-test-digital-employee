# G5 — Defect Truth & Autonomous Defect Hunter Formal Detailed Design v1

**Status:** FORMAL DETAILED DESIGN / 00.8 REVIEW CANDIDATE  
**Governance owner:** 00.8｜ChatGPT Harness 总控与架构治理｜R5  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical main starting commit:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Architecture baseline:** `v7 / FROZEN / UNCHANGED`  
**Prerequisites:** G1/G2/G2R-1/G2.1/G3/G4 = PASS / FROZEN  
**Durable truth:** R1 Event Stream remains the sole durable Runtime Truth  
**Session lifecycle authority:** G2.1 Session Router / Supervisor / R2.5  
**Testing-intelligence authority:** G3  
**Real-execution authority:** G4  
**Defect investigation foundation:** frozen R3.6 `r3_6_defect_investigation_rca`  
**Confirmed-defect lifecycle foundation:** frozen R4.3 `r4_3_confirmed_defect_fix_resolution_lifecycle`  
**Continuous closed-loop boundary:** G6 remains HOLD  
**Bank Internal Pilot Ready:** NO

---

## 0. G5 Mission

G5 converts high-quality G4 execution observations into defensible **Defect Truth**.

G5 is not a failure-labeling layer and is not a bug-count generator.

The product goal is:

```text
G4 OracleFailure / UnexpectedObservation / Evidence
  -> G5 Anomaly Intake
  -> Defect Candidate
  -> Alternative Hypotheses
  -> Evidence Deepening
  -> Cross-source Correlation
  -> Reproducibility / Causal Proof
  -> False-positive Exclusion
  -> Defect Truth Assessment
  -> RCA
  -> Canonical Confirmed Defect Lifecycle (R4.3)
```

North-star value remains **valid defect discovery**: real, reproducible or causally established, non-duplicate, evidence-backed defects that materially help engineering teams find and fix product problems.

Frozen invariants:

```text
TEST_FAIL != CONFIRMED_DEFECT
G4_EXECUTION_OBSERVATION != G5_DEFECT_TRUTH
SINGLE_FAILURE_SIGNAL != PRODUCT_DEFECT
HIGH_CONFIDENCE_LLM_JUDGMENT != DEFECT_TRUTH
RCA_GUESS != RCA_ESTABLISHED
DUPLICATE_SYMPTOM != NEW_DEFECT
```

---

# 1. Repository Reality Recon

## 1.1 Existing R3.6 foundation is real and must be reused

R3.6 already provides durable objects and commands for:

- `TestAnomaly`
- `DefectCandidate`
- bounded `InvestigationWorkSetRequest/Receipt`
- `EvidenceDeepeningReceipt`
- `EvidenceAssessment`
- `CrossSourceCorrelation`
- `ReproducibilityAssessment`
- `FalsePositiveAssessment`
- `DefectAssessment`
- `RCARecord`
- `InvestigationCheckpoint`
- semantic reuse

R3.6 confirmation already requires, for `CONFIRMED_DEFECT`:

- final classification = `PRODUCT_DEFECT`;
- at least one `SUFFICIENT` EvidenceAssessment;
- false-positive status = `NOT_FALSE_POSITIVE`;
- reproducibility = `REPRODUCED` **or** established causal-basis refs;
- no unresolved critical contradiction refs.

G5 must compose this foundation; it must not create a second defect-truth schema/database.

## 1.2 Existing R4.3 lifecycle is the post-confirmation authority

R4.3 opens a `ConfirmedDefectLifecycle` only from an exact same-Mission R3.6 confirmed `DefectAssessment` reference/digest and exact R4.1 QualityVersion/TestCampaign scope.

R4.3 owns fix-link / fix-detection lifecycle after confirmation. G5 must hand off to R4.3; G5 must not fork a second fix lifecycle.

## 1.3 Current product integration is intentionally HOLD

`product_entry.py` and `.opencode/tools/aitest.ts` currently fail closed for Defect Hunter mutations. This is correct pre-G5 behavior.

The existing `aitest-diagnosis` prompt expresses the desired principle — exclude stale test asset, data, auth, environment, deployment and tool failures before product-defect confirmation — but its canonical G5 tool/runtime path is not yet wired.

## 1.4 Legacy `aitest_runtime/defects.py` is not a G5 authority

The legacy module writes SQL observation/diagnosis/defect tables through the old storage layer and includes heuristic AUTO_CONFIRMED behavior. It must **not** become G5 Product Truth.

G5 implementation must not import or write through legacy `defects.py`, legacy defect tables, or `aitest.db`.

---

# 2. G5 Product Boundary

## 2.1 G5 owns

G5 owns product integration for:

1. exact G4 observation/anomaly intake;
2. autonomous defect-candidate formation;
3. evidence-gap analysis and bounded investigation planning;
4. cross-source correlation;
5. reproduction requests and causal verification;
6. false-positive exclusion;
7. defect-truth assessment;
8. RCA establishment/partial/unresolved truth;
9. duplicate/canonical-defect correlation;
10. confirmed-defect handoff into R4.3;
11. human-review escalation when automatic confirmation is unsafe or unsupported.

## 2.2 G5 does not own

G5 must not:

- execute arbitrary UI/API/DB/CAT actions directly; real execution remains G4;
- author Standard Test Cases; G3 remains case/strategy authority;
- create/rotate/manage OpenCode Sessions; G2.1 remains authority;
- create a second Mission/Task/Attempt truth;
- create a second Defect/Fix database;
- mutate bank SUT source;
- claim a defect solely from coverage change/static analysis;
- open G6 closed-loop fix/retest automation;
- silently promote investigation learnings into durable knowledge.

---

# 3. Core Investigation Loop

Each candidate follows this durable loop:

```text
OBSERVED
-> CANDIDATE_OPEN
-> INVESTIGATING
-> EVIDENCE_DEEPENING
-> REPRODUCIBILITY_CHECK
-> FALSE_POSITIVE_CHECK
-> TRUTH_ASSESSMENT

Possible terminal outcomes:
CONFIRMED_DEFECT
CLASSIFIED_NON_PRODUCT
REJECTED_FALSE_POSITIVE
INCONCLUSIVE
BLOCKED
```

R3.6 remains the durable entity truth; G2 Mission/Plan/Task remains the workflow truth. G5 may add only integration facts that are not duplicates of either authority.

A restart or Session rotation must recover from R1 + R3.6 `InvestigationCheckpoint`, never Conversation memory.

---

# 4. G4 -> G5 Admission Contract

A G5 investigation must start from exact durable refs, never free-form prose only.

Minimum admission:

```text
mission_id
G4 goal_id
execution_batch_ref
case_id + case_version
CaseValueLink / strategy refs
ExecutionAttempt ref
step_id / StepCursor ref
oracle_result
expected_ref
actual/evidence refs
source_identity
execution_node
quality_version_ref
campaign_ref
```

Eligible triggers include:

```text
FAIL
ERROR
INCONCLUSIVE
EVIDENCE_INSUFFICIENT
ORACLE_CONTRADICTION
PAGE_RUNTIME_CONFLICT
JOURNEY_ANOMALY
```

A failed step may create `TestAnomaly`; it must not directly create a confirmed product defect.

If required lineage/evidence is missing, G5 records an explicit gap and requests G4/G3 work; it does not invent the missing fact.

---

# 5. Autonomous Defect Hunter Role

Introduce/activate logical role:

```text
DEFECT_HUNTER
```

OpenCode product name may continue to use `aitest-diagnosis`, but runtime role identity must be explicit and Router-bound.

Required capability set:

```text
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

It is a Logical Agent, not a Session owner.

All DEFECT_HUNTER worker actions require exact G2.1 route + R2.5 Attempt/Session binding, the same as G3/G4 governed workers.

---

# 6. Evidence Deepening

## 6.1 Evidence channels

A candidate may request bounded evidence from:

- G4 Browser/UI execution evidence;
- API request/response evidence refs;
- DB safe query/result refs;
- CAT/log/trace refs;
- G3 Git Change Truth + CodeGraph structural refs;
- requirement/SST/design refs;
- Journey/Page/Business-state refs;
- QualityVersion/TestCampaign refs;
- build/deployment/environment refs;
- bank coverage refs only when relevant to changed-code context.

No source is automatically authoritative outside its domain.

## 6.2 Retrieval vs execution

R3.6 WorkSet retrieval can read bounded typed refs.

If a missing fact requires a new real action — e.g. rerun a case, query CAT, inspect DB, execute focused API/UI reproduction — G5 must create a governed request routed through G2/G3/G4. It must not bypass G4 Executor safety/provider contracts.

Mutating reproduction requires the same G4 safety/approval policy as normal execution.

## 6.3 Evidence sufficiency

Evidence assessment must explicitly record:

```text
SUFFICIENT | INSUFFICIENT | CONFLICTED
relevance
verification_method
freshness
scope_match
conflict_refs[]
ENGINEERING_EVIDENCE | FIELD_EVIDENCE
```

Unavailable evidence is `UNAVAILABLE/BLOCKED`, never silently treated as absence of defect.

---

# 7. Alternative Hypothesis / False-positive Matrix

Before product-defect confirmation, G5 must actively evaluate alternatives appropriate to the failure:

```text
PRODUCT_DEFECT_CANDIDATE
ENVIRONMENT_PROBLEM
TEST_DATA_PROBLEM
AUTOMATION_DEFECT
CASE_SPEC_DEFECT
KNOWLEDGE_FACT_ERROR
AUTH/SESSION_RUNTIME_PROBLEM (mapped to the correct non-product class/basis)
DEPLOYMENT/BUILD_MISMATCH (mapped to ENVIRONMENT_PROBLEM or explicit basis)
UNKNOWN_INCONCLUSIVE
```

The candidate must contain explicit supporting and contradicting evidence.

False-positive exclusion is an active step, not a confidence score.

`NOT_FALSE_POSITIVE` must be evidence-backed.

---

# 8. Reproducibility and Causal Proof

Preferred path:

```text
reproduce same governed case/scope
-> same or causally equivalent failure signature
-> correlated evidence
```

But deterministic reproduction is not mandatory when unsafe/impossible. Confirmation may instead use established causal basis, for example:

- exact changed-code logic contradicts required behavior and runtime trace proves execution of that path;
- API contract + response + server log establish violation;
- DB state transition + code path establishes persistence defect;
- deployment/build identity + runtime exception establishes binary/config defect;
- cross-system Journey state transition evidence establishes integration defect.

Causal-basis refs must be durable typed refs; prose alone is not causal proof.

---

# 9. Defect Truth Decision

G5 must use the frozen R3.6 `DefectAssessment` admission rule.

`CONFIRMED_DEFECT` requires all of:

```text
final_classification = PRODUCT_DEFECT
>=1 SUFFICIENT evidence assessment
false_positive = NOT_FALSE_POSITIVE
(reproducibility = REPRODUCED OR causal_basis_refs not empty)
unresolved_critical_contradictions = 0
```

Additional product policy:

- Security/performance/regulatory-sensitive defects require Human Review before final product confirmation unless an accepted future policy explicitly authorizes automation.
- S0/S1 or equivalent highest-severity defects require Human Review.
- Conflicted evidence cannot auto-confirm.
- Destructive reproduction cannot be required merely to raise confidence.
- LLM confidence is advisory only and is not an admission field.

Normal functional defects may be autonomously confirmed **only after** the deterministic R3.6 evidence gates above pass.

---

# 10. RCA

RCA uses the existing R3.6 cause classes:

```text
CODE_LOGIC
API_CONTRACT
DATA_PERSISTENCE
ENV_DEPLOYMENT
AUTH_PERMISSION
INTEGRATION_DEPENDENCY
JOURNEY_STATE
AUTOMATION
CASE_SPEC
KNOWLEDGE_FACT
UNKNOWN
```

RCA states remain:

```text
ESTABLISHED
PARTIAL
UNRESOLVED
NOT_APPLICABLE
```

Rules:

- `ESTABLISHED` requires a bounded causal chain of typed refs;
- root component must not be guessed from a single stack trace/string;
- contradictions remain visible;
- product-defect confirmation does not require RCA to be ESTABLISHED if defect truth is otherwise proven;
- RCA may continue deepening after confirmation, but immutable earlier assessment history remains preserved.

---

# 11. Duplicate / Canonical Defect Correlation

Do not deduplicate solely by error text or HTTP code.

Correlation should consider:

```text
same/related requirement or business rule
same changed-code/root component
same causal chain or defect mechanism
same journey transition/state defect
same API/data contract violation
same build/deployment identity
same reproducibility signature
cross-layer manifestations L1-L7
```

One root defect may have multiple manifestation/anomaly refs and detection layers.

Ambiguous correlation must remain separate candidates or require Human Review; G5 must not silently merge unrelated defects.

The canonical post-confirmation identity is the R4.3 `ConfirmedDefectLifecycle` created from exact R3.6 assessment + QualityVersion/Campaign scope.

---

# 12. R4.3 Handoff

After R3.6 `CONFIRMED_DEFECT`:

```text
R3.6 DefectAssessment
  + exact assessment digest/ref
  + R4.1 QualityVersion ref
  + TestCampaign refs
  + evidence / RCA / severity / priority refs when available
-> R4.3 OPEN_CONFIRMED_DEFECT_LIFECYCLE
```

R4.3 exact admission validation remains authoritative.

G5 must not mark a fix detected, close a defect, dispatch retest, or run fix validation. Those belong to the existing R4 foundations and future G6 orchestration.

---

# 13. Human Review

Use canonical R2.6 HumanGate.

Mandatory review triggers include:

- multiple plausible candidates with unresolved critical contradiction;
- ambiguous duplicate/correlation merge;
- highest-severity defect;
- security/performance/regulatory-sensitive defect;
- required evidence source unavailable where confirmation policy demands it;
- destructive/high-risk reproduction;
- explicit project policy.

Human decision must be durable and scoped. Conversation text is never defect truth by itself.

---

# 14. Product Surface

## 14.1 Canonical `g5` product entry

Add `g5_command(role, action, payload)` to `aitest_runtime.product_entry`.

Suggested actions:

### DIRECTOR

```text
status
intake_observations
investigation_status
open_investigation
request_human_review
canonical_defects
```

### DEFECT_HUNTER / DIAGNOSIS

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

Exact action list becomes CodeContract authority only after Contract Review.

## 14.2 OpenCode tool

`aitest_diagnosis`/`diagnosis` must stop returning HOLD and call canonical product entry only after G5 CodeContract is frozen.

No direct legacy SQL/storage call is permitted.

---

# 15. G5 Investigation Context

`work_context` must be reconstructed from durable truth and include bounded references to:

```text
Mission/Task/Attempt/Session binding
G4 observation + execution lineage
G3 requirement/change/case/strategy facts
R3.6 current candidate stages
R4.1 version/campaign
R4.3 lifecycle if already confirmed
available evidence channels/provider capability
open HumanGates
investigation checkpoint/cursor
```

Raw browser/CAT/API/DB payloads must not be injected wholesale into model context.

---

# 16. Security & Sensitive Evidence

Reuse typed redaction principles established in G4.

Never durably persist raw:

- password/OTP/captcha/face/secret answer;
- Authorization/Cookie/session secrets;
- unredacted sensitive DB/customer data solely for diagnosis convenience.

R1 stores authoritative typed references/digests/statuses. Evidence artifacts may live outside R1 under governed artifact policy.

---

# 17. Required Engineering Gates

G5 Engineering cannot close unless fresh evidence proves at minimum:

1. G4 FAIL does not directly create confirmed defect.
2. exact G4 lineage is required for intake.
3. DEFECT_HUNTER worker is G2.1/R2.5 bound.
4. restart/Session rotation recovers investigation from R1/R3.6 checkpoint.
5. evidence deepening uses bounded typed WorkSet.
6. missing real action routes through G4 rather than direct provider bypass.
7. false-positive alternatives are evaluated.
8. insufficient/conflicted evidence cannot confirm defect.
9. NOT_FALSE_POSITIVE is required.
10. reproduction or causal-basis ref is required.
11. unresolved contradiction blocks confirmation.
12. security/performance/highest-severity confirmation raises HumanGate.
13. duplicate correlation does not merge unrelated symptoms.
14. same root cause across multiple manifestations can correlate to one canonical lifecycle.
15. R4.3 handoff accepts only exact confirmed R3.6 assessment digest.
16. legacy `aitest_runtime.defects` is never imported by G5 product source.
17. legacy `aitest.db` remains unchanged/not created.
18. raw secrets are absent from R1 storage bytes.
19. G5 cannot execute G4 capability directly outside governed G4 path.
20. G5 cannot author/modify G3 Standard Cases directly.
21. G6 actions remain HOLD.
22. `runtime.verify_projection` PASS.
23. full G1-G4 regression remains PASS.
24. same-Mission E2E demonstrates observation -> investigation -> deepening -> reproduction/causal proof -> false-positive exclusion -> confirmed defect -> R4.3 lifecycle.

---

# 18. Adversarial Scenarios

Mandatory negative tests include:

- one API 500 with no corroboration -> not confirmed;
- stale deployment -> classify/non-product or inconclusive;
- wrong test data -> not product defect;
- stale/wrong case expected result -> CASE_SPEC_DEFECT, not product defect;
- automation selector failure -> AUTOMATION_DEFECT;
- auth expiry -> not product defect;
- CAT unavailable -> explicit source unavailable, not fabricated evidence;
- reproducibility blocked + no causal proof -> cannot confirm;
- same error text from two different components -> must not auto-dedup;
- two layers exposing same proven root cause -> may correlate to one lifecycle;
- contradictory DB vs API evidence -> CONFICTED/INCONCLUSIVE until resolved;
- LLM says “99% confidence defect” without evidence gates -> rejected;
- legacy `defects.py` AUTO_CONFIRMED path invoked -> construction gate failure.

---

# 19. Authorization Decision Candidate

Repository reality shows no hard dependency failure blocking G5 design/engineering decomposition:

- R1 durable truth is frozen;
- G2/G2.1 autonomous routing/session lifecycle is frozen;
- G3 Testing Intelligence is frozen;
- G4 real execution/evidence/HumanGate is frozen;
- R3.6 durable defect investigation foundation exists;
- R4.3 exact confirmed-defect lifecycle admission exists.

Field Validation remains mandatory later, but under existing governance ordinary FIELD_VALIDATION_PENDING does not block Engineering unless it proves a hard dependency failure.

Proposed 00.8 state after design review:

```text
G5_ARCHITECTURE_DEPENDENCY_GATE = PASS
G5_DETAILED_DESIGN = PASS / FROZEN
G5_ENGINEERING = AUTHORIZED_TO_START
G6 = HOLD
BANK_INTERNAL_PILOT_READY = NO
```

Engineering must start from canonical main `4edd78536633d4258705c6083fe55b44e51f54bb` on a dedicated G5 branch/PR. Main must not be modified directly.
