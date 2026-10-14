# RC6 Wave 7 Qualification Contract

Wave 7 closes the field failure where Test Design was declared sufficient because broad dimensions were present at least once, even though individual requirements, risks, code impacts and oracles were not proven covered.

## Runtime invariants

- Design coverage is computed over explicit `CoverageSubject` entities, not Case count.
- Every required subject has kind, exact L1-L7 owner layer, risk, and source evidence.
- A Case covers a subject only through an evidence-backed `coverage_link` and only when Case layer equals subject layer.
- All required subjects must be covered before design closure can PASS.
- CRITICAL/HIGH uncovered subjects are reported explicitly and can never be hidden by aggregate percentages.
- Oracle requirements are derived by Runtime from layer + risk + action semantics.
- State-changing actions require a persistence oracle.
- Negative actions require a negative-side-effect oracle.
- Authorization-sensitive actions require an authorization oracle.
- HIGH/CRITICAL Cases require evidence-correlation oracle.
- Delta design is routed to the exact uncovered professional layer and exact subject refs.
- Case candidates cannot transition to FROZEN until semantic coverage and oracle closure PASS.

## Qualification scenarios

1. Twenty L1 Cases do not compensate for uncovered L2/L3/L4 subjects.
2. Complete subject coverage and oracle coverage PASS.
3. Cross-layer coverage link is invalid and does not count.
4. HIGH-risk Case missing evidence-correlation oracle fails.
5. State-changing Case missing persistence oracle fails.
6. Negative Case missing negative-side-effect oracle fails.
7. Coverage gaps create layer-specific delta design requests.
8. Case freeze is blocked before closure.
9. Closure PASS allows candidate freeze.
10. L5 high-risk state-changing oracle policy is derived deterministically.
11. All Wave 1-6 regressions remain green.

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 7 can freeze only after committed source passes GitHub Actions and evidence is recorded in `RC6_CONSTRUCTION_STATUS.md`.
