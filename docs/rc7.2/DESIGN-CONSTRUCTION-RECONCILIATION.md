# RC7.2 design/construction reconciliation — 2026-11-02

## Native accepted execution → full obligation evidence rollup — 2026-11-03

`AcceptedObligationExecutionProof` refreshes R1 under the shared ledger lock and
requires the actual accepted current N7 Delivery. New read-only finalization
`audit` rechecks signed independent process bytes, full bundle/source/cleanup
proof, Gate and Delivery scope, canonical review Evidence, original completed
bindings, actual PASS Attempts, independently accepted WorkItems and matching
output artifacts, and closed executor/reviewer identities. It cannot resume or
repair partial finalization, dispatch tools, restore leases or write acceptance.

The rollup maps every approved primary and secondary coverage_links obligation
to its unchanged original Case SHA, actual Attempt and current-plan ETU. Whole
Case/ETU denominators and exact canonical obligation lineage are checked; blocked,
stale, revision/split/merged ETUs do not pass. No copied Case/ETU, repeated business
call or manually promoted VERIFIED flag substitutes for accepted evidence.

`ReleaseConvergenceAggregator(execution_proof=...)` optionally consumes this
concrete same-R1/same-release native service before publishing any observation.
The existing legacy path remains compatible. Actual HTTP/pytest tests prove
primary/secondary sharing, unchanged execution count and read-only audit, while
changed process bytes, evaluator identity, canonical obligation lineage and
blocked ETU reject. The fixture deliberately retains required L1..L7 policy:
accepted L3 evidence does not turn missing levels or Mission convergence PASS.

Local verification: 16 passed in 37.42s across the native proof, inherited N10
convergence/coverage terminal and N7 pipeline tests; additional blocked-ETU proof
1 passed in 6.41s. Upstream N6 merge validation 2 passed in 76.54s. The full
28-Case product integration now also asserts whole primary/secondary obligation
rollup; its new exact-source CI is pending, not claimed by the earlier N7 run.

C05 remains ACTIVE: full incremental coverage/Gap closure, multi-version release
convergence and the production N9/N10 driver route remain open. C03/C04 conclusive
failure/defect handling, C07 all-role tool fences, product factory, Journey/economy,
final same-source qualification and COMPLETE RC7.1-equivalent package remain open.


## Native formal N7 product route — 2026-11-03

N7PipelineService connects the actual planning/preparation, signed dispatch,
FormalN7RunnerAdapter child processes, environment cleanup/verification,
immutable evidence capture and independent-process finalizer. Existing returned
calls/cleanup proofs resume without restoring released business leases. Unknown
external effects remain held without replay or cleanup. Review-pending and PASS
resume the original active Delivery/bundle, whose full native proof is audited.
A genuine accepted N7→N9 FORWARD edge skips dormant N8 scheduling; it never
changes N8 into PASS. Local engineering tests include real HTTP/process I/O;
initial approvals remain fixtures, not bank Field or production DSH proof.
C08 remains incomplete: N8 repair/N9/N10, production factory/run command and
broader semantic repair. Complete RC7.1-equivalent transport remains C12 OPEN.


ExecutionPreparationService now checks the current identity/contract/task and
all business resources under the same OS-held ledger decision lock through
worker authority restoration. This removes the intervening projection refresh
race and repeated per-resource full replays. Signed existing process suspension
still denies a cold controller before lock acquisition and is checked again
inside. Heartbeat lock contention retains the bounded existing retry semantics.
This is a narrow C06 correctness/performance improvement; legacy writers,
unknown-effect/orphan adjudication and all-role tool fences remain open.



Validation for this checkpoint (local engineering, not Field):
- Full N1..N7 product composition: 28 original approved Cases, real HTTP and
  formal child processes, cleanup, independent acceptance and read-only replay;
  1 passed in 789.79s under the explicit 900s whole-chain budget. Existing
  contract-file budgets remain 180s; path normalization supports Windows.
