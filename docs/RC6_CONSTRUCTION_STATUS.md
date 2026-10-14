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
| 8 | Precondition/Test Data | IMPLEMENTING | deterministic prepare/search/build/verify/bind and recovery semantics next |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 7 frozen capabilities
- canonical CoverageSubject registry with exact kind/layer/risk/evidence
- design sufficiency is computed over required subjects, not Case count or dimension presence
- same-layer evidence-backed Case coverage links only
- explicit CRITICAL/HIGH semantic gaps
- Runtime-derived oracle requirements from layer + risk + action semantics
- state-changing -> PERSISTENCE; negative -> NEGATIVE_SIDE_EFFECT; authorization-sensitive -> AUTHORIZATION
- HIGH/CRITICAL -> EVIDENCE_CORRELATION
- delta design routed to exact professional layer and uncovered subject refs
- Case freeze blocked until semantic coverage and oracle closure PASS

## Wave 7 evidence
- commit: `318fe446c498c22d92ac241f01d067e4c8e3bd83`
- workflow: `RC6 Wave 7 Coverage Oracle Closure`
- run id: `38523909146`
- conclusion: `success`

## Current RED
`W8-PRECONDITION-DATA-RUNTIME`: implement deterministic Case preparation: parse frozen preconditions/data requirements, qualify target/auth/dependencies, search reusable data before construction, construct only through governed strategies, verify after construction, bind immutable data per execution attempt, preserve initial-state vs input-data separation, and carry cleanup policy. Recovery must distinguish transient/auth/data/precondition/tool/route/environment/design/product failures; a valid real product assertion failure must never be re-prepared away.
