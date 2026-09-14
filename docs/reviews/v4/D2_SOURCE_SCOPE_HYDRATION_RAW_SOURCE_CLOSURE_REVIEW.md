# D2 Source Scope / Hydration — Raw Source Closure Review

## Exact authority

- ArchitectureBaseline: v7 / FROZEN / UNCHANGED
- Engineering branch: `work/v1.13.0-recovery-turnkey-validation`
- D1 predecessor closure: `9ef7f4428ce622df198c90ad7f85b3c043648cf9`
- D2 validated exact head: `4441f05cbf570bd5b5cea5f6e4ef450d8deccb55`
- Windows workflow: `V4 D1-D2 source analysis qualification`
- Workflow run: `34860709294`
- Windows job: `104031858983`
- Evidence artifact: `10354229782 / v4-d1-d2-source-analysis-qualification`
- Artifact ZIP SHA256: `2cbe20c24d6f9849fb883ba1e26dc765e843f4dfaab580c11fcbaebd22af6b0f`

## Decision

```ini
D2_SOURCE_SCOPE_MANIFEST = PASS / FROZEN
D2_HYDRATION_GENERATION = PASS / FROZEN
D2_GOVERNED_PRODUCT_ENTRY = PASS
D2_WINDOWS_GATE = PASS
D2 = PASS / FROZEN

ARCHITECTURE_CHANGE_REQUIRED = NO
R1_EVENT_STREAM_REMAINS_SOLE_DURABLE_TRUTH = YES
D3 = AUTHORIZED_TO_START
```

D2 closes explicit source-scope selection and durable semantic-hydration progress. It does not close later Git/AST impact, standard-case/oracle/evidence, business-effect reconciliation, final package, real-model, or bank-field gates.

## Frozen invariants

### Explicit source scope

`SOURCE_SCOPE_MANIFEST` classifies every currently admitted source exactly once as `IN_SCOPE` or `OUT_OF_SCOPE`.

- `OUT_OF_SCOPE` requires a reason.
- At least one source must be in scope.
- Duplicate, unknown, or omitted source identities fail closed.
- Manifest revision identity is immutable.
- A new admitted source changes the source snapshot digest and makes the old manifest stale.
- Existing analysis artifacts cannot be reclassified outside their scope.

Before any new BR/SR/TR durable write, source-scope preflight rejects artifacts that reference an out-of-scope source.

### Hydration generations

Each analysis generation records a durable `SOURCE_HYDRATION_GENERATION` with:

- scope identity and optional scope-manifest reference;
- source snapshot and source-unit scope digests;
- semantic-model reference;
- coverage digest;
- PARTIAL/COMPLETE status;
- total, covered, newly covered, and remaining unit counts;
- predecessor generation when the source-unit scope is unchanged;
- bounded uncovered-unit references.

Repeated identical analysis is idempotent. Restart/replay resolves the same latest generation from R1.

### Context recovery remains bounded

`work_context` exposes only bounded per-scope manifest/hydration summaries.

Exact manifest entries and hydration uncovered-unit references are available through paginated `read_intake_source` reads rather than being repeatedly aggregated into every model context.

### Semantic provenance is scope-safe

Requirement semantic-model `source_refs` contain only sources admitted by the current scope policy. An OUT_OF_SCOPE document cannot leak into R3.1 provenance as an empty or incidental source.

### Product admission is governed

`set_source_scope` is routed through the existing Requirement Analyst G3 product boundary. It retains the current Mission/Task/Attempt/Session authority and actual Host ToolContext admission; no new broad Host tool or bypass was introduced.

The construction fixture was updated to the frozen primary Host contract rather than relaxing `HOST_USER_TURN_REQUIRED`.

## Windows evidence

Exact-head Windows qualification at `4441f05c...` reports:

```text
D1-D2 source analysis regression:
Ran 20 tests
OK

Governed D2 product-entry mutation:
Ran 1 test
OK
```

The source-analysis suite covers normal analysis, stale manifests, missing classifications, exclusion reasons, out-of-scope rejection, revision immutability, partial-to-complete hydration lineage, replay idempotency, bounded context recovery, and paginated manifest/hydration reads.

The product-entry test proves a current Requirement Analyst worker can invoke `set_source_scope` only through the governed worker binding/Host call path.

## Carry-forward

D2 intentionally leaves later Phase-D work open:

1. exact Git/source/AST change-impact scope and explicit unknown edges;
2. richer PDF/page/table locator fidelity where extraction supports it;
3. full standard-case and mandatory-oracle/evidence reconciliation;
4. complete business-effect intent/sent/receipt/UNKNOWN_SIDE_EFFECT reconciliation;
5. project-native Unit/API/UI/DB/CAT execution bindings;
6. final installed package, real-model semantic proof, and bank field validation.

Do not reopen D2 for those independent gaps unless evidence disproves a frozen D2 invariant.
