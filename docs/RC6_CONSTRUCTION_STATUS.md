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
| 10 | CAT Diagnosis/Recovery | IMPLEMENTING | failure diagnosis, bounded CAT correlation and recovery semantics next |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 9 frozen capabilities
- seven independent `L1_EXECUTE` ... `L7_EXECUTE` profiles
- exact PREPARED attempt + FROZEN Case version + TargetIdentity required
- worker role/layer/phase and lease scope are runtime-enforced
- layer-specific tool admission is required for the exact worker and target
- every required execution tool must produce a real tool-call ref and evidence ref
- actual result + independent deterministic oracle assertion + current evidence required for PASS
- `BLOCKED`, `SKIPPED`, `NOT_RUN` cannot become PASS
- mixed-layer Cases are rejected
- execution receives copies; canonical frozen Case and prepared bindings cannot be mutated by an execution worker
- failed oracle stays FAIL with valid execution integrity

## Current RED
`W10-CAT-DIAGNOSIS-RECOVERY`: failed attempts must preserve immutable attempt history, collect bounded multi-source evidence, correlate CAT when applicable using app/time/request/trace/business identifiers, classify the failure, and choose only an allowed recovery path. Retry is allowed only for transient failures and must be bounded. DATA/PRECONDITION/AUTH/TOOL/ROUTE/DESIGN failures use distinct recovery semantics. A valid PRODUCT assertion failure after verified preparation and real action is terminal and cannot be retried or re-prepared to green.
