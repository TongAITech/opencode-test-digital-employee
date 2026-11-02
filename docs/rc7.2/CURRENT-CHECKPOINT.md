# RC7.2 Current Construction Checkpoint

Status: **DESIGN_RECONCILED_INCOMPLETE / NO_DELIVERY**

CONTRACT_SET=docs/rc7.2/00..05 + 07 + 08 + 09
DELIVERY_AUTHORIZED=false
FIELD_VERIFIED=false
BANK_FINAL=NO

Read DESIGN-CONSTRUCTION-RECONCILIATION.md and CONSTRUCTION-PLAN.md. Construction
must finish before a transport package is prepared for delivery. The old portable
candidate at 9476b57 remains quarantined and is not a release.

## Implemented component composition

Truth bootstrap; current canonical N1/N4/N5 source bridge; N6 machine predicates;
read-only N7 admission; persistent planning into actual WorkItems; fresh signed
Workers scoped to exact task/Attempt; data/browser reservations; signed tool
dispatch with durable intent, raw receipts, fixed Oracle and duplicate-call guard.

New slice: N7 dispatch marks the canonical N7 node RUNNING. ExecutionEvidenceService
admits stored observations into inherited execution_attempt, assertion, evidence
and rc7_evidence, with EVIDENCE_READY binding. Historical audit is allowed after
TTL expiry/upstream STALE without restoring execution authority. Attempts remain
BLOCKED even when the business Oracle passes: cleanup/evidence review is pending.

ExecutionCleanupService executes only frozen tool/source-backed cleanup and
verification specifications. Main dispatch rejects unresolved or unscoped cleanup
before any action. Cleanup and verification have separate durable intents and raw
receipts. Fixed predicates evaluate actual results for the complete DataRef set.
All original resource ownership tuples are rechecked before cleanup evidence and
release; partial release replay never repeats external cleanup/verification.

Execution failure or cleanup failure can create a fresh independent N8 diagnosis
assignment consuming actual evidence. Completed dispatch replays reuse it. N7/N8
routing accepts explicit mission scope, so another batch is not modified.

## Evidence and limits

Final combined chain: 136 passed / 4 existing collection warnings, including
cleanup preflight, historical evidence, diagnosis, cold replay and resource
release recovery. Focused cleanup-preflight suite separately passed 47 tests. External adapters are injected fixtures;
these are repository component/integration tests, not real target or Field proof.

Case revision is explicitly the admitted N4 delivery version and source reference.
Target identity is explicitly the N1 environment source reference. Full inherited
frozen-Case/TargetIdentity and runner integration remains to close; these records
cannot grant PASS, coverage/convergence closure, NodeGate PASS or delivery.

## Remaining construction

Production adapters and product controller/continuation wiring; complete evidence
requirements and independent review/finalization; full target/runner identities;
independent N8 actual classification/repair/new Attempt; N9/N10 convergence;
remaining phase/GAP rows and real qualification/Field verification. Mechanical
cleanup verification does not replace independent N5 data certification.

Cross-process Data/Browser lease exclusion and worker environment isolation remain
under audit. Per-call exclusion markers are not global event-store locking.
Recovery for a claim before intent, and crashes during multi-event N8 dispatch,
requires further hardening. Unresolved legacy cleanup still needs governed N4/N6
repair, not an executor-invented plan.

Next atomic step: close independent execution evidence review/finalization and
full runner/target integration, then drive actual N8 recovery into a fresh Attempt
and wire N9/N10 and product ingress. Do not substitute packaging for construction.