- Atomic preparation/process/renewal/expiry/resource exclusion and N7 pipeline:
  56 passed in 126.49s. Includes actual external lock contention at authority
  restoration, cold cleanup/review continuation, unknown effect no replay and
  actual malformed independent reviewer process held without looping.
- Windows candidate transport regression: 19 passed in 201.69s across files.
  Prior exact 95be2cc Windows CI failed five files with WinError 206: large
  fixture candidates were argv payloads. The protocol process now reads the
  complete content-addressed candidate file, preserving native review content.
  Actual production DSH's large-prompt transport still needs its supported host
  protocol verified; fixture transport is not evidence of that host capability.
- Previous N1/N4/N5 regression 21 passed in 63.82s; budget runner 4 passed.
- Logs are release-driver-n7-full-final.log, release-driver-n7-atomic-authorization-final.log
  and release-driver-windows-candidate-transport.log in ../evidence.
- Prior 95be2cc Linux platform baseline passed; Windows failed as above. New
  exact-source Windows/Linux qualification is required. No final package exists.

## Native N6 product route and canonical multi-obligation Cases — 2026-11-03

The product driver now automatically uses N6PipelineService and the existing
CanonicalExecutableService, not caller-supplied ExecutableContracts. Every
approved Case is checked for reviewed execution materialization before compile
writes; all missing Case IDs are returned with owning N4. Typed readiness
violations retain their actual canonical Case scope. Native request/schema
facts are routed to N3 at this Case boundary, never to N1 (which explicitly
cannot own them); inherited standalone compiler behavior remains compatible.

Composition exposed canonical mapping incorrectly requiring every obligation
to be a Case's primary owner. CanonicalDesignService now also recognizes the
approved coverage_links, checking Requirement/SST/layer lineage and rejecting
orphan links. It preserves all obligations, original Case identity, primary
ownership and source hashes. It never duplicates Cases or drops secondary
obligations to make N6 pass. N7/N10 must still consume the full semantic coverage
relationship; final convergence of secondary obligations remains C05 work.

N6 PASS/review-pending recovery re-audits the original approved sources and
reuses immutable contracts; no data occupancy or Case execution result is
created. Missing execution materialization remains HOLD rather than guessing.
Engineering protocol evidence and limits are in RELEASEBATCH-PRODUCT-DRIVER.md.
C08 remains incomplete: N7..N10, semantic repair routing, production factory/run
command, C07 all-role fences and final RC7.1-equivalent package remain open.


## Native N5 product route and owned WorkItem closure — 2026-11-03

The ReleaseBatch product driver now connects concrete N5PipelineService:
canonical whole-Case inventory, deterministic reuse/discovery planning, native
discovery assignment and DSH output, immediate raw anchoring/promotion, a fresh
independent verifier, native resource/binding finalization and whole N5 Gate.
Dispatched plans keep their original denominator while work is in progress;
only after all results are finalized may verified reuse plans be recomputed.
Cold continuation handles mixed finalized/pending work and partial replanning.

N5WorkItemFinalizer re-audits actual native verifier output before closing each
owned discovery task through canonical Evaluation. Negative results create
explicit TEST_DATA_GAP repair work owned by TEST_DATA with test_data capability;
the inherited TEST_DATA_DEFECT -> SCRIPT_READINESS policy remains unchanged.
N5OwnedWorkItemGateService rejects verified bindings that hide unfinished owned
tasks, independently binds Evaluations to native verifier results, and rechecks
producer/verifier raw bytes and promoted candidate hash. This is data-work
acceptance, never Case execution PASS, DataLease authority, Field or BANK_FINAL.

The driver now resumes REVIEW_PENDING through actual registered N1..N5 Gate
services, rather than returning NODE_NOT_READY after a durable Delivery write.
Unsupported nodes remain HOLD. Production N6..N10, semantic repair execution,
worker factory/run command, C07 all-role live tool fences and full portable
package remain open. General interruption inside inherited Evaluation/Gap/task
journal writes remains C06 work; tested recovery points are listed separately.


## Native N4 product route and parent-scoped acceptance — 2026-11-03

