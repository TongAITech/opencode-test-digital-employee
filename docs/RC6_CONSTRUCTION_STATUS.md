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
| 3 | Bank Reality Registry | IMPLEMENTING | canonical bank facts, freshness reconciliation, target identity next |
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

## Wave 2 frozen capabilities
- versioned canonical TestIntent/TestCondition/TestCase contracts
- exactly-one-layer Case contract (`L1`..`L7`)
- append-only JSONL R1 event store
- one-entity atomic live events; batch live writes rejected
- RC5 legacy batch replay expansion without repair events
- deterministic/idempotent projection rebuild
- latest Case projection plus version history
- same entity/version conflict detection
- top-level release/requirement/SST query integrity
- read-after-write persistence receipt
- field-failure reproduction `17 Intent / 17 Condition / 23 Case` recovers as `17/17/23`

## Wave 2 evidence
- commit: `1cd297348edbdd2bd8e6c0885751ebaaa116ba6a`
- workflow: `RC6 Wave 2 Truth Layer`
- run id: `38522392764`
- conclusion: `success`

## Current RED
`W3-CANONICAL-BANK-REALITY`: implement one-time historical fact migration, typed bank registries, freshness/reconciliation states, and a fail-closed TargetIdentity. Execution must remain blocked unless repo revisions, deployment environment, routes, databases and authentication bindings are coherent.
