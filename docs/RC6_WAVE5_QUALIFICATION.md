# RC6 Wave 5 Qualification Contract

Wave 5 closes field failures where Requirement/Code gates could be made green by reshaping payloads or self-reporting coverage values, and where CodeGraph was unavailable but Code Analysis still passed.

## Runtime invariants

### Requirement sufficiency
- Gate recomputes traceability from `source_assertions`, `atomic_statements`, and evidence-backed `trace_links`.
- Caller fields such as `traceability_coverage`, `critical_gap_count`, or `testability_pass` are ignored.
- Every source assertion must map to at least one atomic statement.
- Every atomic statement must be source-backed and testable.
- Invalid trace links fail closed with explicit IDs/metrics.
- Independent review is mandatory: reviewer worker must differ from analyzer worker.
- Reviewer open gaps block sufficiency.

### Code sufficiency
- Gate recomputes changed-symbol explanation coverage and reverse requirement mapping.
- Every changed symbol must have evidence-backed explanation.
- Every in-scope requirement must map back to at least one changed symbol.
- Source revisions must be present.
- Git real tool-call evidence is required.
- When `codegraph_required` is true, a real CodeGraph call and evidence bound to the exact TargetIdentity are required.
- Self-reported `coverage` or gap counts are ignored.
- Independent review is mandatory.

## Qualification scenarios

1. Complete requirement evidence passes even when self-reported metrics deliberately claim failure.
2. Missing trace link fails even when caller claims coverage=1.0.
3. Untestable atomic statement fails.
4. Analyzer reviewing its own work fails.
5. Complete CodeGraph+Git evidence with reverse mapping passes.
6. Missing CodeGraph tool evidence fails.
7. CodeGraph evidence for the wrong target fails.
8. Unexplained changed symbol fails.
9. Reverse requirement gap fails.
10. All Wave 1-4 regressions remain green.

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 5 can freeze only after committed source passes GitHub Actions and run/head evidence is written to `RC6_CONSTRUCTION_STATUS.md`.
