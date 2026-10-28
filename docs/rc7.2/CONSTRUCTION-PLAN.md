# RC7.2 Construction Plan / Checkpoint Ledger

Status: ACTIVE CONSTRUCTION TRUTH

Every construction session MUST first read current `work/rc7.2` HEAD, same-HEAD CI/check-runs, `docs/rc7.2/00-BASELINE-AND-READ-ME.md` through `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`, and this ledger. Chat history or stale SHAs never override repository/R1/CI truth.

## 1. Current checkpoint

```yaml
branch: work/rc7.2
design_baseline_sha: a3426e306abf967ab822d44508127c3891c8e91e
latest_phase3_qualified_code_head_sha: af2de6d8d902647438c5be71b099d2929f0879a9
latest_phase3_qualified_ci_run: 40709689484
phase:
  phase0_reality_baseline: COMPLETE
  phase1_canonical_domain_model: CI_PASS
  phase2_n1_n10_state_machine: CI_PASS
  phase3_sufficiency_gates: CI_PASS
  phase4_adaptive_task_decomposer: NOT_STARTED
field_evidence: NOT_YET_FIELD_VALIDATED
release_status: CONSTRUCTION_ONLY
next_atomic_step: PHASE4_ADAPTIVE_DECOMPOSER_CONTRACT_TESTS_FIRST
```

`CI_PASS` means repository-level contract/regression qualification only. It does not mean in-bank Field validation.

## 2. Frozen source contracts

Read in this exact order:

1. `00-BASELINE-AND-READ-ME.md`
2. `01-AUTONOMOUS-TEST-RUNTIME-DESIGN.md`
3. `02-CONSTRUCTION-CONTRACT.md`
4. `03-N1-N10-RUNTIME-STATE-MACHINE-CONTRACT.md`
5. `04-ADAPTIVE-TASK-DECOMPOSER-CONTRACT.md`
6. `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`
7. `06-RC7.1-REALITY-BASELINE.md`
8. this ledger

## 3. Phase 0 — Reality Baseline

Status: `COMPLETE`

- commit `6fd2d40323e8872d89c5e165025652d2b69a2018`
- RC7.1 inheritance, eight structural GAPs, ReleaseBatch-root invariant, same-R1/no-shadow-runtime, Session != Truth and Worker STRICT were frozen.

## 4. Phase 1 — Canonical Domain Model

Status: `CI_PASS`

Delivered canonical truth:

- ReleaseBatch is the business root.
- N1-N10 MissionNode, NodeDelivery, NodeGate, BackEdge, ImpactSet and NodeTransition are persisted first-class objects.
- TestObligation preserves ReleaseBatch/Requirement/SST/Application/business/risk/test-level/oracle lineage.
- ETU is a persisted schedulable unit with planning snapshot, cohesion and split lineage.
- existing `rc7_task` remains WorkItem truth; existing `execution_attempt` remains Attempt truth.
- WorkItemAttemptBinding links ETU -> Task -> Attempt -> worker/session/lease refs.
- existing RC7 Gap is reused; no duplicate gap store.
- all RC7.2 truth appends/queries/replays through inherited R1.
- cross-entity lineage prevents orphan coverage-driven obligations/ETUs.

Key commits include `028460fa...`, `4256819a...`, `712a5220...`, `be66fbf8...`.

Field validation: `NO`.

## 5. Phase 2 — N1-N10 Runtime State Machine

Status: `CI_PASS`

Qualified code head: `0fdd6ef62101ba837bb623091c6ac3bbadef2e5a`
Qualified run: `40693161338`

Delivered:

- ReleaseBatch bootstrap creates exactly N1-N10 persisted nodes.
- direct PASS forbidden; PASS requires persisted NodeDelivery + NodeGate(PASS).
- forward transition requires PASS and non-STALE mandatory upstream truth.
- conflicting same-version deliveries are rejected.
- N7 failure persists explicit DIAGNOSIS transition to N8.
- N8 accepted delivery/gate precedes semantic routing.
- Gap + BackEdge + Transition persist for N1/N2/N3/N4/N5/N6/N9 routes.
- provider/capability/resource failures stay separate from SUT defects.
- UNKNOWN never auto-PASS.
- ImpactSet supports explicit/safe-fallback STALE propagation.
- STALE truth blocks N7 dispatch.
- coverage target alone can never make N10 CONVERGED.
- restart/replay reconstructs runtime from R1, not chat history.

Real TDD red run `40692350064` found and drove fixes for delivery conflict ordering and explicit DIAGNOSIS semantics.

Field validation: `NO`.

## 6. Phase 3 — N2-N6 Sufficiency / Readiness Gates

Status: `CI_PASS`

### 6.1 Red/green evidence

Tests-first head:
- `e48957695a368eed9499cbaa36326b8e6709dff3` — `test(rc7.2): freeze N2-N6 sufficiency gate contracts`
- run `40693906157` = RED on RC7.2 contracts while inherited RC7 regression remained PASS.

