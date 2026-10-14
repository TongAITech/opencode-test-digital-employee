# RC6 Construction Status

Repository truth only. Conversation claims do not advance a wave.

## Baseline
- repository: `TongAITech/opencode-test-digital-employee`
- branch: `work/rc6-runtime-reconstruction`
- base: `main@58e5e1259cd26846b31ea21a8a87df0bcf071edc`

## Wave status

| Wave | Scope | Status | Evidence |
|---|---|---|---|
| 0 | RC6 architecture/problem baseline | DESIGN_FROZEN | field Reality Audit in project conversation |
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

No Wave above is reopened by the Agent Runtime BANK_FINAL gate. Only the cross-wave runtime proof and the P0 wiring required to make that proof real may change.

## RC6 Agent Runtime BANK_FINAL gate

Status: `BLOCKING / NOT_PROVEN`

This gate is cross-wave and non-negotiable. Agent/Skill/Workflow/Prompt/State-Machine existence and Windows/package qualification do not count as Agent Runtime proof.

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

Every handoff must preserve `worker_instance_id`, `agent_id`, `mission_id`, `attempt_id`, `assignment_id`, `lease_id`, `parent_worker_id`, `scope`, `input_refs`, `tool_calls`, `output_refs`, `evidence_refs`, `started_at`, `finished_at`, `result`, plus the real fresh DSH session id used as independence proof. Coordinator identity/session must never equal a Worker identity/session. Missing Worker/DSH capability is `ROUTING_INTEGRITY_FAIL`; Coordinator fallback is forbidden.

The one-command package entrypoint is `bash QUALIFY-AGENT-RUNTIME.sh`. It launches fresh DSH headless workers and validates proof from the canonical R1 stream. Unit/CI simulations validate fail-closed mechanics only and can never set the real gate to PASS.

Until that real vertical slice passes, these labels are forbidden:
- `AGENT_RUNTIME_PASS`
- `AUTONOMOUS_TESTING_PASS`
- `BANK_FINAL`
- `FULL_CHAIN_REAL`

## Wave 12 frozen capabilities
- R1 Event Stream remains the sole durable business truth for requirement/code analysis, Test Intent, Test Condition, Test Case, execution attempt, assertion, evidence, defect, empirical coverage and report metadata. Agent runtime lifecycle proof is now also persisted in this same R1 stream; no qualification shadow log is allowed.
- Admin/API/reporting are read-only projections/derivatives of R1; no shadow admin business store is allowed.
- Admin query supports release, requirement, SST, layer and status filters plus pagination, with a Chinese list/query shell.
- Allure results are generated automatically from R1 execution/assertion/evidence truth and declare `R1_EVENT_STREAM_PROJECTION` as their source.
- configured local Allure CLI is invoked automatically; users do not manually generate reports.
- mission HTML report and machine-readable report manifest are generated from the same R1-backed Admin read model.
- reconciliation compares identity sets and counts across R1 projection -> Admin/API -> report manifest; Allure execution identities/counts must exactly match R1 execution attempts.
- evidence metadata containing password/secret/token/credential/authorization keys is rejected from R1.
- projection replay remains deterministic and no repair/re-record event is required to reconstruct presentation truth.

## Release qualification status
`IMPLEMENTING`

## Current RED
`RC6-AGENT-RUNTIME-BANK-FINAL-GATE`: keep Wave 0-12 frozen. First prove the real requirement vertical slice above with independent DSH workers, real handoffs, an actual first sufficiency gap, repair routing, independent re-evaluation and R1 proof. Packaging/Windows PASS remains only engineering evidence. After this slice passes, extend the same runtime proof pattern to Code -> Test Design -> Preconditions/Data -> L1-L7 -> Failure/Diagnosis/Recovery -> Defect -> Evidence/Report. Final package remains `ENGINEERING_CANDIDATE_NOT_BANK_FINAL` until both this gate and the real same-Mission bank full-chain field qualification pass.
