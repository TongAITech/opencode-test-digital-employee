# RC6 Wave 8 Qualification Contract

Wave 8 closes the gap between a frozen Case and a real executable attempt. Preparation is a deterministic runtime phase, not free-form worker improvisation.

## Runtime invariants

- Only `FROZEN` Cases can enter preparation.
- Preconditions are structured and typed: ENVIRONMENT / AUTH / BUSINESS_STATE / DATA / DEPENDENCY.
- Preconditions are verified before any test data is bound.
- Initial business state and execution input data are separate bindings.
- Data strategy preference is deterministic: `REUSE_EXISTING -> DERIVE -> API_CREATE -> UI_CREATE -> DB_CREATE -> FIXTURE -> MOCK`, constrained by the Case requirement.
- Every successful data strategy returns a real tool-call ref and evidence ref.
- Every selected binding is verified after search/build; unverified data cannot be bound.
- DB construction requires a HumanGate approval reference before the write strategy can execute.
- One execution attempt has immutable bindings. Reusing the same attempt id is idempotent only for the same Case version/TargetIdentity.
- Oracle is snapshotted before execution and travels with the prepared attempt.
- Cleanup policy is explicit and preserved.
- Recovery distinguishes TRANSIENT / AUTH / DATA / PRECONDITION / TOOL / ROUTE / ENVIRONMENT / DESIGN / PRODUCT.
- A PRODUCT assertion failure after valid preparation and real action is terminal as product evidence: no retry and no re-prepare-to-green.

## Qualification scenarios

1. Candidate Case cannot prepare.
2. Initial state and input data remain distinct.
3. Reusable data is preferred over construction.
4. Failed search can fall through to API construction, then must verify.
5. DB_CREATE without HumanGate is blocked.
6. Approved DB_CREATE preserves HumanGate evidence.
7. Verification failure prevents attempt binding.
8. Attempt binding is immutable/idempotent for same Case version and target.
9. Preconditions complete before data strategy execution.
10. Valid product failure cannot be re-prepared or retried away.
11. DATA failure permits re-prepare; TRANSIENT failure permits same-step retry without re-prepare.
12. All Wave 1-7 regressions remain green.

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 8 can freeze only after committed source passes GitHub Actions and run/head evidence is recorded in `RC6_CONSTRUCTION_STATUS.md`.
