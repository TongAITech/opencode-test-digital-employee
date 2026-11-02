# RC7.2 Current Construction Checkpoint

Status: **DESIGN_RECONCILED_INCOMPLETE / NO_DELIVERY**

CONTRACT_SET=docs/rc7.2/00..05 + 07 + 08 + 09
CONTINUOUS_GOAL=ACTIVE
PACKAGING_AUTHORIZATION=after_all_repository_design_implementation_and_engineering_validation
FIELD_ACCEPTANCE_OWNER=user_after_package_transfer
EXECUTION_PLAN=docs/rc7.2/CONTINUOUS-CONSTRUCTION.md
DELIVERY_AUTHORIZED=false
FIELD_VERIFIED=false
BANK_FINAL=NO

Read DESIGN-CONSTRUCTION-RECONCILIATION.md and CONSTRUCTION-PLAN.md. Finish
construction before preparing a delivery package. Candidate 9476b57 remains
quarantined. This checkpoint supersedes earlier component-only descriptions.

## Native capability recovery intake and durable decisions — 2026-11-03

N8's accepted exact physical-tool absence can now submit an exact native
CapabilityBroker request tied to the original worker, WorkItem, Attempt and
parent lease. Default deny, specialist-delegation and human-gate policies are
consumed without any business replay or automatic grant. A permission grant
cannot install a missing executable; AUTO_GRANT is rejected by this physical
restoration intake. Specialist execution, external approval, actual restoration
and fresh re-probe remain subsequent work, not claimed by a delegation label.

Actual integration found two inherited incompatibilities: CapabilityBroker
accepted only RC7AuthorityRuntime while native N7 uses RC72AuthorityRuntime, and
its scope guard lacked the native task:WorkItem/attempt:Attempt scope. Both now
use concrete compatible runtime interfaces and exact release/worker/Attempt
scope checks; artifact scope is never increased.

The broker now freezes runtime-signed request/policy/parent decisions in R1,
serializes broker writers with an OS-held ledger lock and records ISSUING before
any child authority effect. The same request cannot issue twice, changed input
cannot reuse its identity, and unknown issuance blocks even if lock files are
lost. A recorded observation can recover missing audit projections without a
second grant. Completed replay is historical and does not restore authority.
Only live usability checks can restore an authenticated child after current
parent, binding, scope, TTL and revocation checks.

Revocation is signed and durable before lease metadata projection. Interrupted
revocation cannot restore a child on cold restart. The legacy capability
metadata still contains no signing key, Captain credential or lease signature;
the separate runtime resolution proof contains HMAC-authenticated grant context.
No Field claim is made. Legacy requests without such proof require explicit
reconciliation rather than repeated issuance. Global non-broker journal/resource
locking, unknown-issuance orphan reconciliation and actual call-time tool
interception remain C06/C07 work. Integration chain: 65 passed (2 existing
collection warnings) in 81.72s. Subsequent final cold/native-policy chain: 38
passed (1 existing warning) in 38.30s. Final Broker hardening, including
cross-release rejection and a binding superseded by another runtime, passed
19 checks; native usability refreshes R1 before accepting the binding.
Compilation/diff checks passed; same-source platform qualification is pending.

## Actual failed-tool probe diagnosis — 2026-11-03

C03 now captures failed real tool probes as runtime-signed, attempt/Case/tool-scoped
raw evidence before the dispatch exception. Native N7 observations retain the
proof for independent N8 diagnosis and fresh reviewer processes. Only a failed
probe together with runtime-observed absence of the exact local executable at
an absolute file path may establish CAPABILITY_GAP. Generic failed endpoint/tool
health or business preconditions remain UNKNOWN: tool unavailability is not
inferred from an exception string or a caller's failure-class label.

The accepted outcome reports RECOVERY_REQUIRED / CAPABILITY_BROKER with no
semantic upstream target. It does not create an N1..N6 back edge, grant authority,
replay a business action or promote the blocked Attempt. Exact source bytes,
tool scope and HMAC are checked before diagnosis and rechecked for replay.

This is a concrete classification/routing extension only. CapabilityBroker
consumer wiring, physical restoration/re-probe and fresh execution recovery
remain C07/C08 work; broader environment/analysis/design/executable diagnosis and
controlled semantic repair remain C03. No broad Phase 6 completion is claimed.
Final-source causal/runner/evidence/broker chain: 43 passed (one existing
collection warning) in 48.36s. Inherited compensation/same-identity retry/N7
finalization run: 29 passed in 62.30s; it preceded the final causal narrowing,
which is covered by the 43-check final-source chain. Compilation and diff checks
passed. Same-source platform qualification remains pending.