Implementation/fix commits:
- `cd1d0d081feaf630778c1093a28211bde7a5eb0a` — initial deterministic SufficiencyGateService.
- `8c8fe758b8b43e33baab9fe399f5256d7643f6f2` — bind sufficiency evidence to canonical `rc7_evidence`.
- `af2de6d8d902647438c5be71b099d2929f0879a9` — correct isolated Phase 3 fixtures to establish upstream truth using persisted NodeDelivery + NodeGate(PASS), never a production bypass.

Qualified run:
- workflow `40709689484`
- head `af2de6d8d902647438c5be71b099d2929f0879a9`
- overall `SUCCESS`
- RC7.2 construction contracts Python 3.8: PASS
- RC7.2 construction contracts Python 3.11: PASS
- inherited RC7 source suite Python 3.8: PASS
- runtime compile: PASS

### 6.2 Implemented clauses

N2 Requirement Gate:
- Requirement/SST identity, BR/SR/TR, business rules, roles, states/transitions, negative, boundary, permission and data rules are deterministic dimensions.
- empty dimensions cannot silently pass; explicit not-applicable requires reason + evidence refs.
- unresolved unknowns block PASS.

N3 Code Analysis Gate:
- Requirement/SST mapping, changed code, API, DTO, Service, DB, dependency impact, reverse mapping, Git evidence and CodeGraph evidence are deterministic dimensions.
- missing CodeGraph evidence or dependency impact blocks PASS.
- graph/git evidence refs must belong to the current canonical sufficiency evidence set.

N4 Test Design Gate:
- orphan TestCase is rejected.
- Requirement/SST/TestObligation/test-level lineage is checked.
- unresolved TBD/UNKNOWN, missing precondition/steps/oracle/evidence requirements block PASS.
- HIGH-risk obligations require negative and boundary depth.

N5 Test Data Gate:
- non-NONE data strategies require DataRef/precondition refs, verified and reserved state, cleanup policy.
- NONE_REQUIRED must be explicit and reasoned.

N6 Executable Readiness Gate:
- case target, execution target, tool route, input binding, data refs, assertion, oracle, evidence requirements, capabilities, resources and cleanup are checked.
- TBD/UNKNOWN prevents PASS, so Executor cannot be handed an intentionally incomplete contract and asked to guess.

Common behavior:
- `SufficiencySnapshot` persists in same R1 and survives replay.
- deterministic failure generates canonical RC7 Gap facts.
- reviewer identity/session is persisted in NodeGate.
- reviewer recommendation cannot override deterministic failure.
- Gate applies through the existing Phase 2 state machine; no parallel state machine exists.

### 6.3 Phase 3 exit decision

`PHASE3 = CI_PASS`

Open qualification:
- no real in-bank ReleaseBatch has exercised the new N2-N6 deterministic gates yet.
- therefore `FIELD_VALIDATED = NO`.

## 7. Phase 4 — Adaptive Task Decomposer

Status: `NOT_STARTED`

Next step MUST be tests-first against `04-ADAPTIVE-TASK-DECOMPOSER-CONTRACT.md`.

First implementation slice must prove at minimum:

1. ReleaseBatch/Requirement/SST/TestObligation remains the planning root.
2. unrelated SSTs cannot merge merely because API/tool is the same.
3. heterogeneous 20+ cases split into cohesive ETUs rather than one large round.
4. mixed L3/L4 split by tool/resource semantics.
5. same obligation/API/data/oracle small cases can merge.
6. coverage gap may reprioritize/repair mapped obligations but cannot create orphan canonical Case.
7. all ETUs persist planning snapshot/cohesion explanation and preserve lineage.
8. decomposition is deterministic for identical frozen input/config.

Phase 4 must not implement scheduler/Worker leasing yet; Decomposer defines work units, Scheduler later decides when/where/by whom.

## 8. Remaining phases

- Phase 4: adaptive TestObligation -> ETU decomposition/scoring/split/merge/reprioritization.
- Phase 5: Fresh Worker/Fresh Reviewer/session rotation/Captain handoff.
- Phase 6: independent diagnosis/recovery orchestration.
- Phase 7: CapabilityBroker, BrowserPool/BrowserLease, DataLease, model failover.
- Phase 8: Libra feedback through Requirement/SST/TestObligation and N10 convergence.
- Phase 9: Journey Teaching/Compiler/Replay/Benchmark.
- final: Windows + Linux + clean-unpack + real in-bank Field Acceptance.

## 9. Anti-drift rule

Future sessions MUST NOT infer completion from this file alone. Always inspect:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ frozen 00-05 contracts
+ this ledger
+ R1/evidence where applicable
```

If they differ, live repository/R1/CI truth wins and the ledger must be corrected in the same construction turn.
