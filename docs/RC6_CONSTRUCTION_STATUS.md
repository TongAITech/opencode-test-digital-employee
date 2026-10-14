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
| 10 | CAT Diagnosis/Recovery | ENGINEERING_PASS / FROZEN | code `9c9fc97133353503c8acb52f02193d082b0d2104`; GitHub Actions run `38526336050` = success |
| 11 | Execution Coverage Closure | IMPLEMENTING | empirical L1-L7 coverage evidence -> gaps -> delta execution/design loop next |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 10 frozen capabilities
- append-only immutable attempt history; retries/repreparation create successor attempts
- dedicated `FAILURE_DIAGNOSTIC` runtime role and scoped lease
- L3/L5 CAT mandatory; L1 CAT mandatory only for remote integration
- CAT bounded by applications + time window + request/trace/business correlation identifiers
- CAT must be READY for exact diagnostic worker + TargetIdentity and produce real tool/evidence refs
- retry only for TRANSIENT and bounded by retry budget
- DATA/PRECONDITION/AUTH/TOOL/ROUTE/ENVIRONMENT/DESIGN use distinct recovery paths
- verified preparation + real action + failed assertion must remain PRODUCT and terminal
- PRODUCT cannot retry/reprepare to green; UNKNOWN fails closed

## Current RED
`W11-EMPIRICAL-COVERAGE-CLOSURE`: after real execution, each applicable L1-L7 layer must calculate coverage from real layer-specific evidence, not Case counts or model claims. Uncovered required subjects must become explicit empirical coverage gaps. Critical/high-risk gaps must trigger delta design/execution and re-evaluation until closure. L1 uses changed code line/branch/method evidence (and mutation when available); L2 DB/transaction/state; L3 route/schema/auth/error/business; L4 page/control/state/network; L5 journey/state/cross-system; L6 workload envelope/SLO; L7 attack surface/security controls. No execution coverage evidence means no execution sufficiency PASS.
