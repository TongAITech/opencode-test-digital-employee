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
| 7 | Coverage/Oracle Closure | IMPLEMENTING | subject-level semantic coverage, oracle adequacy and delta-design closure next |
| 8 | Precondition/Test Data | NOT_STARTED | — |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 6 frozen capabilities
- every TestCondition receives seven explicit L1..L7 applicability decisions
- applicable layers require evidence; non-applicable layers remain explicit
- one applicable layer creates one independent `Lx_DESIGN` worker identity and lease
- combined `L2-L4` design workers are absent from the runtime planner
- Case candidate layer/condition/worker/lease provenance is validated
- design worker may emit only CANDIDATE
- design context is bounded artifact refs; raw diff/source/chat context is rejected
- context overflow rotates within the same professional role/layer only

## Wave 6 evidence
- commit: `5daf515777a0a36fc08c1d640f8c40efbca69520`
- workflow: `RC6 Wave 6 L1-L7 Design Runtime`
- run id: `38523622831`
- conclusion: `success`

## Current RED
`W7-COVERAGE-ORACLE-CLOSURE`: replace dimension-presence counting with a canonical CoverageSubject registry. Every required subject must be mapped to concrete Case candidates; critical/high-risk and critical-oracle gaps must be zero before freeze. Oracle adequacy must be computed from layer/risk/action semantics, and uncovered subjects must produce delta-design work for the exact professional layer rather than a generic re-generation pass.
