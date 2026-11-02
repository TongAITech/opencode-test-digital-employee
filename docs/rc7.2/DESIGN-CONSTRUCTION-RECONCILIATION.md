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
| Phase 2: real N1–N10 state machine and back-edges | rc72_state_machine, rc72_impact; phase2 and phase6 tests | INTEGRATED COMPONENT: actual local N7 failures dispatch N8; classification/repair/full resumption remains OPEN |
| Phase 3: N2–N6 sufficient before N7 | rc72_n1..n6 completion services, rc72_sufficiency | INTEGRATED COMPONENT: dedicated current-source/gate admission and live formal precondition/DataRef verification; production ingress remains OPEN |
| Phase 4: adaptive obligation-first decomposition | rc72_decomposer, rc72_decomposition_truth | INTEGRATED COMPONENT: N7 planning service creates persistent WorkItems; feedback/product continuation remains OPEN |
| Phase 5: fresh worker, signed Attempt binding, reviewer, captain handoff | rc72_worker_lifecycle; phase5 tests | INTEGRATED COMPONENT: signed N7 workers, fresh review and cold finalization replay; product captain continuation remains OPEN |
| Phase 6: independent diagnosis, correct semantic back-edge | rc72_diagnosis_orchestration, rc72_impact_truth, rc72_impact_application | INTEGRATED DATA-FAILURE DIAGNOSIS / COMPONENT DURABLE STALE RECOVERY: real N8 process/review -> N5 back-edge; durable frozen impact/cold recovery is tested with canonical fixtures; actual accepted repair -> fresh execution remains OPEN |
| Phase 7: capability/browser/data/model leases | rc72_capability_broker, rc72_browser_resources, rc72_data_resources, rc72_model_failover | INTEGRATED COMPONENT: admitted signed execution and verified cleanup release; global exclusion/orphan recovery remains OPEN |
| Phase 8: coverage mappings and full-denominator N10 | rc72_coverage_convergence, rc72_release_scope, rc72_release_convergence | COMPONENT; connect real execution/defect/coverage state, prohibit caller-supplied success flags |
| Phase 9: teaching→compile→replay→benchmark→human→official consumption | rc72_journey_* and rc72_official_journey_execution | COMPONENT; check product exposure, real Browser adapter/ownership and trusted review; fixtures do not qualify |
| Phase 10 A–H: measured usage, cost windows, warning semantics, context, batch, dual Q7 | rc72_model_*, rc72_context_*, rc72_economy_*, rc72_safe_execution_batch, rc72_q7_admission | COMPONENT; some economy adapter integration exists; trace every real producer/evaluator/retry call and preserve mandatory scope |
| 01 §14 + GAP-01: readiness/auth recovery chain | inherited readiness/model resilience + rc72_n1_* | AUDIT: prove provider-client refresh/recreation and real dispatch blocked until required readiness |
| GAP-02: adaptive decomposition | planner modules above | INTEGRATED COMPONENT: canonical N7 planner creates actual WorkItems; product entry remains OPEN |
| GAP-03: productized Journey Teaching | journey modules above | AUDIT product entry/real capture and promotion |
| GAP-04: fresh worker provider failover | rc72_model_failover | AUDIT actual launcher and same-WorkItem retry linkage |
| GAP-05: browser isolation | rc72_browser_resources | AUDIT real BSK/browser acquisition at execution and release |
| GAP-06: STRICT capability request/amendment/delegation | rc72_authority, rc72_capability_broker | AUDIT actual Task/Attempt/Worker-scope enforcement and specialist resumption |
| GAP-07: enforce N2–N8 boundaries | node services + state machine | INTEGRATED N7 success and narrow N8 data-failure result/review/back-edge; actual repair/retry remains OPEN |
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
| CT-01 | every execution Case has batch/requirement/SST/obligation lineage | INTEGRATED COMPONENT: canonical N7 lineage/source admission and formal runner binding; product ingress remains OPEN |
| CT-02..04 | insufficient analysis/design/data prevents real dispatch | COMPONENT; negative actual dispatch tests needed |
| CT-05..07 | actual failure → independent diagnosis → N3/N4/N5 revision | COMPONENT; full consumer chain needed |
| CT-08..10 | fresh ETU workers, session loss recovery, captain takeover without duplicate work | COMPONENT; actual mission orchestration integration needed |
| CT-11..13 | exclusive browser, provider takeover, scoped STRICT capability requests | COMPONENT; actual dispatch/cleanup integration needed |
| CT-14 | coverage cannot create orphan cases | COMPONENT; actual coverage feedback wiring needed |
| CT-15..17 | fresh independent review, no executor upstream edits, consistent R1 truth | INTEGRATED N7 deterministic evidence review/result/gate; DSH/product-wide review remains OPEN |
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

