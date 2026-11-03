# Native incremental coverage measurement (engineering bridge)

`NativeLibraMeasurementService` composes the concrete original N1 expected-scope
provider and the concrete accepted N9 service over the same R1 and source. It
reads an operator-configured normalized HTTP bridge after accepted N7/N9. This
is an implemented bridge protocol, not an assertion about a Libra vendor API,
bank report origin, or Field approval. Production authenticated provider binding,
coverage-gap repair routing and the complete N10 controller remain open.

## Original normative policy

`RC72_EXPECTED_RELEASE_SCOPE_V1` remains compatible and carries no coverage
policy. V2 retains all V1 fields and adds exactly `coverage_targets`, keyed by
**every original Application ID**. Each target has exactly:

```json
{
  "metric": "LINE",
  "base_revision": "original baseline revision",
  "target_revision": "original release revision",
  "target_ratio": 0.9,
  "report_url": "https://configured-bridge.example/report",
  "auth_mode": "WORKER_HEADER",
  "source_ref": "catalog://original-coverage-policy/version"
}
```

Supported metrics are LINE, BRANCH and METHOD. Distinct nonempty revisions and
finite numeric thresholds in (0,1] are required; booleans are not numbers.
HTTP/HTTPS URLs are fixed by the captured policy, with no embedded credentials
or fragment. Targets are frozen with the original native N1 capture and receipt;
callers cannot supply a percentage, denominator, URL or lowered threshold to
`collect`. `WORKER_HEADER` currently returns a specific HOLD before measurement
WorkItem creation or HTTP I/O. Only explicitly ANONYMOUS targets can be read by
this engineering implementation. No authenticated-to-anonymous fallback exists.

## Actual read and proof

One deterministic measurement identity binds original input bytes, accepted N7
Gate and Application. The canonical COVERAGE_AUDIT WorkItem consumes the actual
original N1 Delivery artifacts and accepted N7 Case outputs. A distinct coverage
worker receives a scoped, expiring read-only lease; its role cannot author truth
artifacts. The program validates current Task/identity/lease/source before and
after the fixed GET. It disables inherited proxy routing and redirects, bounds
time and response size, and sends `X-RC72-Measurement-ID`.

A signed IN_FLIGHT intent precedes I/O. Captured bytes are written exclusively
and flushed to disk before acceptance. Lost authority/source after the effect
preserves an UNKNOWN receipt and any captured body; it never automatically
repeats the HTTP read. A returned invalid report also never triggers a new read.
Controller recovery from an already returned, independently reviewed report can
finish metadata without issuing another read lease.

The response has exactly schema `RC72_LIBRA_INCREMENTAL_REPORT_V1`,
measurement_id, application_id, base_revision, target_revision, metric,
observed_at (integer Unix seconds), source_ref (`libra://...`) and nonempty units.
Each unit has exactly a unique nonempty unit_id, nonempty code_slice and boolean
covered. Identity/revisions/metric must equal the fixed request. Freshness is
bounded by the accepted N7 Gate and observed read completion. Duplicate JSON
keys and duplicate unit IDs are refused. Full unit counts, uncovered slices and
ratio are derived from captured units; no report-supplied percentage is accepted.
The bridge remains responsible for supplying the complete authoritative unit
population; this protocol does not independently inspect the bank source tree.

A separate isolated Python process reviews the parent capture. Signed receipt
metadata binds request hash, process ID, exit code and output hash. Canonical
Artifact, Evidence and independently attributed Evaluation close the measurement
WorkItem. A valid below-target measurement is a PASS measurement WorkItem and
still produces `coverage_met=false`. The observation retains the report's actual
observed_at; it does not substitute metadata acceptance time.

## N10 consumption and restart

Native `ReleaseConvergenceAggregator` requires this concrete proof provider,
with the same original expected-scope instance and accepted N7 pipeline. It
reaudits receipt scope, historical authority, body, separate review request and
result, actual Task/Evaluation/Artifact/Evidence and derived observation. Audit
requires all closure metadata already present and performs no network read,
review process, new Task or authority restoration. Unattested percentage rows
cannot replace the native result. Removing providers after native scope history
cannot regain the legacy percentage path.

A measured target cannot erase missing Requirement/SST/L1..L7 obligations,
professional defects, unresolved gaps or runtime blockers. Engineering localhost
fixtures verify this bridge only. Complete product/Field certification and the
RC7.1-equivalent full portable package are separate outstanding deliverables.
