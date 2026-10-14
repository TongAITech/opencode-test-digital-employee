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
| 1 | Runtime Kernel | IMPLEMENTING | local qualification 9/9 PASS before commit; GitHub CI pending |
| 2 | Truth Layer | NOT_STARTED | — |
| 3 | Bank Reality Registry | NOT_STARTED | — |
| 4 | Tool Capability Broker | NOT_STARTED | — |
| 5 | Requirement/Code Intelligence | NOT_STARTED | — |
| 6 | L1-L7 Design Runtime | NOT_STARTED | — |
| 7 | Coverage/Oracle Closure | NOT_STARTED | — |
| 8 | Precondition/Test Data | NOT_STARTED | — |
| 9 | L1-L7 Execution | NOT_STARTED | — |
| 10 | CAT Diagnosis/Recovery | NOT_STARTED | — |
| 11 | Execution Coverage Closure | NOT_STARTED | — |
| 12 | Admin/Allure/Report | NOT_STARTED | — |

## Wave 1 current implementation
- durable Mission state independent of chat history
- bounded ResumeEnvelope
- runtime-issued immutable WorkerIdentity
- signed TaskLease
- Role/Artifact ACL
- Tool ACL
- same-role generation rotation
- pre-request ContextBudget guard
- global ProviderBudget with rolling-window backpressure
- 429/451 cooldown hooks
- fail-closed StageMachine

## Wave 1 qualification
Local qualification command:

```bash
python -m unittest discover -s tests -v
```

Observed before GitHub commit: `Ran 9 tests ... OK`.

Wave 1 remains `IMPLEMENTING` until the committed source is verified and GitHub qualification evidence is attached. It may then move to `ENGINEERING_PASS / FROZEN`.

## Next RED
`W1-CI-PROOF`: commit the Wave 1 source, verify branch HEAD moved off baseline, and inspect GitHub Actions result. If PASS, freeze Wave 1. Otherwise repair the first failing test only.