## N7 inherited evidence / cleanup / independent N8 assignment — 2026-11-02

Located implementations: rc72_n7_execution_evidence, rc72_n7_cleanup and the
signed tool dispatch, lifecycle, diagnosis and state-machine services.

The runnable component chain now covers signed preparation -> actual configured
adapter invocation -> stored raw receipt -> fixed Oracle -> inherited Attempt,
Assertion and both Evidence stores -> defined cleanup call -> separate actual
per-DataRef observation -> fixed verification -> owned resource release. Execution
or cleanup failure can hand actual evidence to a fresh independent N8 assignment.
Both node routing and diagnosis replay are scoped to the source mission/binding.

Contract enforcement rejects unresolved cleanup before main tool execution.
Cleanup requires explicit tool/source and machine verification fields in approved
N4 materialization; their bytes propagate unchanged into the N6 contract. Missing
legacy fields require upstream repair; the executor cannot fill them in.

Status remains COMPONENT. Attempt is BLOCKED, task RUNNING; no success, Case
completion or Node PASS is fabricated. External adapters are fixtures. Case
revision is explicitly N4 delivery revision; target is explicitly N1 environment
source. Full inherited frozen-Case/TargetIdentity/runner integration, complete
required-evidence review, actual independent N8 classification/recovery, N9/N10,
product ingress and Field remain OPEN. Cleanup machine predicates do not replace
independent N5 certification. Partial multi-event diagnosis dispatch recovery,
orphan claims, global cross-process lease exclusion and child environment
isolation remain under audit.

## N7 whole-denominator evidence and independent review admission — 2026-11-02

ExecutionEvidenceReviewService composes canonical N1-N6 source checks, signed N7
observations, inherited Attempt/Assertion and actual cleanup/release proof. The
entire planned Case denominator must be present. Each frozen evidence requirement
must have actual file bytes with the exact Attempt/tool and expected checksum.
Copies live separately from adapter outputs in an atomic content-addressed store;
review rechecks bytes and canonical evidence. Missing/changed/out-of-scope or
oversize data blocks the whole bundle without reducing evidence scope.

The full bundle is a single R1 entity with case_results (avoiding legacy batch
replay), then a whole-plan N7 NodeDelivery and a fresh independent reviewer
assignment. Source/gate changes invalidate admission. Completed replay, delivery
append interruption, reviewer-session interruption, corrupt bytes, forged scope
and actual separate-process schema replay are covered by focused tests.

Status remains COMPONENT / NO_DELIVERY. Node is REVIEW_PENDING, Attempts BLOCKED,
WorkItems RUNNING. The service does not execute a reviewer, accept a reviewer
verdict, create NodeGate PASS or finalize execution. Full target identity and
approved runner receipt remain explicit known gaps. These facts must be bound
before the independent review/finalization slice can grant any success. Actual
N8 recovery, N9/N10, product ingress and real Field remain OPEN.


## N7 formal local execution and finalization — 2026-11-02

This supersedes prior N7 target/runner/review-admission limitations above for the
formal branch. Approved fresh N1 facts bind a complete inherited TargetIdentity.
N4 runner declarations are source-validated. The unmodified strict loader verifies
durable upstream script qualification and exact frozen Case/Oracle/source hashes.
Actual environment tool probes and complete frozen precondition/DataRef checks
produce captured evidence before the actual business runner process. Runtime
signs proof for exact target/Attempt/Worker/process. Failed preparation feeds N8;
process failure or absent professional-tool evidence cannot become Oracle PASS.

The complete evidence bundle is read by a fresh deterministic reviewer process.
Accepted signed process proof finalizes native Attempts, bindings, WorkItems and
independent Evaluations, accepts an N7 NodeGate and makes N9 READY. Recovery after
partial writes and cold restart reuses recorded review and completed business I/O.
The legacy convergence entry now requires an accepted active N10 Gate for an
RC7.2 mission; caller-supplied success cannot converge after N7 alone.

