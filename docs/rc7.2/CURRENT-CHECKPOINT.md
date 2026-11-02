# RC7.2 Current Construction Checkpoint

Status: **DESIGN_RECONCILED_INCOMPLETE / NO_DELIVERY**

CONTRACT_SET=docs/rc7.2/00..05 + 07 + 08 + 09
DELIVERY_AUTHORIZED=false
FIELD_VERIFIED=false
BANK_FINAL=NO

Read DESIGN-CONSTRUCTION-RECONCILIATION.md and CONSTRUCTION-PLAN.md. Finish
construction before preparing a delivery package. Candidate 9476b57 remains
quarantined. This checkpoint supersedes earlier component-only descriptions.

## Implemented execution composition

Current canonical N1-N6 source/gate admission -> persistent Case-to-WorkItem
planning -> fresh signed exact-task/Attempt Worker -> owned resource reservations
-> durable tool intent -> actual adapter call -> raw signed observation -> fixed
Oracle -> inherited Attempt/Assertion/Evidence -> frozen cleanup/reverification
-> owned release -> complete evidence capture -> fresh review assignment.

The formal N7 branch now binds a full inherited TargetIdentity from approved,
fresh N1 facts, with exact environment/endpoint/business release and authoritative
sources. N4 explicitly declares approved script qualification and workspace.
The real StrictScriptExecutionBundleLoader checks durable upstream qualification,
source hashes and exact frozen Case/Oracle fingerprints; no substituted loader
is required. Actual Pytest/JUnit process harnesses persist exit/stdout/stderr.
The active environment must probe the tool and verify every frozen precondition
and DataRef with file evidence before business execution. A missing check blocks
execution and its evidence is retained for independent N8 diagnosis.

Runtime signs full target/Case/source/process/probe/preparation proof for the exact
Attempt and worker. Business Oracle success cannot hide a failed runner process
or missing professional-tool evidence. Source-only preflight does not execute
readiness subprocesses before dispatch intent. Child environments omit ambient
credentials, user profiles and pytest plugins. N7 rejects import/loader injection;
legacy explicit PYTHONPATH callers retain compatibility. This is configuration
isolation, not an OS filesystem/network sandbox.

Whole-plan capture still requires every frozen evidence declaration, actual bytes,
checksum and exact Attempt ownership. A separate content-addressed store publishes
complete files atomically; both Evidence stores and live source facts are checked.
Formal proof closes the two prior target/runner gaps only for proven Cases. Plain
fixture-adapter results retain those gaps and cannot enter finalization.

An actual separate, read-only deterministic reviewer process verifies the bundle
and captured evidence denominator/checksums. Runtime rechecks canonical sources
before accepting its signed process result. Only this result can finalize native
Attempts, WorkItem bindings, independent Evaluations and the N7 NodeGate. Worker
sessions close, leases revoke, and N9 becomes READY. Partial-write and cold-replay
recovery reuse recorded review and never rerun completed business calls. Historical
lease audit does not restore tool authority. N7 success cannot converge the whole
mission: RC7.2-bound missions require an accepted active N10 delivery/gate.

## N8 actual evidence diagnosis and governed repair boundary

ExecutionDiagnosisService consumes a real failed N7 Attempt, exact contract and
runtime-signed live preparation checks. A separate read-only diagnostic process
rechecks file bytes and emits classification/confidence/rationale/affected refs
and requested remediation. A different fresh reviewer and subprocess recompute
the conclusion; caller-supplied classification or approval is not accepted.

The supported conclusive rule is deliberately narrow: an exact frozen DataRef
with a signed failed live verification becomes TEST_DATA_GAP. Reviewed N8 output
is delivered and gated before the existing semantic route returns N5 to
NEEDS_REVISION. No product defect is inferred from process exit or an unexplained
precondition/Oracle failure: UNKNOWN remains BLOCKED with no PASS gate/back-edge.
Diagnostic/review PIDs, output hashes and exact input scope are runtime-signed.
Saved results and cold replay reuse the process proof. Stable semantic route IDs
recover partial gate/gap/back-edge/transition/outcome writes without duplicates.

