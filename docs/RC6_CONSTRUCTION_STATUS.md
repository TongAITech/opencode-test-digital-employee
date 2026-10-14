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
| 7 | Coverage/Oracle Closure | IMPLEMENTING | subject-level semantic coverage, oracle derivation, delta design, and freeze gate under qualification |
| 8 | Precondition/Test Data | NOT_STARTED | — |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 7 implementation under qualification
- canonical CoverageSubject registry with explicit kind/layer/risk/source evidence
- required subjects are evaluated individually; Case count and dimension presence do not substitute for coverage
- Case-to-subject coverage links must be evidence-backed and same-layer
- uncovered CRITICAL/HIGH subjects reported explicitly
- OraclePolicy derives required oracle types from L1-L7 layer, risk and action semantics
- state-changing -> PERSISTENCE oracle; negative -> NEGATIVE_SIDE_EFFECT; authorization-sensitive -> AUTHORIZATION
- HIGH/CRITICAL -> EVIDENCE_CORRELATION oracle
- DeltaDesignPlanner emits exact subject refs grouped by professional layer
- CaseFreezeGate blocks FROZEN transition until semantic coverage and oracle closure PASS

## Current RED
`W7-CI-PROOF`: commit semantic coverage/oracle closure plus adversarial tests, run GitHub Actions, and repair only the first failing invariant. Wave 8 remains blocked until Wave 7 is frozen.