Ambient credentials, user configuration and pytest plugins are excluded from child
environments. N7 injection controls fail closed; inherited explicit module paths
remain supported. OS-level filesystem/network isolation is not implemented.

Proof uses a real local HTTP service and real readiness/runner/reviewer processes.
Approved design/target facts and script qualification inputs are fixtures. This is
engineering composition evidence, not real Field proof or a DSH semantic review.
Full source regression result is recorded in CONSTRUCTION-PLAN.md. N8 actual
repair/retry, accepted conclusive failure admission, N9/N10, product ingress,
global cross-process resource exclusion and Field requirements remain OPEN.


## N8 actual signed-data-failure diagnosis — 2026-11-02

A real independent deterministic diagnostic process and a distinct reviewer/process
now consume signed failed N7 preparation facts and actual file bytes. An exact
frozen DataRef failure can produce a reviewed N8 delivery/gate and the existing
semantic back-edge to N5. Rationale, confidence, affected refs and requested repair
are persisted. No caller provides a failure class or approval flag on this path.
Unproven causality remains UNKNOWN/BLOCKED; no product defect is inferred from
runner failure. Saved process proof survives cold replay. Stable route identities
and classification replay avoid duplicate gaps/edges after partial writes.

The repair admission checks a newer accepted active N5 delivery, recomputes native
full-inventory criteria and requires coverage of failed DataRefs. Its negative
old-gate check is proven; a positive actual N5 repair -> recompiled N6 -> fresh
Attempt integration remains OPEN and is not claimed complete. Additional failure
classifications, initial-assignment/orphan recovery, DSH semantic specialists,
N9/N10, product continuation and Field requirements remain OPEN.


## N5 native re-verification revision composition — 2026-11-02

The previously located immutable same-DataRef binding/delivery obstacle is now
addressed by an explicit native re-verification mode. A binding-revision request
creates a distinct verifier Attempt/session; anchoring/finalization selects the
exact Attempt and retains native raw/source/worker checks. Journal sequence proves
the observation postdates both binding and previous accepted N5 Gate. Successful
proof appends verification history; failed proof suspends old usability; a new
independent proof is required to reactivate. Delivery identity includes revised
verification evidence, and stale Gate replay is rejected.

Proof uses external verifier/tool fixtures and a supplied authorized repair-node
boundary. It does not close actual N8 cleanup/old-N6 invalidation/repair assignment
(including reuse-only data without a discovery candidate), N6 recompilation/fresh
N7 execution, N9/N10, product ingress or Field. No whole-product closure is inferred.


## N8 actual compensation and repair-boundary consumer — 2026-11-02

The previous manually supplied repair entry is now implemented for accepted data
diagnosis with a drained batch. The service verifies actual N8 process proof/Gate,
unchanged upstream source digests and exact resource custody; issues independent
cleanup-only authority; runs frozen compensation and per-ref predicates; releases
only verified resources; preserves failure history and locks old N6/N7 before
opening N5. Real local HTTP and signed independent diagnostic process composition
are covered. Partial/cold replay audits saved proof without repeating tool I/O or
restoring business authority. Failed verification cannot open repair.

This does not close reuse-only N5 repair assignment, actual re-verification through
N6 compilation into a fresh business execution, or original WorkItem/ETU retry
reconciliation. Current N7 WorkItem IDs incorporate plan_id, which must be
reconciled with N8 same-WorkItem replacement invariants. Grant renewal, initial
orphan/claim recovery, N9/N10/product/global exclusion/Field remain OPEN.


## Existing DataRef physical repair / independent verification — 2026-11-03

A completed accepted N8 boundary now has a callable native repair consumer even
when N5 reused data without any discovery artifact. Separate scoped DATA_PREPARER
and DATA_VERIFIER processes restore/observe the original DataRef. Runtime anchors
raw output, denies substitution or self-issued PASS, suspends old proof and uses
the native binding revision and full N5 Gate. Each failed DataRef must have a fresh
post-original-Gate proof at accepted repair intake. Partial/cold replay never
repeats known completed preparation/verification; unknown effects remain blocked.

