# RC6 Wave 6 Qualification Contract

Wave 6 closes the field failure where `L2-L4` combined workers and mixed-layer Cases bypassed the planned seven professional design roles.

## Runtime invariants

- Every TestCondition receives exactly seven explicit applicability decisions: L1..L7.
- Applicable layers require evidence; non-applicable layers still have an explicit reason.
- One applicable layer creates one independent worker identity and one lease.
- Worker role is exactly `Lx_DESIGN`; Case artifact type is exactly `case_candidate_lx`.
- No combined worker such as `L2-L4` exists.
- A Case has exactly one layer and must match its task layer and condition.
- Candidate provenance must match runtime worker_id + lease_id.
- Design workers can emit only `CANDIDATE`; they cannot self-freeze Cases.
- Worker inputs are bounded artifact references. Raw diff/source/chat history is forbidden.
- Context overflow recovery rotates to the same role/layer and a new generation only.

## Qualification scenarios

1. Router returns seven explicit decisions.
2. L1/L2/L3/L4 applicability produces four separate worker identities/tasks.
3. Applicable layer without evidence is rejected.
4. Design context contains artifact refs only.
5. Raw diff/chat context is rejected.
6. Each task has the correct `case_candidate_lx` lease.
7. Wrong-layer candidate is rejected.
8. Wrong-worker provenance is rejected.
9. Valid layer candidate is accepted only as CANDIDATE.
10. Context overflow rotates same role/layer only.
11. All Wave 1-5 regressions remain green.

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 6 can freeze only after committed source passes GitHub Actions and evidence is recorded in `RC6_CONSTRUCTION_STATUS.md`.
