# D1 Source Unit Ledger — Raw Source Closure Review

## Exact authority

- ArchitectureBaseline: v7 / FROZEN / UNCHANGED
- Branch: work/v1.13.0-recovery-turnkey-validation
- C3 closure: ecb0589d4dc8b91350d57747e36d96eed38d2f92
- D1 validated head: a829b26552d69799e0e50210798e2141cf89f63f
- Windows workflow run: 34846405247
- Windows job: 103983307210
- Result: 17/17 PASS
- Artifact: 10348019362 / v4-d1-source-unit-qualification
- Artifact ZIP SHA256: e243924442b64cf8577723999681b174d95c6f2fe1f213c5fc49097d2aadfda7

## Decision

```ini
D1_SOURCE_UNIT_LEDGER = PASS / FROZEN
D1_WINDOWS_SOURCE_GATE = PASS
F12_FOUNDATION = IMPLEMENTED / PARTIAL
F47_SOURCE_UNIT_LEDGER_FOUNDATION = IMPLEMENTED / PARTIAL
ARCHITECTURE_CHANGE_REQUIRED = NO
R1_EVENT_STREAM_REMAINS_SOLE_DURABLE_TRUTH = YES
D2 = AUTHORIZED_TO_START
```

D1 is a narrow Phase-D closure. It does not close all of F12/F47 or any later Phase-D, packaging, real-model, or bank-field gate.

## Frozen D1 invariants

New SOURCE_DOCUMENT facts persist a deterministic bounded source-unit ledger. Each unit has stable identity, ordinal, structure kind, exact stored-text offsets, character count, and exact text digest. The ledger rejects overlap, semantic gaps, invalid bounds, and digest mismatch. One unit is limited to 8192 characters and one document to 4096 units.

Markdown uses heading sections. DOCX uses extracted paragraphs. Other text forms preserve paragraph boundaries, with bounded chunking for oversized units. Historical source facts are not rewritten; their immutable stored text can produce a deterministic compatibility view.

BR/SR/TR artifacts now carry exact source-unit references. Multi-unit sources require explicit unit provenance. A one-unit source can be auto-bound without ambiguity. Cross-source, unknown, or duplicate unit references are rejected before a durable write.

Until D2 creates an explicit per-scope source manifest, D1 conservatively uses every SOURCE_DOCUMENT already admitted to the Mission as the analysis denominator. Omitting an imported document therefore cannot manufacture complete analysis.

The analysis result exposes a bounded coverage summary: document count, total and covered units, uncovered count, at most 64 uncovered references, truncation marker, source-scope digest, coverage digest, and completion state. Any uncovered source unit returns PARTIAL_SOURCE_UNITS rather than PASS.

read_intake_source can address an exact unit id and rechecks the unit digest. Source reads remain read-only; durable semantic analysis truth comes from R1/G3 artifacts, not conversation state.

## Windows evidence

The exact validated head completed the full recovery intake suite on Windows:

```text
Ran 17 tests
OK
```

Coverage includes restart/replay, immutable revisions, bounded source reads, multi-section ledgers, partial-to-complete analysis, omitted-document denominator checks, bounded uncovered summaries, and forged unit-provenance rejection.

## Carry-forward

D2 and later Phase-D work still owns explicit scope manifests, semantic hydration/reconciliation generations, richer PDF/source locators, exact code-impact reconciliation, complete case/oracle/evidence closure, and full business-effect reconciliation.

D1 must not be reopened for those independent gaps unless evidence disproves a frozen D1 invariant.