The ReleaseBatch driver now connects N4PipelineService: the exact canonical
Requirement x SST set -> native assignment -> DSH design -> immediate raw
anchor -> candidate promotion -> independent design review -> formal N4 Gate.
Cold assignment/review boundaries resume without repeating the designer.

Composition uncovered a real acceptance gap: legacy N4 obligation schema could
not carry its parent source mapping. The additive source_refs contract preserves
exact KIND:source_id:parent_artifact_id identities. N4ParentScopedDesignEvaluator
requires every mandatory parent source in a required same-kind obligation;
equal symbol IDs in different repositories cannot collapse the denominator.
It composes actual independent review with inherited deterministic Oracle and
SufficiencyV2 depth/interaction guards, retaining the native RC7.2 Case contract.
N4ParentScopedDeliveryGateService independently recomputes these checks before
writing a Delivery or opening N5, including when older review rows say PASS.

Actual DSH independent design review also required the inherited reviewer role
in RC72AuthorityRuntime; only its exact review-candidate/analysis-gap permissions
were added, never canonical Case, obligation, Evaluation or Gate write rights.
N4/driver regression and recovery evidence is recorded in
RELEASEBATCH-PRODUCT-DRIVER.md. Protocol children are engineering adapters, not
bank DSH/physical-tool Field proof. C08 remains incomplete: N5..N10, repair/retry,
worker factory/run command and C07 all-role live fences remain open. No final
RC7.1-equivalent portable package has been built or delivered.


## Native N3 product routing — 2026-11-03

The ReleaseBatch product driver now uses concrete N3PipelineService for the
application discovery -> anchored candidate -> independent source mapping
review -> every discovered code target -> independent Code evaluator -> whole
N3 Gate chain. Native Git/CodeGraph requirements and mandatory impact dimensions
remain authoritative. Unresolved discovery is a HOLD before promotion/code;
negative code sufficiency never opens N4. Source and code promotion interruption
resumes from canonical bytes without repeating discovery or analysis. Completed
N3 replays the native Gate without rolling downstream state back.

N1/N2/N3 product and recovery chain: 15 passed / 10.93 s. See
RELEASEBATCH-PRODUCT-DRIVER.md. Engineering child protocols do not qualify actual
bank DSH/Git/CodeGraph tool bodies. C08 remains ACTIVE, incomplete: N4..N10,
repair/retry routing, production factory/run command and all-role C07 fences
still open. Final RC7.1-equivalent portable package has not been built/delivered.


## ReleaseBatch product route foundation — 2026-11-03

C08 is now ACTIVE: the concrete ReleaseBatchDriver connects actual N1 strict
completion to the whole N2 Requirement fanout, governed candidate promotion,
independent DSH review and formal NodeGate. No caller-provided PASS callback or
driver completion record exists. Read-only `rc7_release.rc72_mission_cli status`
reads existing R1 without worker configuration. Cross-process batch ownership,
cold source audits, interrupted promotion-to-review continuation and unchanged
required denominator are exercised. Native regression: 37 passed / 5.60 s.

This composition uncovered and fixed N1 replay requiring N2 to stay READY:
advanced downstream states now require the original canonical forward lineage
and are not reset. See RELEASEBATCH-PRODUCT-DRIVER.md for actual route and limits.
N3..N10, repair/retry routing, production worker configuration/run command and
all-role call-time tool fences remain open. This is not a complete C08 product,
Field qualification or final package. The overall goal remains ACTIVE.


## Whole-repair resource custody — 2026-11-03

Existing-DataRef repair admission now takes the same OS ledger lock as data
reservations and native tool calls. Its durable request owns exact-resource
custody while preparation and independent verification are in progress, across
process/controller restarts and the gap between returned tool calls. Another
repair cannot concurrently claim that resource. Native tool calls reject a
conflicting unfinished repair, and normal reservations cannot bypass it.

