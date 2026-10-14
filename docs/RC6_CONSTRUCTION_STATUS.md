# RC6 Construction Status

Repository truth only. Conversation claims do not advance a capability.

## Baseline
- repository: `TongAITech/opencode-test-digital-employee`
- active construction branch: `work/rc6-agent-runtime-bank-final-clean`
- Wave 0-12 architecture/frozen runtime baseline remains unchanged.
- R1 Event Stream remains the sole durable Runtime Truth.
- release label remains `ENGINEERING_CANDIDATE_NOT_BANK_FINAL`.

## Wave status

| Wave | Scope | Status | Evidence |
|---|---|---|---|
| 0 | RC6 architecture/problem baseline | DESIGN_FROZEN | field Reality Audit in project history |
| 1 | Runtime Kernel | ENGINEERING_PASS / FROZEN | code `0a9e3d0eebf3003a2046c857a9334657655c5a6a`; GitHub Actions run `38521696131` = success |
| 2 | Truth Layer | ENGINEERING_PASS / FROZEN | code `1cd297348edbdd2bd8e6c0885751ebaaa116ba6a`; GitHub Actions run `38522392764` = success |
| 3 | Bank Reality Registry | ENGINEERING_PASS / FROZEN | code `27d100405185b688802b97c0a5216961e8c71d85`; GitHub Actions run `38522685705` = success |
| 4 | Tool Capability Broker | ENGINEERING_PASS / FROZEN | code `c13cddb6e1bc013106050bb24a4735cac4049a65`; GitHub Actions run `38523006166` = success |
| 5 | Requirement/Code Intelligence | ENGINEERING_PASS / FROZEN | code `0d79b7e46240d28a94691d4ae7e26f74e85c44ae`; GitHub Actions run `38523268446` = success |
| 6 | L1-L7 Design Runtime | ENGINEERING_PASS / FROZEN | code `5daf515777a0a36fc08c1d640f8c40efbca69520`; GitHub Actions run `38523622831` = success |
| 7 | Coverage/Oracle Closure | ENGINEERING_PASS / FROZEN | code `318fe446c498c22d92ac241f01d067e4c8e3bd83`; GitHub Actions run `38523909146` = success |
| 8 | Precondition/Test Data | ENGINEERING_PASS / FROZEN | code `bdd54561f7f2c68feeba0970ede0506b6a7f4cb1`; GitHub Actions run `38524369514` = success |
| 9 | L1-L7 Execution | ENGINEERING_PASS / FROZEN | code `a8f9cf301b21448ce71a5c2c1067f25e22167651`; GitHub Actions run `38525779029` = success |
| 10 | CAT Diagnosis/Recovery | ENGINEERING_PASS / FROZEN | code `9c9fc97133353503c8acb52f02193d082b0d2104`; GitHub Actions run `38526336050` = success |
| 11 | Execution Coverage Closure | ENGINEERING_PASS / FROZEN | code `270e10346787009440a29f0fb7bd2906179a1f4d`; GitHub Actions run `38526923819` = success |
| 12 | Admin/Allure/Report | ENGINEERING_PASS / FROZEN | code `f3e5a85bc66aaee6f009811bc4920db9c43f7228`; GitHub Actions run `38527845151` = success |

No Wave above was reopened. Execution Closure is an additive cross-wave overlay that preserves the frozen Wave 0-12 contracts.

## RC6 Execution Closure Overlay

Status: `ENGINEERING_PASS / BANK_FIELD_NOT_PROVEN`

Engineering scope now closes:

`Frozen TestCase -> Executable Test Spec -> Automation Reuse Resolution -> AI Script Build -> Deterministic Script Validation -> Preparation/Test Data -> Real Runner -> Actual/Oracle/Evidence -> Failure Ownership -> CAT/Runner Log/CodeGraph RCA -> Recovery Action -> New Attempt -> Re-execution -> Execution Convergence`

