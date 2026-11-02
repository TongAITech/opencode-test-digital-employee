# RC7.2 design/construction reconciliation — 2026-11-02

BASELINE_HEAD=9476b57cf70056f958352762c14a5ec3b2b2151d
CONTRACT_SET=docs/rc7.2/00..05 + 07 + 08 + 09
OVERALL_STATUS=INCOMPLETE
DELIVERY_AUTHORIZED=false
FIELD_EVIDENCE_STATUS=NOT_AVAILABLE
KNOWN_DEVIATIONS=prior phase CI closure was incorrectly treated as whole-product readiness; portable preparation started before construction integration was demonstrated.

## Evidence interpretation

The 736 local RC7.2 contract tests and 492 passing inherited tests (one skipped)
are regression evidence, not proof of all design implementation. They include
fixtures, injected workers, mocked external services and manually constructed
canonical state. The source construction CI on 9476b57 passed on Python 3.8 and
3.11. These facts cannot close production integration or field requirements.

Completed portable job 41378144733 is an unaccepted engineering artifact.
It is not the RC7.2 delivery and must not be offered as design completion.

Status meanings: COMPONENT means an implementation and associated tests exist,
but the complete required runtime path has not been demonstrated. OPEN is a
confirmed missing slice. AUDIT means further call/evidence tracing is required.
No row below is considered whole-product COMPLETE.

## Design and phase map

| Design / plan obligation | Located implementation and tests | Audit finding / remaining work |
|---|---|---|
| Phase 0: preserve RC7.1 capabilities, close GAP-01..08 | 06 baseline; inherited RC7 regression | COMPONENT; recheck each gap through RC7.2 entry and real dispatch |
| Phase 1: ReleaseBatch/Node/Delivery/Gate/Obligation/ETU + R1 | rc72_domain, rc72_truth, rc72_repository; phase1 tests | COMPONENT; prove canonical objects used by product ingress and all execution consumers |
| Phase 2: real N1–N10 state machine and back-edges | rc72_state_machine, rc72_impact; phase2 and phase6 tests | COMPONENT; real N7 failure-to-N8 routing and full resumption not demonstrated |
| Phase 3: N2–N6 sufficient before N7 | rc72_n1..n6 completion services, rc72_sufficiency | OPEN: no dedicated N7 ExecutionAdmission; READY alone is insufficient; revalidate active deliveries, gates, contract bytes and data immediately before dispatch |
| Phase 4: adaptive obligation-first decomposition | rc72_decomposer, rc72_decomposition_truth | COMPONENT; persistent planner has no located non-test service consumer outside its definition; connect planner to actual N7 work creation and feedback |
| Phase 5: fresh worker, signed Attempt binding, reviewer, captain handoff | rc72_worker_lifecycle; phase5 tests | COMPONENT; lifecycle is used by diagnosis/failover helpers, but unified execution dispatch/resume integration remains to prove |
| Phase 6: independent diagnosis, correct semantic back-edge | rc72_diagnosis_orchestration, rc72_impact_truth | COMPONENT; stitch actual N7 result, independent N8 worker, revised upstream delivery, STALE propagation, new Attempt |
| Phase 7: capability/browser/data/model leases | rc72_capability_broker, rc72_browser_resources, rc72_data_resources, rc72_model_failover | COMPONENT; bind to admitted execution and signed authority; prove release/orphan recovery in the real path |
| Phase 8: coverage mappings and full-denominator N10 | rc72_coverage_convergence, rc72_release_scope, rc72_release_convergence | COMPONENT; connect real execution/defect/coverage state, prohibit caller-supplied success flags |
| Phase 9: teaching→compile→replay→benchmark→human→official consumption | rc72_journey_* and rc72_official_journey_execution | COMPONENT; check product exposure, real Browser adapter/ownership and trusted review; fixtures do not qualify |
| Phase 10 A–H: measured usage, cost windows, warning semantics, context, batch, dual Q7 | rc72_model_*, rc72_context_*, rc72_economy_*, rc72_safe_execution_batch, rc72_q7_admission | COMPONENT; some economy adapter integration exists; trace every real producer/evaluator/retry call and preserve mandatory scope |
| 01 §14 + GAP-01: readiness/auth recovery chain | inherited readiness/model resilience + rc72_n1_* | AUDIT: prove provider-client refresh/recreation and real dispatch blocked until required readiness |
| GAP-02: adaptive decomposition | planner modules above | OPEN integration: planner must create the actual canonical execution work, not remain a fixture API |
| GAP-03: productized Journey Teaching | journey modules above | AUDIT product entry/real capture and promotion |
| GAP-04: fresh worker provider failover | rc72_model_failover | AUDIT actual launcher and same-WorkItem retry linkage |
| GAP-05: browser isolation | rc72_browser_resources | AUDIT real BSK/browser acquisition at execution and release |
| GAP-06: STRICT capability request/amendment/delegation | rc72_authority, rc72_capability_broker | AUDIT actual Task/Attempt/Worker-scope enforcement and specialist resumption |
| GAP-07: enforce N2–N8 boundaries | node services + state machine | OPEN N7 admission/execution integration and independent N8 result consumption |
| GAP-08: ReleaseBatch business root | domain/state machine/repository | OPEN product ingress and running mission driver integration |
| Product entry (01 §2, 02 DoD) | bank_mission / mission_autonomous_driver / admin and field mission helper | OPEN: direct searches found no N6DeliveryGateService consumer outside its module; no rc72 node-service references in bank_mission, mission_autonomous_driver or admin server; field mission helper only bootstraps nodes |
| Q1/Q2 | current source platform + clean-unpack CI | Engineering only; read exact-HEAD conclusions; does not close above open construction work |
| Q3–Q9 | attestation/handoff + qualification modules | HOLD: real approved target, offline acceptance, Browser, verifier, ReleaseBatch, recovery and final evidence still required |