A negative independent result (`REPAIR_REQUIRED`) retains custody. A later
repair may restore the exact resource; ordinary reservations reopen only when
that repair is independently VERIFIED, the exact binding revision points to its
anchor and contains its actual verification evidence, and its block is cleared.
A failed terminal row by itself never makes the resource available.

Validation: actual MCP preparation/verifier, independent cold-controller
reservation, negative verification then a fresh exact-binding repair and
successful verification: `native-repair-lifecycle-retry.log`, 2 passed (13.99 s).
Native repair integration: `native-repair-lifecycle.log`, 36 passed (127.98 s).
Custody/fencing and cross-process reservation checks:
`native-repair-lifecycle-cold.log`, 16 passed (40.88 s). Unknown-effect disposition,
all journal writers and general orphan recovery still require C06 construction;
this is not full design or delivery qualification.


## Native N5 call-time authority — 2026-11-03

C07 now has an actual MCP-to-parent execution bridge for existing-DataRef
preparation and independent verification. Each physical handler is admitted at
call time against the signed assignment, exact tool and arguments, current task
owner, unrecalled lease and deadline. Child workers receive a scoped ephemeral
capability and isolated environment, never the parent signing key. Native mode
cannot fall back to the legacy field handler. A reported tool call or positive
output without matching signed physical observations cannot produce a handoff.

Signed call records distinguish IN_FLIGHT, RETURNED and UNKNOWN. A transport
retry of the same returned request does not repeat effects; an unknown effect
cannot replay or reopen its former invocation. In-flight/unknown calls and data
reservations share the ledger gate and preserve conflicting resource custody
across missions. Historical evidence verifies scope and observations without
restoring an old live capability.

Validation: `native-call-gate-integrated.log`: 54 passed (129.04 s), covering the
actual MCP subprocess entry, native repair finalizers and inherited DSH/MCP
contracts. The protocol worker is an engineering adapter, not real DSH-host or
bank Field qualification. Additional custody/process checks: `native-call-gate-custody.log`, 14 passed
(29.50 s), including a different mission denied during IN_FLIGHT and after
UNKNOWN plus controller closure.

C07 remains incomplete: other node roles, non-MCP tools, physical specialists,
provider/captain/session takeover and the unified production driver still need
implementation/qualification. Generic unknown-effect disposition and full N5
lifecycle reservations remain C06 work. C03/C04/C05/C08/C09/C10/C11/C12 remain
open as tracked below; this component does not authorize final delivery.


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


## Cross-process active resource reservation — 2026-11-03

C06 now serializes DataLeaseManager, BrowserPool and native capability decision
writers through one OS-held ledger gate. R1 projection and the event-store
sequence cursor are refreshed before decisions. Release/worker/binding checks
are fresh; distinct processes or independent missions cannot acquire a second
active mutable DataRef/WRITE browser owner from a stale snapshot. Shared readers
retain their intended semantics. A dead process releases the lock without
requiring deletion of a durable marker; existing resource ownership is never
silently transferred or replaced.

Actual subprocess evidence covers competing writers, shared readers and unique
monotonic sequence numbers, dead lock-holder recovery, stale superseded bindings
and two separate canonical mission/batch/obligation/ETU/Attempt lineages. Native
preparation/compensation/retry regression75 passed; final process/Broker27 passed.
The existing TTL auto-expiry/reacquire path is not proof that unknown external
I/O has drained or cleanup completed. Expired-writer custody, verified
compensation/re-use, renewal, orphan reconciliation and actual tool-call fencing
remain mandatory C06/C07 work. Non-participating journal writers are not claimed
serialized by this manager-level gate. No Field or whole-release qualification
is inferred from these tests.


## Expired custody and accepted native compensation — 2026-11-03

Automatic expiry no longer frees a mutable DataRef or WRITE browser. EXPIRED is
unusable retained custody; a new writer waits for verified recovery, including
when another reader expired. Wall-clock expiry also requires recovery even if a
caller avoided an expiry projection and metadata still reads ACTIVE. N5 physical
repair and N8 retry/drain checks honor expired owners.

