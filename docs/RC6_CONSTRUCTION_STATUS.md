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
| 5 | Requirement/Code Intelligence | IMPLEMENTING | evidence-backed deterministic analysis gates next |
| 6 | L1-L7 Design Runtime | NOT_STARTED | — |
| 7 | Coverage/Oracle Closure | NOT_STARTED | — |
| 8 | Precondition/Test Data | NOT_STARTED | — |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 4 frozen capabilities
- staged capability states: DISCOVERED / EXECUTABLE / REGISTERED / VISIBLE_TO_WORKER / PERMISSION_OK / PROBE_PASS / TARGET_READY / READY
- binary/path discovery alone never yields READY
- probe PASS requires real tool-call and evidence references
- visibility and permission scoped to exact worker
- readiness scoped to exact TargetIdentity
- admission fail-closed for any missing stage
- real tool-call evidence record allowed only after admission succeeds

## Wave 4 evidence
- commit: `c13cddb6e1bc013106050bb24a4735cac4049a65`
- workflow: `RC6 Wave 4 Tool Capability Broker`
- run id: `38523006166`
- conclusion: `success`

## Current RED
`W5-EVIDENCE-GATES`: implement canonical RequirementAnalysis and CodeAnalysis contracts plus deterministic sufficiency evaluators. Gates must recompute traceability/coverage from evidence and reject self-reported percentages, unsupported assertions, unexplained changed symbols, missing reverse requirement mapping, or missing required CodeGraph tool-call evidence.
