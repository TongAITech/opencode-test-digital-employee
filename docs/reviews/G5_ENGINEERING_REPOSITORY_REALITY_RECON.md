# G5 Engineering Repository Reality Recon

**WorkItem:** `10.G5｜Defect Truth & Autonomous Defect Hunter`  
**Status:** `REPOSITORY_REALITY_RECON = PASS`  
**Review type:** Git-native / exact-branch engineering recon  
**Canonical repository:** `TongAITech/opencode-test-digital-employee`  
**Canonical frozen main:** `4edd78536633d4258705c6083fe55b44e51f54bb`  
**Active engineering branch:** `work/g5-defect-truth`  
**Recon starting commit:** `7febc529e8f13fd806ce3f567c3b5dc79442fe10`  
**Draft PR:** `#2` / Draft / UNMERGED  
**ArchitectureBaseline:** `v7 / FROZEN / UNCHANGED`

> This document is engineering review evidence only. It does not replace the two frozen G5 Design Authority documents and it does not freeze the G5 CodeContract.

## 1. Branch / authority identity

Verified at recon start:

- `main` points exactly to `4edd78536633d4258705c6083fe55b44e51f54bb`.
- `work/g5-defect-truth` points exactly to `7febc529e8f13fd806ce3f567c3b5dc79442fe10`.
- PR #2 targets `main`, is Draft, is OPEN, and is not merged.
- The branch contains the frozen G5 detailed design and 00.8 engineering authorization only; no G5 runtime construction existed at recon start.

Result: `ENGINEERING_SOURCE_IDENTITY = PASS`.

## 2. Frozen R3.6 investigation/RCA foundation is real

Exact module: `workspace-template/ai-test/runtime/aitest_runtime/r3_6/`.

Existing durable surface includes:

- `TestAnomaly`
- `DefectCandidate`
- `InvestigationWorkSetRequest/Receipt`
- `EvidenceDeepeningReceipt`
- `EvidenceAssessment`
- `CrossSourceCorrelation`
- `ReproducibilityAssessment`
- `FalsePositiveAssessment`
- `DefectAssessment`
- `RCARecord`
- `InvestigationCheckpoint`
- `SemanticReuse`

`R36ApplicationService` already exposes the canonical commands for anomaly, candidate, evidence deepening, evidence assessment, correlation, reproducibility, false-positive assessment, defect assessment, RCA, checkpoint and semantic reuse on the shared `RuntimeService`.

The frozen handler already fail-closes `CONFIRMED_DEFECT` unless all of the following hold:

1. final classification is `PRODUCT_DEFECT`;
2. at least one referenced EvidenceAssessment is `SUFFICIENT`;
3. false-positive status is `NOT_FALSE_POSITIVE`;
4. reproducibility is `REPRODUCED` or causal-basis refs are present;
5. unresolved contradiction refs are empty.

R3.6 entities reject raw/secret-bearing fields and require typed upstream refs with exact digest/fingerprint.

### Important lineage reality

R3.6 is a historical frozen foundation and its local constant remains `ARCHITECTURE_BASELINE_REF = "v5"`.

G5 must **not** edit frozen R3.6 merely to relabel history. Because `R36ApplicationService` accepts caller-supplied `origin_lineage`, G5 integration must explicitly provide `architecture_baseline_ref = "v7"` for every new G5-originated R3.6 command while preserving the frozen R3.6 implementation unchanged.

Result: `R3_6_REUSE_SEAM = REAL / REUSE_REQUIRED`.

## 3. Frozen R4.3 ConfirmedDefectLifecycle is real

Exact module: `workspace-template/ai-test/runtime/aitest_runtime/r4_3/`.

`r3_6_adapter.py` validates an exact same-Mission R3.6 `DefectAssessment` reference and digest and independently replays the underlying candidate/evidence/reproducibility/false-positive facts. Only `CONFIRMED_DEFECT` is admissible.

`R43ApplicationService.open_confirmed_defect_lifecycle(...)` is the exact post-confirmation handoff. It:

