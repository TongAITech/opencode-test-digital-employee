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
| 4 | Tool Capability Broker | IMPLEMENTING | staged capability admission and worker/target proof next |
| 5 | Requirement/Code Intelligence | NOT_STARTED | — |
| 6 | L1-L7 Design Runtime | NOT_STARTED | — |
| 7 | Coverage/Oracle Closure | NOT_STARTED | — |
| 8 | Precondition/Test Data | NOT_STARTED | — |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 3 frozen capabilities
- typed bank fact registry with READY / STALE / NEEDS_BINDING / INVALID states
- one-time idempotent historical migration with provenance
- bounded freshness reconciliation and explicit drift
- deterministic TargetIdentity
- target binds release + deployment mode + four repo revisions + frontend/gateway + three DB profiles + 4A + CAT + account
- remote FAT target does not infer localhost service readiness
- fail-closed release/environment/route/database/auth consistency
- inline secrets forbidden from registry; local credential references supported

## Wave 3 evidence
- commit: `27d100405185b688802b97c0a5216961e8c71d85`
- workflow: `RC6 Wave 3 Bank Reality`
- run id: `38522685705`
- conclusion: `success`

## Current RED
`W4-CAPABILITY-ADMISSION`: replace binary-found=READY with staged capability proof. A tool is usable only when discovered, executable, registered, visible to the assigned worker, permitted, probe-passed with real evidence, and ready for the exact TargetIdentity.
