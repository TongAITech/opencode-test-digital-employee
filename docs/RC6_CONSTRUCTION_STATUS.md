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
| 3 | Bank Reality Registry | IMPLEMENTING | canonical registry + TargetIdentity implementation under qualification |
| 4 | Tool Capability Broker | NOT_STARTED | — |
| 5 | Requirement/Code Intelligence | NOT_STARTED | — |
| 6 | L1-L7 Design Runtime | NOT_STARTED | — |
| 7 | Coverage/Oracle Closure | NOT_STARTED | — |
| 8 | Precondition/Test Data | NOT_STARTED | — |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 3 implementation under qualification
- typed bank fact registry: application/repository/environment/database/auth/CAT/account/route/tool
- fact states: READY / STALE / NEEDS_BINDING / INVALID
- one-time idempotent historical migration with source provenance
- bounded freshness reconciliation and explicit drift detail
- registry rejects inline passwords/tokens/secrets; accepts local credential references
- deterministic TargetIdentity bound to release + deployment + four repo revisions + frontend/gateway + three DB profiles + 4A + CAT + account
- remote deployment target does not depend on localhost process state
- fail-closed release/environment/route/database/auth consistency checks

## Current RED
`W3-CI-PROOF`: commit BankRealityRegistry and TargetIdentity with regression tests; inspect GitHub Actions and repair first failing invariant only. Wave 4 remains blocked until Wave 3 is frozen.
