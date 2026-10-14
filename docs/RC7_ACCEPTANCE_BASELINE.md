# RC7 Acceptance Baseline

Status: FROZEN FOR CONSTRUCTION

## Engineering baseline

RC7 is an additive closed-loop refactor based on the proven RC6 branch:

- base branch: `work/rc6-agent-runtime-bank-final-clean-fieldfix5`
- base commit: `201156f16a70055fc0ea82af45357d7a0c5cbc06`
- RC7 construction branch: `work/rc7-closed-loop-runtime`

RC7 construction MUST preserve verified RC6 testing capabilities. Staged delivery is an implementation order only; it MUST NOT reduce the final acceptance scope.

## Frozen final capability scope

RC7 is complete only when all of the following closed loops are implemented and reality-qualified:

1. Requirement Analysis closed loop
2. Code Analysis closed loop
3. Test Design / Test Obligation sufficiency closed loop
4. Test Case -> Execution Contract -> Script Readiness closed loop
5. Test Execution / Evidence / Failure Diagnosis / Recovery closed loop
6. Defect Qualification / RCA / Fix Verification / Regression closed loop
7. Mission Test Sufficiency / Residual Risk / Final Report closed loop

Cross-node requirements are mandatory:

- canonical Mission / Task / Artifact / Evidence / Gap / Evaluation contracts
- R1 Event Stream remains sole durable runtime truth
- independent evaluation; worker output is never self-acceptance
- canonical Gap-driven repair and cross-node routing
- targeted reopen and dependency invalidation
- session-independent durable Mission state
- runtime-owned loop/retry/routing/convergence
- shared dependency/root-cause de-duplication
- `PLAN_COMPLETE != TEST_SUFFICIENT`
- `WORKFLOW_COMPLETE != MISSION_COMPLETE`
- final completion requires Mission sufficiency/convergence evidence

## Forbidden scope reductions

The following MUST NOT be used as substitutes for acceptance:

- mock-only closure instead of real runtime closure
- unit tests alone instead of required reality qualification
- worker/agent declaring its own output PASS
- artifact existence being treated as node completion
- case count being treated as test-design sufficiency
- pytest/JUnit process exit code being treated directly as product result
- BLOCKED being collapsed into product FAIL
- script repair silently changing business Oracle to make a test green
- previously accepted nodes being permanently non-reopenable
- report generation being treated as Mission completion
- max retry/iteration count being treated as a quality PASS condition
- skipping a critical gap because of time/cost

## RC6 reuse/refactor reality matrix

This matrix is based on code present at the frozen RC6 base commit, not on conversation claims.

| RC6 asset | RC7 treatment | Reality found |
|---|---|---|
| `rc6_runtime/truth.py` | REUSE + EXTEND | Append-only JSONL R1 truth, deterministic replay/projection, read-after-write verification |
| `rc6_runtime/contracts.py` | REUSE + EXTEND | Canonical business artifact validation already exists |
| `rc6_runtime/execution_overlay.py` | REUSE PATTERN | Proven R1 overlay extension mechanism |
| `rc6_runtime/mission.py` | WRAP / EVOLVE | Durable Mission state and strict session successor handoff already exist |
| `rc6_runtime/autonomous_loop.py` | REUSE / REFACTOR | Runtime-owned autonomous loop and no-durable-progress protection already exist |
| `rc6_runtime/orchestrator.py` | REFACTOR CONTROL MODEL | Deterministic stage/gate routing exists but uses stage/gate strings rather than canonical RC7 Task/Gap/Evaluation objects |
| `rc6_runtime/intelligence.py` | REUSE | Independent evidence-backed Requirement/Code sufficiency evaluators already exist |
| `rc6_runtime/agent_runtime.py` | WRAP / REUSE | Worker lifecycle proof, independent requirement gate and R1 lifecycle events already exist |
| execution / preparation / executable spec / automation | REUSE / WRAP | Existing executable-test capabilities remain assets, not rewrite targets |
| diagnosis / recovery / coverage | REUSE / WRAP | Existing diagnosis, recovery and empirical closure capability remains an RC7 input |
| presentation/reporting | REUSE VIEW / REFACTOR GATE | Presentation is a projection; report generation cannot define Mission completion |

## Current RC7 construction slices

### RC7.1 Closed-loop control core

Implemented on the RC7 branch:

- canonical Mission / Task / Artifact / Evidence / Gap / Evaluation / Event models
- deterministic Task/Gap/Mission state transitions
- worker output cannot jump directly to PASS
- Gap resolution requires reevaluation authority
- Mission convergence hard gates
- RC7 control records persisted through inherited R1 Event Stream overlay
- targeted Artifact dependency invalidation and Task reopening
- deterministic cross-node Gap routing policy

### RC7.2 Requirement closed-loop vertical slice

Implemented incrementally:

- RC6 independent Requirement Sufficiency Gate reused as semantic evaluator
- gate reasons normalized into canonical RC7 Gap objects
- missing boundary becomes CRITICAL Gap
- repair output does not close Gap
- Gap must reach EVIDENCE_PENDING and be closed by a new independent Evaluation
- repaired candidate can reach Task PASS only after reevaluation
- evaluation/gap versions are persisted in the same R1 Event Stream

A slice is not RC7 completion. RC7 completion remains governed by the full frozen scope above.