- uses the existing shared RuntimeService;
- writes with `session_id = None`;
- validates the R3.6 assessment before execution;
- opens the canonical lifecycle from the exact assessment + QualityVersion + Campaign refs;
- owns all later fix-link / fix-detection lifecycle semantics.

G5 therefore must not create a new defect/fix store or a parallel post-confirmation lifecycle.

Result: `R4_3_HANDOFF_SEAM = REAL / EXACT`.

## 4. G4 observation/evidence boundary is real and already fail-closed

Exact module: `workspace-template/ai-test/runtime/aitest_runtime/g4/`.

Current G4 behavior records a governed `EXECUTION_STEP_RESULT`; for `FAIL`, `INCONCLUSIVE` or `ERROR` it additionally emits `UNEXPECTED_OBSERVATION` with:

- `step_result_ref`
- `oracle_result`
- `status = OBSERVATION_ONLY`
- `g5_defect_truth = HOLD`

G4 rejects direct confirmed-defect mutation. This is the canonical G4 -> G5 admission boundary.

G4 also already implements typed sensitive-evidence redaction: credential-bearing ingress is not persisted as raw evidence; durable evidence uses safe refs/digests/statuses. G5 must consume these bounded facts rather than re-ingesting raw CAT/DB/API/UI bodies.

Result: `G4_OBSERVATION_ADMISSION_SOURCE = REAL` and `TEST_FAIL != CONFIRMED_DEFECT` remains mechanically enforced.

## 5. G2.1 Router + R2.5 exact LogicalAgent binding are real

Current `AgentRoleRegistry.default()` includes `DIAGNOSIS -> aitest-diagnosis`, but does not yet expose the frozen product role `DEFECT_HUNTER`.

G2.1 already owns Session creation/rotation/reconciliation. `G21AutonomousOrchestrationService.report_task_outcome(...)` demonstrates the required binding pattern:

- resolve the durable route;
- require exact Task/Attempt/Session;
- derive/validate the Router logical-agent identity;
- replay R2.5 `LogicalAgentBinding` for the same root Attempt;
- reject logical-agent or physical-agent drift;
- never let the Agent own Session lifecycle.

R2.5 `LogicalAgentBinding` already carries exact:

`mission_id + logical_agent_id + root_attempt_id + attempt_id + task_id + session_id`.

### G5 binding conclusion

G5 must be stricter than merely checking a role name. Every DEFECT_HUNTER worker action must fail closed unless the supplied Mission/Task/Attempt/Session matches both:

1. G2.1 durable route (`DEFECT_HUNTER`, physical agent `aitest-diagnosis`), and
2. an exact R2.5 LogicalAgentBinding for the active Attempt/Session lineage.

`DIAGNOSIS` may remain an OpenCode/product-surface alias only; it must normalize to the single canonical Router role `DEFECT_HUNTER`, not create a second logical role identity.

Result: `DEFECT_HUNTER_ROUTER_BINDING_SEAM = REAL / ROLE_REGISTRY_CHANGE_REQUIRED`.

## 6. Canonical R2.6 HumanGate is real

Exact module: `workspace-template/ai-test/runtime/aitest_runtime/r2_6/`.

`HumanGateApplicationService.open_gate(...)` durably binds a gate to Mission/Task/root Attempt/origin Attempt/origin Session and persists the decision workflow in the shared Event Stream. `evaluate_human_gate_boundary(...)` is already fail-closed for pending/blocked/revision-required states.

G5 does not need or permit a second human-review database/task mechanism.

Result: `G5_HUMAN_REVIEW_SEAM = R2_6_CANONICAL`.

## 7. Current product/OpenCode integration is intentionally HOLD

`workspace-template/ai-test/runtime/aitest_runtime/product_entry.py` currently has canonical `g3_command` and `g4_command` seams with governed worker binding, but no `g5_command`.