Implemented runtime contracts and invariants:
- `ExecutableTestSpec` is compiled only from a FROZEN TestCase and binds Case + immutable Oracle fingerprints, release/requirement/SST/layer/target/precondition/data/action/oracle/evidence/cleanup/runner/automation metadata.
- `AUTOMATION_ENGINEER` owns executable-spec/automation-mapping/script construction, but cannot decide final execution PASS.
- `AutomationReuseResolver` searches existing test, fixture, API client, DB helper, Page Object, auth/4A, route, data builder, assertion and cleanup assets before new script generation.
- `SCRIPT_GENERATED != SCRIPT_READY`; deterministic `ScriptValidator` computes readiness.
- pytest validation includes Python compile, collect-only, fixture/dependency resolution and targeted execution.
- JUnit validation includes dependency resolution, test compile, test discovery and targeted execution without exact tool-version pinning.
- `PytestRunnerAdapter` and `JUnitRunnerAdapter` invoke real processes. Runner exit code alone is not execution truth; structured execution manifest must provide Actual + professional ToolCall/Evidence required by the existing Wave 9 Execution Integrity Gate.
- Failure ownership supports `SCRIPT`, `SPEC`, `ORACLE`, `DATA`, `PRECONDITION`, `AUTH`, `ROUTE`, `TOOL`, `ENVIRONMENT`, `DEPENDENCY`, `FLAKY`, `PRODUCT`, `TRANSIENT`, `UNKNOWN`.
- Assertion failure alone never implies PRODUCT. PRODUCT requires evidence-backed exclusion of Case/Oracle, ExecutableSpec, Script, Data, Auth, Route, Tool, Environment and Dependency ownership.
- `FailureSignature` provides stable clustering using exception/root-frame/HTTP/business-code/route/assertion identity.
- CAT keeps bounded application/time-window/request-id/trace-id/business-id correlation. RCA can bind runner/CAT evidence to CodeGraph symbol, call path, Git change and requirement/SST in an evidence-backed `RootCauseCandidate` with confidence.
- `RecoveryActionExecutor` executes recovery rather than returning a recommendation only. Nonterminal MCP recovery requires a trusted runtime-scoped `VerifiedRecoveryAdapter`; a Worker cannot self-report `{verified:true}` as proof.
- Each rerunnable recovery creates a fresh append-only Attempt. Independent execution/script/data/auth/route/tool/environment/dependency/flaky budgets and repeated FailureSignature protection prevent blind retry loops.
- PRODUCT is terminal and emits a stable defect-candidate reference; MCP terminal PRODUCT creates an R1 `DEFECT(CANDIDATE)` and never changes Script/Oracle to manufacture green.
- Coordinator is forbidden from professional Execution Closure artifacts; failure/convergence/RCA/recovery paths require FAILURE_DIAGNOSTIC authority and lease.

Canonical R1 overlay artifacts/events are registered into the same Wave 2/12 JSONL Event Stream and deterministic replay/projection:
- `executable_test_spec` / `EXECUTABLE_TEST_SPEC_UPSERTED`
- `automation_mapping` / `AUTOMATION_MAPPING_UPSERTED`
- `script_artifact` / `SCRIPT_ARTIFACT_UPSERTED`
- `script_validation` / `SCRIPT_VALIDATION_UPSERTED`
- `failure_diagnosis` / `FAILURE_DIAGNOSIS_UPSERTED`
- `root_cause_candidate` / `ROOT_CAUSE_CANDIDATE_UPSERTED`
- `recovery_decision` / `RECOVERY_DECISION_UPSERTED`
- `recovery_action` / `RECOVERY_ACTION_UPSERTED`
- `execution_convergence` / `EXECUTION_CONVERGENCE_UPSERTED`

The R1 qualification also verifies traceability across the existing canonical `test_case`, `execution_attempt`, `assertion`, `evidence`, and `defect` entities. Runtime immutable tuples are canonicalized to JSON lists only at the overlay serialization boundary; the frozen Wave 2 truth implementation is not replaced.

StageMachine after Case Freeze now contains the explicit closure path:

`CASE_FREEZE -> EXECUTABLE_SPEC -> SCRIPT_BUILD -> SCRIPT_VALIDATE -> SCRIPT_READY -> PREPARATION -> PRECONDITION_VERIFY -> TEST_DATA_PREPARE -> PREPARED_ATTEMPT_FREEZE -> L1_L7_EXECUTION -> EXECUTION_INTEGRITY -> FAILURE_DIAGNOSIS -> RECOVERY_DECISION -> RECOVERY_ACTION -> REEXECUTION/new preparation -> EMPIRICAL_COVERAGE`

`FAILURE_DIAGNOSIS` no longer unconditionally jumps to empirical coverage.

MCP Worker-callable Execution Closure surfaces:
- `executable_spec_build`
- `automation_reuse_resolve`
- `script_build`
- `script_validate`
- `runner_execute`
- `failure_diagnose`
- `recovery_decide`
- `recovery_execute`
- `execution_convergence`