A repair intake now rejects old N5 delivery/gates, incomplete changed-data scope,
and generic success flags. A newer active accepted N5 delivery must still satisfy
the native full-inventory data criteria before recording repair impact. This is a
repair admission boundary, not proof of an executed N5 repair or a new successful
Attempt. Positive actual N5 repair -> recompiled N6 -> new signed Attempt remains
OPEN. The same-DataRef re-verification/version dependency is now implemented
through the explicit native handoff/anchor/finalization path below. Actual repair
boundary entry, resource cleanup and fresh business execution still need wiring. Original Attempts and owned resource leases are not silently rewritten or
released by diagnosis. The classifier/reviewer are deterministic processes, not
DSH semantic specialists. Other conclusive failure classes remain OPEN.

## N5 same-DataRef re-verification and renewed Gate

An explicit native verifier request names the binding revision, yielding a fresh
Attempt/session. Ordinary initial verification keeps rejecting existing bindings.
Exact Attempt selection is supported in anchoring/finalization; ambiguous attempts
fail closed. Raw bytes, source/Case/producer/verifier lineage and existing native
candidate checks are retained, with external DSH/tool output fixtures in tests.

Successful re-verification appends a binding revision/history without replacing
its DataRef or original evidence. Journal sequence requires the verifier to start after the
current binding and last accepted N5 Gate; finishing afterward is insufficient.
Cached/old proof cannot certify repair.
Semantic source/strategy/cleanup changes require their governed repair path.
Failed re-verification blocks old binding usability. A further fresh independent
verification is required to reactivate it. Both success and failed replay are
idempotent and successful reactivation survives cold truth replay.

The complete N5 delivery identity now includes verification revision/evidence.
Old Gate replay rejects stale evidence; a new whole-inventory delivery/Gate is
required before N6 readiness. N5-only tests explicitly provide an authorized repair
boundary and locked N6. The actual N8 compensation/entry consumer is now described
below; reuse-only N5 repair assignment still is not supplied by test state. Reuse-only data lacking an original discovery
candidate still needs its own governed repair assignment consumer.

## N8 accepted compensation and actual repair entry

RepairBoundaryService now binds accepted signed N8 data-failure diagnosis to a
fresh cleanup-only worker/lease and unchanged N1-N4 source digests. It requires
other executions and resource owners in the batch to drain, plus cross-mission
owners of the same DataRef/browser instance. Original business
execution authority is not restored, even when already revoked. Only the concrete
repair service can authorize the recovery cleanup hook; no generic callback or
caller success flag grants authority. Native resource TTL, original owner and
browser auth context are rechecked before each new external call. Fresh worker
authority does not rescue expired resource custody; governed resource renewal
is still required and is not implemented.

Frozen cleanup and complete machine verification run through the existing durable
cleanup engine. Actual local HTTP compensation is exercised. All owned resources
must verify before release. Failure retains ownership and does not open N5.
Verified completion supersedes the old binding, marks its WorkItem STALE and
preparation INTERRUPTED, closes sessions and revokes old/cleanup leases. The failed
Attempt is unchanged. N6/N7 retain historical deliveries/Gates but active pointers
are cleared and both nodes lock NOT_STARTED; N5 opens RUNNING through the native
state transition. Partial and cold recovery do not repeat compensation calls.

Completed-boundary replay is a read-only receipt/predicate/evidence/resource audit;
it does not depend on the repair still being at the original N5 state. Partial
recovery refuses newer downstream delivery/version conflicts. Source changes,
missing accepted diagnosis, failed verification, undrained workers and forged
proof are covered by negative checks. Fresh cleanup authority renewal, multi-running-worker drain orchestration, orphan
assignment/claim recovery and cleanup-failure-specific recovery remain OPEN.

This closes the previously supplied test-only repair entry boundary for supported
single-drained-execution data failures. It does not supply a reuse-only N5 repair
candidate/assignment or execute a new N7 business Attempt. N7 plans currently
include plan_id in WorkItem identity, whereas N8 retry requires original WorkItem
and ETU lineage. Revised-plan reconciliation must resolve this before retry is
claimed. Other batches are untouched; global cross-process exclusion is unchanged.

## Evidence and limits

