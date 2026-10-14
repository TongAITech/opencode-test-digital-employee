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
| 1 | Runtime Kernel | ENGINEERING_PASS / FROZEN | code `0a9e3d0eebf3003a2046c857a9334657655c5a6a`; local 9/9 PASS; GitHub Actions run `38521696131` = success |
| 2 | Truth Layer | IMPLEMENTING | canonical contracts, atomic R1 events, legacy batch replay, deterministic projection, read-after-write integrity under qualification |
| 3 | Bank Reality Registry | NOT_STARTED | — |
| 4 | Tool Capability Broker | NOT_STARTED | — |
| 5 | Requirement/Code Intelligence | NOT_STARTED | — |
| 6 | L1-L7 Design Runtime | NOT_STARTED | — |
| 7 | Coverage/Oracle Closure | NOT_STARTED | — |
| 8 | Precondition/Test Data | NOT_STARTED | — |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 1 frozen capabilities
- durable Mission state independent of chat history
- bounded ResumeEnvelope
- runtime-issued immutable WorkerIdentity
- signed TaskLease
- Role/Artifact ACL and Tool ACL
- same-role generation rotation
- pre-request ContextBudget guard
- global ProviderBudget with rolling-window backpressure
- 429/451 cooldown hooks
- fail-closed StageMachine

## Wave 2 implementation under qualification
- versioned canonical contracts for TestIntent, TestCondition, TestCase
- exactly-one-layer Case contract (`L1`..`L7`)
- append-only JSONL R1 event store
- one-entity atomic live events
- live batch payload rejection
- deterministic disposable projection
- RC5 legacy `{intents:[...]}`, `{conditions:[...]}`, `{cases:[...]}` replay expansion without repair writes
- latest entity projection plus Case version history
- same entity/version conflict detection
- top-level release/requirement/SST queries
- read-after-write entity/query integrity receipt

## Current RED
`W2-CI-PROOF`: commit Wave 2 source and qualification tests, run GitHub Actions, and repair the first failing invariant only. Wave 3 is blocked until Wave 2 is `ENGINEERING_PASS / FROZEN`.