Actual HTTP preparation and independent observation are engineering-composed with
native N8 diagnosis/compensation and N5 acceptance. The worker is a DSH-protocol
engineering adapter, not bank/provider Field proof. Revised planning/Attempt,
global exclusion/orphan recovery and product entry remain OPEN. This supersedes
the prior reuse-only candidate/assignment absence for this exact-ref policy only.
The user's requested final deliverable is a complete RC7.1-equivalent portable
package; bank acceptance follows user transfer and is not a prerequisite for
finishing repository construction and producing that engineering-qualified package.


## Native same-identity retry after accepted data repair — 2026-11-03

C02 implements the actual data-repair continuation using native N6 compilation,
current admissions, a runtime-signed durable identity reconciliation and existing
fresh-generation preparation. The original immutable decomposition, full Case
inventory, ETUs and WorkItems remain authoritative; changed Case source, old
admission hashes or Case-to-ETU mapping cannot authorize restoration. Only the
frozen impact-authorized STALE targets become READY; no PASS is manufactured.
Partial restoration resumes idempotently. The compensation boundary and old
Attempt/binding remain immutable lineage in the signed record.

The engineering test restores every physically unavailable DataRef via separate
preparer and verifier processes, recompiles N6, executes all original Cases with
the strict runner, verifies cleanup and independently finalizes N7. The original
failed Attempt remains BLOCKED and N10 remains un-converged. Native N5 now rejects
changed raw-verifier bytes before issuing its Gate. Other original-plan Cases
may obtain exact-resource repair assignments; outside-plan Cases and active
resource owners remain forbidden. Arbitrary alternate decomposition is not
accepted through this unchanged-semantics protocol.

This closes the narrow data-repair-to-execution gap, not the full Phase 6 gate.
Other semantic failure classes, completed-member reconciliation, production
call-time tool scopes, global ownership and controller wiring remain open.
Local protocol subprocesses are engineering evidence, not bank Field proof.


## Failed tool probe causal boundary — 2026-11-03

The real formal adapter now preserves failed tool probe bytes under a signed
attempt/Case/tool scope. Native evidence and independent N8 processes consume
those observations. Runtime-observed absence of the exact absolute local tool
executable supports CAPABILITY_GAP -> CAPABILITY_BROKER; a generic health failure
or unsatisfied business precondition remains UNKNOWN. Tampered bytes, tool scope
and signatures are rejected before diagnosis. The original Attempt stays BLOCKED
and no semantic back edge or automatic business retry is produced. This closes
one real classification path; it does not close the entire C03 or broker/product
recovery integration. Final-source chain: 43 passed, one pre-existing collection
warning; inherited compensation/retry/finalization: 29 passed before final causal
narrowing (which has its own final-source coverage).


## Native capability recovery consumer / signed decision journal — 2026-11-03

Accepted N8 physical-tool absence now calls the native policy Broker with the
same scoped worker/WorkItem/Attempt/parent lease. Deny, delegation and human-gate
outcomes do not replay business work or imply physical restoration. Automatic
permission is rejected for a missing executable. Real specialist repair,
approval consumption, re-probe and replacement execution remain open.

The inherited Broker was not compatible with native RC72AuthorityRuntime or its
exact task/attempt scope. Native interface support now preserves release,
identity, parent and artifact/tool bounds. Runtime-signed resolution records
freeze the request/policy/parent; OS-held broker ledger serialization and an
ISSUING pre-effect state prevent duplicate grants. Lost observations remain
unknown and cannot automatically issue again. Recorded effects recover missing
metadata without issuing; historical replay itself restores no authority.
Live usability refreshes R1 and checks current binding/parent/TTL/revocation
before HMAC-authenticated child restoration. Signed revocation precedes its
metadata projection and survives interrupted cleanup and cold restart.

Proof: integration65, final cold/native policy38, final broker19 passed; existing
collection warnings only. These checks cover real local HTTP failure/native
N8/Broker intake, three safe policies, forged proof, concurrent requests,
unknown issuance, replay/projection recovery, fresh-process schema bootstrap,
revocation, parent revocation and externally superseded bindings. Global
non-broker resource/journal locks and actual call-time DSH scope enforcement
remain incomplete and cannot be inferred from these Broker tests.
