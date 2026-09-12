# HumanGate resume independent raw-source review

**Current decision: ORIGINAL SENT-FENCE P1 CLOSED; FINAL EXPANDED VALIDATION STILL PENDING.** This is a bounded review of new exact-Gate owners and Host entry. No product or Git changes by reviewer. No architecture/HARD approval Gate; ordinary implementation work continues.

## P1: UNKNOWN continuation is fenced only at the resume function

resume_gate returns UNKNOWN_SIDE_EFFECT for its own CONTINUATION_SENT record, but G4 execute_capability still admits fresh execution solely through Mission ACTIVE and pending-control checks. finish_gate also completes the interaction receipt for UNKNOWN, removing that interaction's unresolved blocker. Thus another Worker/direct governed executor path can issue new SUT work while the prior continuation outcome is unknown. Repeating complete_human_takeover without resending is necessary but insufficient.

Independent actual temporary R1 + injected physical-boundary fixture (`human-gate-sent-fence-counterexample.json`) produces CONTINUATION_SENT after a lost first submit result, then calls the public G4 execute_capability method with its underlying physical boundary instrumented. A second effect is admitted, yielding effects=[first-submit, second-submit]. This verifies the missing admission fence, not a real browser click or bank effect.

Add unresolved Gate continuation admission checks to the common physical-effect boundary and relevant dispatch/progress seams. The currently executing owner needs a narrowly scoped internal permit for its already-claimed effect; neither arbitrary model payload nor a blanket bypass may release the fence. After process death, SENT without a canonical result must deny fresh conflicting work. Recovery of exact Gate receipts may report UNKNOWN while maintaining this effect fence. Include a regression against a fresh execute_capability call, not only repeat calls to complete.

## Supported source properties

HumanGate admission now branches before generic unique-Mission resolution. prepare_gate enumerates compatible Gates across the authorized candidate set and honors literal scope/subject restriction, rather than requiring a unique Mission first. Prior operation receipt is replayed before fresh selection; Gate/takeover/root/browser digest remain fixed. Model gate argument does not directly select unrelated work. No new Mission is created.

The per-Gate typed owner converges AUTO and explicit paths. Its immutable intent contains exact Gate/Task/root Attempt/origin Attempt/takeover/browser context/decision/cursor references. Shared G4 coordination serializes handback and decision. Current code checks a canonical committed R2.6 decision before retry or compensation; it does not compensate HUMAN merely because record_decision's return was lost. Closed-Gate recovery bypasses fresh PENDING selection and reconstructs final G4 facts using stable fact IDs. New typed roots use existing owner compatibility and do not change frozen Mission core events.

Verification is invoked through the existing supervisor, with explicit same-context and current owner checks. Pausing is rechecked before handback and continuation. The continuation digest/effect ID is stable and SENT persists before its call; no catch blindly retries the same resume function. These source properties do not close the separate fresh-effect bypass above.

## Required clarification by implementation policy, not user approval

Host expiry is checked only before a Gate resume intent exists. A failed first verification leaves REQUESTED, after which background recovery can start handback indefinitely because the Gate intent stores no original Host expiry. Distinguish an already accepted persistent verification request from a time-bounded effect grant. If the existing 15-minute Host authority applies to starting handback, REQUESTED/VERIFIED must reject after expiry; HAND_BACK_INTENT and later may still reconcile already-started effects. If a durable request intentionally persists, define its cancellation/expiry boundary and prove the underlying Gate expiry remains enforced. Do not silently label mere REQUESTED as an already committed external effect.

The production CDP adapter derives owner from canonical G4 BROWSER_LEASE plus a process-local pending override. The test Browser object retains its owner across simulated restart. Therefore the fixture's two-handoff count alone is not proof of production adapter restart semantics. A fresh real adapter after transfer-before-G4-lease-fact must be tested; no second *SUT* effect may be inferred from a reconstructed logical lease transition. Existing bank selectors and actual context identity still need real provider evidence.

