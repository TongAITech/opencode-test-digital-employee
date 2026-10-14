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
| 8 | Precondition/Test Data | IMPLEMENTING | deterministic structured preparation and recovery under qualification |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 8 implementation under qualification
- only FROZEN Cases enter preparation
- structured preconditions: ENVIRONMENT / AUTH / BUSINESS_STATE / DATA / DEPENDENCY
- preconditions verified before data selection/build
- separate immutable initial-state and input-data bindings per execution attempt
- deterministic strategy order: reuse -> derive -> API -> UI -> DB -> fixture -> mock, constrained by Case policy
- every selected binding requires tool/evidence refs and post-selection verification
- DB_CREATE requires HumanGate approval evidence
- attempt binding is immutable by attempt id, Case version and TargetIdentity
- Oracle snapshot and cleanup policy fixed before execution
- deterministic failure recovery semantics
- valid real PRODUCT assertion failure => PRODUCT_DEFECT; no retry and no re-prepare-to-green

## Current RED
`W8-CI-PROOF`: commit preparation/data/recovery runtime plus adversarial tests, run GitHub Actions, and repair only the first failing invariant. Wave 9 remains blocked until Wave 8 is frozen.
