# RC6 Wave 12 Qualification — Admin / Allure / Report Truth Convergence

## Objective
Make R1 Event Stream the only durable business truth visible to Admin/API/reporting. Eliminate split truth where the DSH conversation says work is complete while the back-office page shows zero/missing assets.

## Runtime invariants qualified
- R1 live atomic events cover requirement analysis, code analysis, test intent, test condition, test case, execution attempt, assertion, evidence, defect, empirical coverage and report metadata
- projection/replay supports all of those entities without creating repair events
- Admin is a read-only view of `TruthRuntime`; it owns no business database/cache that can diverge
- Admin supports release / requirement / SST / layer / status filters plus pagination
- Admin navigation and core query shell are Chinese and list/query oriented rather than dashboard-only
- Allure result files are generated automatically from R1 execution/assertion/evidence truth
- Allure is derivative only; its manifest declares `R1_EVENT_STREAM_PROJECTION`
- configured local Allure CLI is invoked automatically; no user manual report generation is required
- mission HTML report and machine-readable manifest are generated from the same Admin/R1 read model
- reconciliation compares identity sets/counts across R1 projection -> Admin query -> report manifest; Allure execution identities/counts must exactly match R1 execution attempts
- evidence metadata containing password/secret/token/credential/authorization keys is rejected from R1
- replay remains deterministic and existing Wave 2 `inventory()` behavior remains backward-compatible

## Required RED reproductions
1. Admin pagination/filter query sees live R1 updates without restart/shadow sync
2. report identity/count mismatch -> reconciliation FAIL
3. missing Allure execution -> reconciliation FAIL
4. evidence contains token/password field -> reject
5. R1 replay reconstructs analysis/execution/evidence/defect/coverage/report entities
6. Allure renderer is invoked automatically with configured CLI
7. Chinese Admin shell contains version/requirement/SST/layer query controls and pagination

## Qualification command
`python -m unittest discover -s tests -v`

## Freeze rule
Wave 12 may be frozen only when code, full regression qualification and the Wave 12 GitHub Actions run are green on the same implementation commit. Wave 12 engineering freeze does **not** mean BANK_FIELD_PASS; final turnkey packaging plus a real same-Mission bank qualification remain required before final acceptance.