Accepted TEST_DATA_GAP compensation can clean the unchanged frozen scope through
its distinct cleanup-only actor/lease. Both cleanup phases now have runtime HMAC
receipts; a concrete native signed boundary must audit exact ownership, full
DataRef denominator, actual frozen-predicate results, two native proof records
and canonical Evidence before releasing expired custody. Invalid/missing
signatures and unrelated evidence cannot extend legacy release authority.
Business authority is revoked before compensation, survives failed verification
as a durable suspension marker and is not restored by cold startup. Native
preparation restores authority only after all resource checks pass.

Engineering validation injects expiry deterministically but executes real local
HTTP compensation, physical data repair, independent verification, fresh same-
WorkItem/ETU Attempt and full strict-runner evidence finalization to N7_PASS.
Old failure history is unchanged. A real POST with lost controller response
remains IN_FLIGHT/UNKNOWN: no compensating call or new owner is invented. Cold
partial finalization reuses signed observations without another action. Failed
cleanup retains expired custody. Integrated76 and N5/retry62 passed before final
authority hardening; final authority/retry40 and final proof/lineage22 passed.
Collection warnings are inherited. Compilation/diff checks passed.

This is a concrete accepted-data-gap recovery consumer, not generic drain proof
for every expired external process. Renewal, unknown-effect/orphan adjudication,
cleanup-time expiry after other failure classes, actual DSH call-time fencing
and final browser field recovery remain C06/C07/C09 work. Full design and portable
package delivery remain incomplete; Field/BANK_FINAL stays unverified.


## Native whole-ownership temporal renewal — 2026-11-03

The native renewal API extends one live owned Attempt's worker/data/browser
windows together, with original preparation and signed lease retained as history.
Signed PLANNED/APPLIED generation records bind Mission/Batch/WorkItem/Attempt/
Worker/Session, original contract/plan, policy, prior lease and complete resource
denominator. All projections must commit before the effective signed temporal
amendment is usable. No scope, tool, data mode, cleanup policy or identity may
change. Partial renewal blocks native execution and resumes only while its prior
deadline and current ownership remain valid. Expired or diagnosed work cannot be
revived by renewal. IN_FLIGHT requires the actual live dispatcher instance; cold
reconstruction is not a liveness proof. Policy refusal preserves incomplete work.

Preparation and renewal now share exact tuple/resource validation. A validly
signed wrong-task lease or altered data mode/cleanup contract fails before new
authority. Dispatch and formal execution carry runtime authorization capsules
with effective expiry/renewal reference and exact compiled contract/source scope.
Historical evidence consumes signed capsules/renewal history without restoring
permission, including after data repair interrupts the original preparation.
Actual local tests cross the original deadline using deterministic lease clocks,
run the full strict business/cleanup/independent finalization denominator and
preserve old preparation. Renewed data failure -> expiry -> accepted compensation
-> same WorkItem/ETU replacement -> full N7_PASS is exercised as well. No Mission
convergence or Field proof is manufactured.

Inherited chain86 passed165.06s; final source/scope/history/process/Broker53 passed
80.71s (1 inherited collection warning). Automatic product heartbeats, generic
orphan/drain recovery, provider/session takeover and DSH call-time interception
remain C06/C07/C08 work; this is not the full Phase 7 completion gate.

Platform17dd427: Construction/Q2/Linux engineering passed, Windows Q1 failed
contention checks because a sentinel byte was read before obtaining its lock.
The range is now locked without pre-read or initialization, retaining nonblocking
conflict handling for empty and existing lock files. [Microsoft CRT documentation](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking)
permits locking a range beyond EOF. Actual Windows qualification of the fix is
pending on the next exact source; no scope or timeout was reduced to hide failure.


## Owned native process heartbeat — 2026-11-03

FormalN7RunnerAdapter now uses its actual SignedToolDispatchService invocation
and owned Popen controller to poll current scope and renew the original complete
worker/data/browser tuple. Signed process observations bind PID, run/command,
worker/session/Attempt, source/compiled contract, renewal references and actual
exit. Captured stdout/stderr/command bytes are hashed and verified by the formal
receipt consumer. Neither process termination nor renewal establishes Case PASS.