Latest repair-entry validation: full RC7.2 + inherited regression 1384 passed,
1 skipped, 32 existing collection warnings in 519.72s. Initial related chain:
45 passed. Original-N6/current-N8 scope tightening was applied during the full run;
latest-source affected boundary/cleanup/diagnosis suite then passed 40 tests.
One additional scope test was added after full collection. Compilation/whitespace
checks passed. Logs are local work/evidence/n8-repair-boundary-current-source-full.log
and n8-repair-final-scope.log. Earlier intermediate failure from a test constructor
mistake is superseded by this corrected full run. Current new-HEAD remote result
must still be observed after push; it is not inferred from previous green runs.

Older engineering evidence is retained below for history.


Latest N5 revision validation: full RC7.2 + inherited regression 1371 passed,
1 skipped, 32 existing collection warnings in 484.99s; N5-N8 chain 208 passed.
The final worker-start ordering tightening was applied during that full run;
latest-source affected N5 suite then passed 71 tests. Final freshness suite:
8 passed (two tests were added after full-run collection). Compilation/whitespace
passed. Logs are local work/evidence/n5-reverification-full-final.log,
n5-n8-reverification-final.log, n5-reverification-latest-source.log and
n5-final-freshness-proof.log. New-HEAD remote qualification remains to be observed.


Latest N8 source validation: full RC7.2/inherited regression 1363 passed,
1 skipped, 32 existing collection warnings in 467.79s; related combined chain
59 passed; final N8 proof suite 14 passed. Two additional tamper tests in that
14-test suite were added after the full run collected tests; runtime source was
unchanged. Compilation and whitespace checks passed. Logs are local under
work/evidence/n8-full-final.log, n8-final-combined.log and n8-proof-final.log.
Remote new-HEAD CI is checked after push; it does not become PASS by implication.
The previous N7 HEAD 7c220db passed construction and Windows clean-unpack but
failed Q1 Windows platform tests. Inspection located text-mode CRLF translation
of the generated qualification fixture script versus the normalized LF candidate;
the strict loader correctly rejected source drift. Fixture script publication now
uses exact UTF-8 bytes. The loader/source hash checks are unchanged. Affected
chain revalidation passed 31 tests in 102.40s. New-HEAD Windows CI must still
qualify the correction; do not claim Windows PASS from local results.

The prior N7 validation below is retained as historical engineering evidence.

Targeted actual-runner/finalization/isolation plus inherited runtime checks:
24 passed. After the legacy explicit-module-path compatibility correction,
actual-runner/finalization/isolation plus strict qualification: 21 passed.
Full RC7.2/inherited regression: 1350 passed, 1 skipped, 32 existing collection
warnings in 330.79s. The final import-injection tightening and new negative test
were applied during that full run, then the complete affected actual-runner,
finalization, process-isolation and strict-qualification subset passed 22 tests
on the final source. Syntax compilation and whitespace checks passed. Local logs:
work/evidence/formal-full-final.log and formal-injection-boundary-final.log
(not tracked). Earlier intermediate failures are not final-source evidence.

The integration tests use an actual local HTTP target, real child processes,
actual probe/data/precondition/cleanup requests and an actual reviewer process.
Approved N1 facts, N4 inputs and upstream qualification are engineering fixtures.
This proves repository execution composition, not a production target or Field
acceptance. The reviewer is deterministic evidence verification, not a DSH
semantic reviewer or product-controller run.

## Remaining construction

Additional independent N8 classifications; actual upstream repair -> fresh Attempt;
N9 defect/accepted-failure integration; N10 full release denominator convergence;
production adapter/product-controller continuation; remaining phase/GAP rows and
real qualification/Field evidence. Mechanical data checks do not replace N5
independent certification. Review currently admits passing asserted/cleaned Cases;
accepted conclusive N8/N9 failures still need their governed branch.

Global cross-process Data/Browser exclusion, pre-intent orphan-claim recovery,
N8 multi-event dispatch recovery, and OS-level isolation remain OPEN/AUDIT.
Per-call exclusion is not global event-store locking. Unresolved legacy cleanup
requires governed N4/N6 repair. No delivery or whole-product completion is claimed.

Next: wire reuse-only N5 repair verification and renewed delivery, then reconcile
N6/new-plan compilation with original WorkItem/ETU retry lineage,
then connect N9/N10 consumers to this proven success
chain, then product ingress. Packaging does not substitute for construction.