Static search observations above are evidence of an unlocated integration, not
proof that every possible dynamic path is absent. Such rows remain OPEN/AUDIT
until an explicit runnable product path and negative regressions establish it.

## Mandatory contract-test coverage to prove in the integrated path

| Contract | Required integrated proof | Current status |
|---|---|---|
| CT-01 | every execution Case has batch/requirement/SST/obligation lineage | COMPONENT; enforce at N7 admission |
| CT-02..04 | insufficient analysis/design/data prevents real dispatch | COMPONENT; negative actual dispatch tests needed |
| CT-05..07 | actual failure → independent diagnosis → N3/N4/N5 revision | COMPONENT; full consumer chain needed |
| CT-08..10 | fresh ETU workers, session loss recovery, captain takeover without duplicate work | COMPONENT; actual mission orchestration integration needed |
| CT-11..13 | exclusive browser, provider takeover, scoped STRICT capability requests | COMPONENT; actual dispatch/cleanup integration needed |
| CT-14 | coverage cannot create orphan cases | COMPONENT; actual coverage feedback wiring needed |
| CT-15..17 | fresh independent review, no executor upstream edits, consistent R1 truth | COMPONENT; admission and real result/gate binding needed |
| CT-18 | complete release denominator, defects, evidence and gaps govern N10 | COMPONENT; real execution/convergence path needed |
| CT-19..21 | economy never drops scope; Shanghai windows; critical path override | COMPONENT; real scheduling call-chain coverage needed |
| CT-22..24 | deterministic-first, waste guard, UNKNOWN usage truth | COMPONENT; actual producer/evaluator/repair launch coverage needed |
| CT-25..26 | per-member batch evidence and retry delta | COMPONENT; actual execution/evaluator consumers needed |

## Corrected construction order

1. Establish this reconciliation and replace misleading whole-phase closure.
2. Close Truth bootstrap/late Projection defects and exact-source regressions.
3. N7 ExecutionAdmission: immutable source/active N6 contract + upstream gates,
   canonical lineage, data validity and replay-safe receipt. No execution result
   or DataLease is manufactured by admission.
4. Obligation/Case → persistent decomposition → WorkItem/Attempt → fresh signed
   worker; acquire Capability/Data/Browser resources in deterministic order.