Failure revokes business authority, kills/reaps the owned direct child with a
bounded wait, and retains resource custody. Remote jobs/descendants are not
presumed drained. Cold execution cannot recover authority from a saved PID or
IN_FLIGHT record. Lost append responses recover the exact fsynced signed record
without business replay. Evidence capture failure remains durably FAILED; failed
spawn cannot manufacture a PID, heartbeat or formal receipt.

Integrated native chain: 69 passed in 177.65s. Additional failure/history/cold
proof chain: 36 passed in 63.93s. Final source chain initially found a missing
PIPE constant in the isolated spawn-failure test double (36 other tests passed);
that test double was corrected; the complete heartbeat file passed all 9 tests.
Parent 2ffe9f9 passed Construction, Windows clean unpack and Windows/Linux
platform baseline. This source needs its own exact-commit platform qualification.
Generic orphan recovery, multi-member drain/reuse, DSH call-time fencing and
product-wide scheduling remain open. No Field or BANK_FINAL claim is made.


## Executed-member checkpoint before N8 repair — 2026-11-03

Native member drain consumes the same original business/Oracle/Attempt/assertion/
formal receipt and exact cleanup/resource proof as the whole-plan review, with
a separate signed historical candidate that grants no review or execution. All
required bytes are captured before signed PLANNED, which suspends cold authority;
closure and DRAINED resume after interruption without new business I/O. Original
Task RUNNING/binding EVIDENCE_READY/Attempt BLOCKED are preserved. The native
repair boundary audits DRAINED peers instead of accepting their status alone.
Actual two-member local execution -> data failure -> independent N8 diagnosis ->
blocked boundary -> peer checkpoint -> scoped compensation/REPAIR_OPEN passed.
Missing/unsigned/changed cleanup and tampered captured files fail closed.

The full-plan denominator and live upstream source checks remain unchanged.
Historical drain cannot itself approve old evidence for a repaired plan. Impact/
scope-equivalence reuse decisions and fresh Attempt scheduling for affected
completed members remain C06 work; the current retry reconciler rejects them.
Generic unknown-effect/orphan recovery and remote drain are not established.
Final checkpoint9 tests passed32.63s; actual two-member boundary1 passed5.69s.
Inherited member/review/finalization/repair47 passed124.91s; heartbeat/retry
chain21 passed101.98s. Compilation/diff checks passed. Field/BANK_FINAL stays unverified.


## Current-plan review reuses only unchanged drained members — 2026-11-03

Signed retry reconciliation freezes the original drained peers and exact native
impact. Explicit unchanged dependency scope, contract digest (including data
proof), N1..N4 lineage and current N1..N6 admission are required. Historical
preparation/lease/Attempt/WorkItem/ETU remain immutable; old execution permission
is not restored. Current whole-plan independent review consumes checkpoint bytes
and retains every Case. Read-only admission supports REVIEW_PENDING/PASS without
relaxing live admission. Finalized historical owner changes require matching
signed independent review; completed checkpoint/review cold replay is read-only.

Actual two-member local business/cleanup -> exact other-member data loss -> N8
independent diagnosis -> signed drain -> scoped compensation -> physical N5
repair/independent re-probe/new Gate -> native N6/replan -> same first Attempt
evidence + actual replacement execution -> full independent N7_PASS is proven.
A previous failed Attempt is preserved, business actions equal original Cases,
and no Mission/Field/BANK_FINAL result is manufactured. Tampered capture, impact
or decision fails before new permission; interrupted READY publication resumes
without another execution. If the completed member's data is physically repaired
or its contract/impact changes, reuse is refused; its governed new Attempt and
generic orphan recovery remain open. Integrated planning/admission/review/
finalization/drain/retry62 passed203.00s; final reuse/renewal/repair-boundary34
passed113.95s, including a renewed original member and cold finalization replay.
Compilation/diff checks passed.