Keep fixture failures and live evidence distinct. Same-root Attempt checks allow legal rotation within a root; validate the chosen current Attempt/continuation against normal G4 guards, rather than changing frozen R2.6 lineage. No full HumanGate, C1, Windows or bank PASS is asserted by this initial review. TASK_DIFFICULTY=HARD; REASONING_RECOMMENDATION=HIGH.

## Incremental SENT fence and authority-expiry repair recheck

Initial twelve-test suite independently completed: **12 tests / OK / 68.717s**. That run predates the new expanded CDP/multi-Mission/expiry cases; it does not certify them.

Independent latest targeted recheck (`human-gate-fence-expiry-recheck.json`) confirms the original fresh-effect bypass is closed: after CONTINUATION_SENT, public G4 execute_capability returns UNKNOWN_SIDE_EFFECT_RECONCILIATION_REQUIRED with zero calls to the instrumented underlying physical boundary. Its in-process continuation permit binds exact runtime DB, typed root and request hash, and is consumed on one entry. It is not a model argument or durable retry grant.

The owner now retains original valid_until and checks REQUESTED/VERIFIED both before verification and before HAND_BACK_INTENT. Independently, a request first left REQUESTED by failed verification, then resumed after expiry, is denied HOST_USER_TURN_EXPIRED with browser still HUMAN and only the initial takeover handoff. HAND_BACK_INTENT and later preserve recovery of potentially already-started handback. REAUTHORIZE is a separate constrained event for a fresh admitted Host operation after expiry; it retains Gate/browser/lineage and does not let background recovery invent a new user turn. Expanded fresh-turn reauthorization and production CDP restart tests still require independent result review.

No new demonstrated P0/P1 found in this incremental repair check, but final component seal is deferred pending the expanded source/tests noted above.

## Namespace/reauthorization delta review (implementation still changing)

The namespace idea is sound: new G4 fact command/idempotency IDs must include owning Mission because fact IDs are stream-local while command/idempotency keys are database-global. Existing-fact lookup precedes command generation, preserving its original returned record and avoiding a rewrite of historical event/command bytes. Reusing a shared FakeHost inventory and distinct R2.6 gate IDs makes the multi-Mission fixture respect the existing identity contracts; it does not weaken Gate selection assertions.

**New implementation P1 detected:** the changed service generates `g4:fact:hash(Mission,fact_id)`, but G4CommandContribution still accepts only `g4:fact:fact_id`. Independent execution of all four new multi-Mission/reauthorization cases failed during the first create_goal in setup, with G4_IDEMPOTENCY_INVALID (4 errors / 5.795s). This prevents all fresh G4 facts under the inspected revision, not merely the second Mission. Keep a strictly derived new-key acceptance path and legacy key compatibility in the handler; do not remove validation or change the historical golden. Implementer was notified immediately. A planned independent old-key replay fixture was blocked by the same seed failure and is not counted as passed.

REAUTHORIZE source review retains fixed Gate/browser/lineage and permits a changed request identity only after prior expiry, resetting only pre-effect verification records to REQUESTED. New Host selection/recovery tests must pass after the namespace repair before claiming this delta validated. Chrome/CDP failure reports are not converted to fixture PASS; Windows live CDP evidence remains separately pending.

## Namespace experiment withdrawn; existing G4 identity contract preserved

Implementer withdrew the uncommitted command-key experiment after the handler rejection, retaining its failed source/log separately. Current service_base._record again uses the original command/idempotency key format. Therefore the fresh-fact regression described above is not retained as an open finding against current source. No handler validation was loosened and no frozen fixture was changed to accept a new format.

Review of G4 formal design and contracts found no explicit prose promise that Goal/Batch IDs may repeat across Missions, nor an explicit global uniqueness statement. The implemented contract requires globally unique derived fact IDs because handler idempotency is fixed to fact_id in a database-global namespace. The updated fixture supplies unique goal_id/batch_id/gate_id and shares one Host inventory, while still creating two real Missions and asserting the same unique/ambiguous Gate selection sets. This is valid alignment with existing identity semantics, not weakening the selection oracle. Cross-Mission reuse of the same domain Goal ID remains an existing limitation, not a fix claimed by this wave. Production trusted owners should generate unique domain IDs automatically; do not turn this into a user-managed naming prerequisite.