5. Thin N7 real tool execution, separate actual/assertion/evidence result, cleanup
   and independent N8 routing. Reject upstream redesign inside execution.
6. Connect back-edge/STALE repair, defect/RCA/regression and N10 full-denominator
   convergence; prove session/provider/resource recovery on that path.
7. Wire the same runtime into product ingress, continuation and status; close
   teaching/browser/provider/economy integration gaps row by row.
8. Full regression + same-source Windows/Linux integration qualification;
   explicitly retain target/field HOLD where external evidence is unavailable.
9. Only after all repository construction rows close may a delivery package be
   produced. Final acceptance remains evidence-based; no fixture Field PASS.

A later slice may reveal more gaps. Add them explicitly; do not change the design
or lower acceptance gates to make this ledger look complete.

## Construction findings after the initial audit

- Added rc72_n7_execution_admission: component-only, 11 new tests; no real
  dispatch consumer yet. Recheck reads hash-verified live N3/N4 inventory and
  canonical N5 binding/resources; no write occurs on denial.
- N4 candidate obligations are not yet promoted by N4 completion into the
  rc72_test_obligation repository consumed by the persistent decomposer. This
  is a confirmed canonical asset bridge gap, not a missing field environment.
- Existing N6 tests compile a separate Case-shaped fixture rather than the
  approved N4 Case. A canonical N4→N6 adapter and semantic lineage checks remain
  necessary before product integration can be considered closed.
- Historical portable preparation is quarantined and is not a delivery.

## Canonical source bridge follow-up

CanonicalDesignService now promotes approved N4 obligations and exposes exact
source Cases; CanonicalExecutableService compiles only reviewed execution
materialization plus actual canonical N1/N5 truth. N7 validates those sources
again before admission. New integrated fixtures run actual N1 completion and
anchoring, rather than planting a manual N1 PASS. The external worker/tool I/O
remains injected, so this proves repository composition, not Field operation.
Legacy N4 candidates lacking materialization remain non-executable and require
repair. Planner/worker/resource/execution/product consumers remain OPEN.

## N7 planning and Oracle findings

The persistent decomposer now has a non-test N7 planning service consumer.
It persists source-bound snapshots/ETUs and ordinary RC7 WorkItems. Product
entry/driver wiring remains open. An additional defect was found in old N4
Oracle shapes: type + evidence_ref alone is descriptive, not executable.
Executable materialization now requires fixed machine predicates and exact
source preservation through N6/N7. L1–L7 requires an explicit compatible N1
tool family, including real performance/security families for L6/L7.

## Signed preparation slice (component evidence only)

Actual persisted WorkItems now receive fresh signed Worker/session/Attempt
bindings with exact-task scope, deterministic data/browser reservations and
restart HMAC revalidation. Unstarted takeover preserves WorkItem lineage but
replaces the concrete worker and Attempt. Started execution requires a separate
cleanup/diagnosis path; it cannot use preparation rollback. N6 recompilation
preserves immutable emission time and does not treat unrelated N7 leases as its
own premature acquisitions. Final focused regression: 64 passed, including browser context hardening. Actual tool execution, cleanup/re-verification, independent
N8, N9/N10 and product controller integration remain OPEN. Multi-process lease
exclusion and child-process credential isolation are not yet proven.

## Signed dispatch boundary slice — 2026-11-02

N7 now has a callable adapter boundary consuming current signed preparations.
Intent precedes I/O; receipt, raw result and digest are durable; task and binding
enter RUNNING. Interrupted/failed calls do not repeat automatically. A permanent
exclusive-create marker also blocks calls after a crash before intent append.
Frozen N6 Oracle predicates evaluate persisted actual without caller substitutions.
This is component evidence only: injected adapters are not real Field evidence.
No cleanup, release, Case PASS, N7 PASS or delivery decision is manufactured.
Production tool adapters, inherited Attempt/Evidence finalization, actual cleanup,
resource re-verification, N8/N9/N10 and product controller remain OPEN. Broader
cross-process lease exclusion and worker environment isolation remain under audit.