`workspace-template/.opencode/agents/aitest-diagnosis.md` already instructs the diagnosis agent to treat failures as observations and actively exclude stale case/data/auth/environment/deployment/tool causes before a product defect conclusion.

`workspace-template/.opencode/tools/aitest.ts` exposes `diagnosis`, but it currently returns `HOLD / G5_DEFECT_HUNTER` for all actions.

Result: `G5_PRODUCT_INTEGRATION = MISSING_BY_DESIGN / CONSTRUCTION_REQUIRED_AFTER_CONTRACT_FREEZE`.

## 8. Legacy defect path is concretely unsafe and forbidden

`workspace-template/ai-test/runtime/aitest_runtime/defects.py` is confirmed legacy code. It:

- writes old SQL `observations`, `diagnoses`, `defects`, `defect_observations` tables;
- can infer `PRODUCT_DEFECT` from deterministic signal/exception heuristics;
- contains `AUTO_CONFIRMED` behavior;
- can directly invoke CAT and persist returned payloads through the old storage path;
- owns fix/retest operations that conflict with frozen R4.3/G6 boundaries.

Therefore the G5 implementation and tests must prove that the canonical G5 product path never imports, calls, writes through or depends on this module, legacy defect SQL tables, or `aitest.db`.

Result: `LEGACY_DEFECT_TRUTH = FORBIDDEN / NEGATIVE_GATE_REQUIRED`.

## 9. Test topology reality

The project does not use a conventional `runtime/tests` directory. Current executable product/closure tests live under:

`workspace-template/.pfc-internal-field-validation/tests/`

`tools/run_wave2_validation.py` is the current aggregate runner for the frozen G1-G4 regression suites and records `g5_defect_truth = HOLD` / `g6_closed_loop = HOLD` today.

G5 tests therefore must be added beside the existing product-path suites and must be added to a G5-capable aggregate validation runner or an explicitly extended canonical runner; CodeContract/ExecutionContract may not invent a different test root.

Result: `TEST_TOPOLOGY = REAL / EXACT_PATH_IDENTIFIED`.

## 10. No second durable G5 truth is required

Repository reality does not reveal any missing durable domain that requires a new G5 Event extension or SQL database.

The correct construction shape is an **integration/application layer** that composes:

`G4 observation/evidence -> R3.6 investigation truth -> R2.6 HumanGate when required -> R4.3 lifecycle`.

Any new `aitest_runtime/g5` package must therefore contain only product-integration contracts/policies/facades. It must not register a second durable extension for anomaly/candidate/assessment/RCA/defect/fix truth.

## 11. Recon result and required CodeContract deltas

```text
G5_ENGINEERING_REPOSITORY_REALITY_RECON = PASS
ARCHITECTURE_DRIFT = NO
FROZEN_FOUNDATION_REOPEN_REQUIRED = NO
NEW_DEFECT_DATABASE_REQUIRED = NO
NEW_FIX_TRUTH_REQUIRED = NO
G5_CODE_CONTRACT_CANDIDATE = AUTHORIZED_TO_FORM
READY_FOR_CODEX = NO
```

The CodeContract candidate must explicitly freeze:

1. integration-only `aitest_runtime/g5` shape with no second durable truth;
2. canonical `g5_command` actions and worker-role normalization;
3. `DEFECT_HUNTER -> aitest-diagnosis` Router role/capabilities;
4. exact G2.1 + R2.5 Task/Attempt/Session/LogicalAgent admission;
5. exact G4 `UNEXPECTED_OBSERVATION` + linked step-result admission;
6. v7 G5 origin lineage into unchanged frozen R3.6;
7. bounded WorkSet vs governed new-action distinction;
8. canonical R2.6 human-confirmation policy;
9. duplicate/canonical-lifecycle correlation without error-string merging;
10. exact R4.3 confirmed-assessment handoff;
11. checkpoint/restart/rotation recovery from R1/R3.6;
12. legacy-path, sensitive-evidence, direct-provider, G3-write and G6 negative gates;
13. fresh adversarial suites and same-Mission E2E under the real test topology.