## Native unchanged-Case repair continuation — 2026-11-03

C02 now has a callable native continuation from an accepted, independently
verified N5 repair and applied impact set through real N6 recompilation to a
signed retry plan. The complete original Case denominator, decomposition
snapshot, ETU and WorkItem identities are preserved. Historical admission hashes,
original Case source bytes/semantics and exact Case-to-ETU mapping are checked
before any STALE target is restored to READY. A signed durable reconciliation
freezes every restoration target and the completed compensation boundary;
interruption after restoration resumes without minting another decomposition.

Current N6 contracts and N7 admissions are produced by the ordinary compiler and
admission services. Ordinary planning refuses an unreconciled accepted repair;
identity reuse requires the runtime-signed exact reconciliation, followed by all
normal current-source checks. The replacement uses a fresh worker/session/lease
and child Attempt linked to the original failure; no Case PASS is manufactured.

N5 repair can now cover other Cases in the original approved plan, each with its
own exact original contract/DataRef and independent specialist work. This is
needed when the failed input check exposes an inventory-wide physical outage.
It cannot import a different Case or silently restore unrelated data. Recognized
raw verifier evidence bytes are rehashed by native N5 resolution before a new
Gate and subsequent compilation, rather than trusting only stored metadata.

Local engineering validation runs real physical repair/verification subprocesses,
strict formal runner, HTTP business actions, frozen cleanup and independent
whole-plan evidence review/finalization. The full original denominator reaches
N7_PASS with the old BLOCKED Attempt unchanged; N10 is not auto-converged. Eight
final-source retry checks passed, covering actual full execution, interrupted
restoration, forged signatures, changed source snapshot, historical admission/
Case-to-ETU mapping and damaged raw evidence. The inherited planning suite also
passed in the preceding 12-check run.
The N5/N7/N8/canonical-source cross-node run passed 238 checks in 217.85s.
The final signed-boundary/historical-decision hardening is additionally covered
by the final-source eight-check run (21.11s). Final-source platform qualification
remains pending.
This is local engineering proof, not Field/BSK/bank acceptance. C03..C12 remain
open, including other failure classes, multi-member completed-attempt recovery,
global resource ownership and product controller wiring.

## Existing-DataRef repair and independent N5 proof — 2026-11-03

ExistingDataRepairService consumes a signed completed N8 compensation boundary
and the exact failed Case/Requirement/binding/resource. It creates no discovery
candidate for reuse-only data. A durable signed request suspends the old binding;
the native resolver also rejects a pending request if interruption occurred
before the suspension write. N6/N7 remain locked while repair is unresolved.

A fresh zero-artifact DATA_PREPARER may restore the physical resource using only
explicit tools and the original source/constructor policy. PREPARED is not data
verification. A distinct DATA_VERIFIER/session must then observe the exact DataRef
and declared preconditions. Both roles have separate ordinary WorkItems and signed task/Attempt scopes, raw DSH
output, observed tool calls and revoked post-process leases. Canonical raw-proof
artifacts and independent Evaluations close these data WorkItems; failed data
work remains failed until superseded by an evidenced later verification. The worker cannot
substitute data, change source/strategy/cleanup/validity or emit canonical PASS.

Raw bytes, exact output schema, session/tool/runtime lineage, HMAC and journal
freshness are rechecked before the native binding revision is admitted. Historical
proof survives cold restart; partial finalization and lost handoff responses reuse
observations without another process/action. Unknown producer/dispatch effects
block verification and do not auto-replay. Global exclusion/orphan reconciliation
remain C06 work; this path requires a drained accepted repair boundary.

Only the native whole-inventory N5 Gate releases N6. The actual N8 repair intake
now requires a fresh post-original-Gate independent anchor for every failed
DataRef. A new generic N5 Gate, changed_refs label, missing anchor or changed raw
proof is insufficient. Original Attempt/WorkItem failure history remains intact.