## Affected completed-member fresh execution — 2026-11-03

Signed current-plan member decisions now distinguish unchanged reuse from
mandatory re-execution after actual verified drain. Before publication, the
consumer under the shared ledger gate preflights every member and applies exact
resumable binding/Task/preparation transitions. Old owners are cleared/revoked,
closed sessions are required, original signed drain/Attempt history stays intact.
Only an actual newly signed scoped worker/session/lease with next generation,
original parent Attempt and current contract/admission can own the same WorkItem
afterward. Historical proof after supersession uses an explicit authenticated
disposition, not generally relaxed owner/state checks. No old lease or process
is revived and no business I/O is launched by reconciliation.

Actual two-member local flow physically repairs both completed/failed data,
independently verifies N5, recompiles N6, executes fresh signed child Attempts
for the entire original Case denominator and reaches independent N7_PASS. Both
original Attempts remain unchanged. Business actions count the original completed
action plus every mandatory regression Case; cold finalization/history replay
is read-only. Six interrupted writes and projection-tampering guards9 passed
63.39s; actual full chain1 passed15.19s; child/heartbeat/expired-custody21 passed
68.08s. Final member source/session fence20 passed149.40s; integrated member/
retry/drain/renewal/finalization/admission63 passed229.89s. Compilation/diff
checks passed.
Multi-round recovery, generic orphan disposition and actual tool-call fencing
remain open. This is engineering evidence, not Field/BANK_FINAL.


## Repeated native recovery with authenticated past-plan identity — 2026-11-03

Historical reconciliation verification is now separate from current admission/
permission. Signed prior scope/identity/repair/boundary and content-addressed
admissions/semantic contract identities remain checked; stale past plans never
become executable through this read-only surface. A new current reconciliation
resolves an original drained peer via the signed ancestor mapping, re-evaluates
current source/impact and preserves mandatory re-execution until real new evidence.
Pending already-completed supersession projections can carry forward unchanged,
with no old authority restored or duplicate business/repair/projection writes.

Actual two-round local failures -> fresh independent N8 diagnoses -> scoped
compensations -> exact physical data repair/independent re-probes/new N5 gates ->
native N6/new child parentage -> complete independent N7_PASS cover both unchanged
reuse and a pending mandatory regression member. Both failures and prior signed
reconciliation remain immutable. Cold completed review is read-only. Ancestor/
admission/captured-evidence tampering, rehashed old contract identity, and second-
round partial publication are covered. Inherited integration32 passed230.79s;
repeated-round source12 passed133.61s. Final rehashed contract identity refusal
and both actual full/cold flows3 passed46.52s after the last identity check.
Compilation/diff checks passed. Multi-completed-peer/more-round scenario
proof, generic orphan recovery and actual product scheduling remain open.


## Mixed multiple peers and completed-regression reuse — 2026-11-03

Three Cases enter native N4 approval/N5 inventory/decomposition/actual script
qualification before any business execution. Two actually execute and clean;
third data-gap failure enters independent N8 diagnosis and scoped compensation.
Physical repair/independent re-probe changes one peer and the failed Case. Native
current decisions contain both REEXECUTE and REUSE, actual required regression
executes, and all three Cases reach independent N7_PASS with one original
snapshot/mapping and preserved affected/failed histories. Cold replay is read-only.
A bad later peer blocks all earlier projections; after a partial first-member
write, changed later evidence blocks roll-forward before further projection.

A separate two-round actual flow completes an affected peer's new regression
Attempt before another failure, then checkpoints/reuses that fresh evidence.
The invalidated root result is never revived. Both failed histories/root history
remain intact and current independent review includes the correct new peer.
Executed-peer/full/cold1 passed19.69s; mixed-three-Case/full/cold1 passed19.90s;
preflight/partial-recovery3 passed30.56s. Final mixed-peer/repeated-round/
disposition integration19 passed195.69s. Compilation/diff checks passed.
Generic orphan/drain and DSH call-time fencing remain incomplete; these tests
do not establish full-design completion or bank/Field qualification.