Engineering qualification evidence:
- RC6 Execution Closure run `38552005013`: Ubuntu current Python = PASS; Ubuntu Python 3.8 = PASS; Windows Python 3.8 = PASS; real JUnit runner = PASS.
- The focused Execution Closure qualification at that run: `67 passed, 20 subtests passed`.
- Full RC6 regression at that run: `190 passed, 1 skipped, 20 subtests passed` on Ubuntu current Python; Windows/full and Ubuntu 3.8/full also PASS.
- Real JUnit line-of-fire at that run: Maven/Java capability probe PASS and `1 passed`; it exercises dependency resolution -> compile -> discovery -> targeted JUnit execution -> JUnitRunnerAdapter.
- Real L3 engineering vertical uses a real TCP HTTP SUT and real pytest subprocess, then requires runner-manifest Actual/ToolCall/Evidence and Wave 9 integrity before PASS.
- Recoverable route fault qualification performs FAIL -> ownership classification -> CAT/evidence-backed diagnosis -> RootCauseCandidate -> real route side effect -> fresh Attempt -> rerun -> PASS.
- Product-protection qualification proves HTTP/process execution can succeed while business Oracle fails; with complete test-side ownership evidence the result is PRODUCT -> terminal defect candidate, with no Script/Oracle mutation.
- Formal Release integrated qualification run `38552105667`: Linux Python 3.8 = PASS; Linux current Python = PASS; Windows Python 3.8 qualification + immutable package build + package verify + Git Bash package-only verify + Execution Closure package-content check + artifact upload = PASS.

Package policy remains capability based and explicitly pre-bank:
- `ENGINEERING_CANDIDATE_NOT_BANK_FINAL`
- `bank_field_pass=false`
- `autonomous_testing_pass=false`
- `full_chain_real=false`
- `agent_runtime_bank_final_gate=NOT_PROVEN_UNTIL_REAL_DSH_VERTICAL_SLICE_PASS`

## RC6 Agent Runtime BANK_FINAL gate

Status: `BLOCKING / NOT_PROVEN`

This gate is cross-wave and non-negotiable. Agent/Skill/Workflow/Prompt/State-Machine existence and engineering/Windows/package qualification do not count as real Agent Runtime or BANK field proof.

Required real vertical slice before `AGENT_RUNTIME_PASS` is legal:

`Coordinator -> pfc-requirement-analysis -> pfc-requirement-sufficiency -> Gap -> Repair Routing -> pfc-requirement-analysis -> pfc-requirement-sufficiency -> PASS`

Qualification fault injection requires Attempt #1 to preserve `missing_boundary_rule`; Attempt #1 must therefore fail sufficiency. A direct first PASS is qualification failure.

R1 must contain real ordered lifecycle events from actual DSH headless Worker sessions:
- `WORKER_ASSIGN_REQUESTED`
- `WORKER_ADMITTED`
- `WORKER_STARTED`
- `WORKER_TOOL_CALLED`
- `WORKER_OUTPUT_PRODUCED`
- `WORKER_COMPLETED`
- `HANDOFF_RETURNED`
- `SUFFICIENCY_STARTED`
- `SUFFICIENCY_GAP_FOUND`
- `REPAIR_REQUESTED`
- `WORKER_REASSIGNED`
- `SUFFICIENCY_REEVALUATED`
- `SUFFICIENCY_PASSED`

Every handoff must preserve Worker identity/session/mission/attempt/assignment/lease/parent/scope/input/tool/output/evidence/start/end/result references. Coordinator identity/session must never equal Worker identity/session. Missing Worker/DSH capability is `ROUTING_INTEGRITY_FAIL`; Coordinator fallback is forbidden.

The one-command package entrypoint remains `bash QUALIFY-AGENT-RUNTIME.sh`. It launches fresh DSH headless workers and validates proof from the canonical R1 stream. Unit/CI/synthetic engineering qualifications can never set the real gate to PASS.

Until that real vertical slice and real BANK same-Mission full-chain field qualification pass, these labels are forbidden:
- `AGENT_RUNTIME_PASS`
- `AUTONOMOUS_TESTING_PASS`
- `BANK_FINAL`
- `FULL_CHAIN_REAL`

## Remaining BANK field blockers
- Actual bank DSH Worker vertical with real provider/MCP composition and fresh independent Worker sessions.
- Fresh Bank Reality / exact TargetIdentity in the intended BLOAN environment.
- Real 4A/auth adapter binding and verification against bank authentication flow.
- Authoritative bank route binding, CAT and CodeGraph/Git evidence against real cfg-admin/cfg-data/cfg-scd/cfg-center revisions.
- Real TDSQL/OceanBase/TiDB data preparation where the selected Case requires it, including HumanGate for controlled writes.
- Real BLOAN-PF1.2.0 one-Mission full loop through requirement/code/design/preparation/execution/recovery/coverage/defect/report/allure/reconciliation.

## Release qualification status
`ENGINEERING_PASS / BANK_FIELD_NOT_PROVEN`

## Current RED
`RC6-AGENT-RUNTIME-BANK-FINAL-GATE`: Execution Closure engineering is qualified, but real DSH Worker Runtime and BANK field proof remain NOT_PROVEN. Final package therefore remains `ENGINEERING_CANDIDATE_NOT_BANK_FINAL`.