Engineering proof includes real local failure/diagnostic/reviewer/compensation,
a real independent protocol subprocess performing the physical HTTP repair, a
separate verification subprocess, native N5 Gate and native N8 repair intake.
Approved upstream facts and the DSH-protocol worker are engineering fixtures;
this is not real bank DSH/BSK qualification. Production controller wiring remains
C08. Revised N6/planning/original-WorkItem/ETU retry is implemented above; product controller wiring remains C08.

Validation: N5/N8/canonical-source/N7-admission chain 145 passed in 141.79s.
Explicit schema bootstrap, generic DIAGNOSIS-session replay composition and
no-marker unknown-dispatch guards were completed afterward; final-source cold
start/lifecycle/diagnosis/data-repair chain 69 passed (4 existing collection
warnings) in 61.85s. The new generic-process replay test found the prior base
session validator overwriting DIAGNOSIS support; explicit purpose dispatch now
preserves it after lifecycle reinstall while unknown purposes remain rejected.
Unknown dispatch cannot repeat from a restored R1 even if claim files are absent.
New-HEAD qualification is observed after push, not inferred from these results.


## Durable repair impact application

Repair invalidation now freezes its complete decision and original target
versions before the first STALE mutation. A deterministic application identity
is scoped to release, mission, repair delivery, changed references and reason.
A diagnosis-scoped durable repair intent also freezes the requested delivery,
changed references and reason; partial replay cannot silently switch repairs.
The native ImpactSet is retained once; interrupted application resumes only
against unchanged targets or the one expected STALE revision. All pending
versions are checked before resumed asset writes. Newer/replanned targets and
source/denominator drift fail closed instead of being overwritten.

An APPLIED record is historical: replay does not invalidate assets that were
rebuilt afterward. Repair registration likewise resumes the missing repair/case
write and preserves later RECOVERY_LINKED state. The actual N8 accepted-repair
consumer no longer returns early before completing an interrupted case update.
Its existing signed diagnosis, newer accepted N5 Gate and canonical proof checks
remain mandatory. This is native journal/state-machine recovery, demonstrated
with contract fixtures and a separate Python process; it does not certify a new
N5 repair or execute a replacement N7 Attempt. Cross-process exclusion remains
OPEN: a frozen decision and version checks are not a global lock. Unregistered
legacy interruptions without a frozen decision require reconciliation.

Validation: full RC7.2/inherited regression 1411 passed, 1 skipped, 32 existing
collection warnings in 800.49s. Final diagnosis-scope, interrupted-request and
node-revision tightening was applied during that run; affected final-source
chain passed 94 tests (3 existing collection warnings) in 303.02s, including
actual local N8 diagnosis and compensation-boundary regression. New fault
coverage is a canonical control-plane fixture and a separate real Python process,
not an accepted new N5 repair or new N7 business execution.

## Recovery link admission and interruption recovery

Replacement registration now requires a classified, recoverable diagnosis for
exactly the original Mission/Attempt. Semantic repairs require an impact record
for that same failure; UNKNOWN and PRODUCT_DEFECT cannot directly register a
replacement. Initial registration requires distinct nonempty Worker, Session
and task lease identities and a prepared-or-later binding. Original WorkItem,
ETU, Case and parent Attempt checks remain mandatory.

The durable recovery tuple is immutable on replay. A crash after writing the
link resumes only the missing diagnosis-state update; completed replay adds no
journal events. A different replacement binding or changed impact is rejected.
This is a lineage/admission check, not runtime authorization: signed preparation,
current canonical planning and resource authority still govern actual execution.
The new-plan/original-WorkItem/ETU identity mismatch described below remains OPEN;
this change does not claim an actual repaired N5 -> recompiled N6 -> N7 retry.

Validation: recovery contract suites 26 passed (2 existing collection warnings),
Actual N8 diagnosis/repair-boundary plus recovery regression: 48 passed in
89.55s (2 existing collection warnings); four additional scope-negative tests
were then covered by the final 26-pass contract run. Coverage includes
interrupted write with a cold TruthRuntime, unchanged original binding,
no-write replay/conflict, stale diagnosis/repair scope and reused authority.

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
Attempt. The complete positive repair -> recompiled N6 -> new signed Attempt remains
OPEN; exact-DataRef physical repair/verification and accepted repair intake are
now implemented in the newer section above. The same-DataRef re-verification/version dependency is now implemented
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

Next: reconcile N6/new-plan compilation with original WorkItem/ETU retry lineage,
then connect N9/N10 consumers to this proven success
chain, then product ingress. Packaging does not substitute for construction.
