# RC7.2 C06 / C07 Runtime Workstream — additive handoff to Session A

BASELINE_HEAD=`7efb3c8aa62f22629e570e3381727969524bf598`
CONTRACT_SET=`docs/rc7.2/00..05`, `10-DESIGN-IMPLEMENTATION-CLOSURE-CONTRACT.md`
WORK_BRANCH=`work/rc7.2-runtime`
FIELD_EVIDENCE_STATUS=`FIELD_PENDING / NO_BANK_FINAL`

## Contract impact (without reimplementing accepted components)

Source: `05` §§3,8,12,14,15,17,18,19,21,22; `10` C06/C07.

| Existing implementation verified in baseline code | Remaining contract boundary |
| --- | --- |
| `rc72_data_resources.py`: canonical exclusive DataLease and custody over expiry | Multi-process stress, owner-orphan evidence and tool-boundary complete integration |
| `rc72_browser_resources.py`: BrowserPool, exclusive write, AuthKeeper isolation metadata | Real BSK/CDP / 4A instance ownership and target-field verification |
| `rc72_capability_broker.py`: restricted delegation and temporary signed TaskLease | End-to-end production tool invocation of temporary grants and revocation |
| `rc72_lease_renewal.py`: signed same-Attempt renewal | Same-HEAD Windows/Linux negative qualification |
| `rc72_worker_lifecycle.py`: Fresh Worker, rotation, Captain checkpoint/takeover | Fencing simultaneous Captain dispatch authority |
| `rc72_model_failover.py`: provider failure namespace and new worker fallback | Real DSH provider quota/auth/timeout field probes |
| `rc72_mission_node_handoff.py` / N2–N5 handoffs: concrete governed DSH launchers | Common all-role product scheduling and C07 final acceptance |
| `rc72_n7_tool_dispatch.py`: durable IN_FLIGHT intent and permanent claim | Adapter exception after remote commit previously misclassified FAILED |

## Implemented in this PR

### Slice C06-U01 — indeterminate external effect

- N7 adapter errors after admission persist `UNKNOWN`, only exception class (never exception text), **unless** the trusted FormalN7Runner supplies cryptographically verified pre-execution negative evidence (no observed process/business call). That deterministic no-business-effect subset retains `FAILED` and the N8 failure-diagnosis contract.
- Retain side-effect custody `possible_external_effect=true` and `replay_prohibited=true`.
- Cold/hot redispatch refuses UNKNOWN instead of returning a FAILED result that might be misinterpreted as harmless.
- The R1 intent still precedes external I/O; original permanent OS claim is retained.
- Existing preflight failures remain before business I/O, and returned receipts remain independently evaluated.
- `rc72_n7_no_effect_attestation.py` verifies signed N7 precondition/probe failure and captured evidence SHA256, rejects unsigned/fabricated error claims, and rejects any observed business process/native call.
- Tests: `test_rc72_n7_tool_dispatch.py` now verifies timeout **after simulated remote commit**, cold resume, error redaction, no additional call, retained DataLease, and forged failure-class refusal.
- CI first Windows 3.11 run (old SHA `0ca7aaf`) found 96 passed, 7 failed, due to the earlier overbroad UNKNOWN classification and one cold test ordering error; both were specifically corrected in follow-up commits. Final HEAD CI results must be verified independently.
- IMPORTANT: This is an engineering failure-injection test, not proof of a real bank payment, DSH provider, or environment.

### Slice C07-U01 — Captain dispatch leader fence

- New `rc72_captain_dispatch_fencing.py` maintains mission-scoped exclusive Captain dispatch custody in R1.
- Admission/ownership and takeover protected by existing cross-process OS-backed ledger lock.
- Explicit `acquire_initial`, `assert_owner`, `heartbeat`, `prepare_handoff`, `takeover`.
- `prepare_handoff` quiesces dispatch **before** `WorkerLifecycleService.create_captain_handoff`; crash leaves old Captain disabled.
- Takeover requires existing canonical `rc72_captain_handoff` and delegates readiness to `WorkerLifecycleService.takeover_captain` under the same R1/ledger.
- New generation fences old Captain and cannot be re-used after lease expiration.
- Tests: `test_rc72_captain_dispatch_fencing.py` covers R1 cold replay, two Captain contention, safe takeover, crash before checkpoint, expiry, multi-process race.
- Intended product integration contract for Session A: call `assert_owner(mission_id,lease_id,captain_session_id)` before accepting new scheduling commands; route Captain checkpoint/takeover via `prepare_handoff`/`takeover`. To close the dispatch race fully, the production scheduler must also atomically persist per-WorkItem dispatch admission under the leader fence; the current fencer alone is **not** a C07 product-closure proof.

### Slice C07-U02 — canonical TaskScheduler + Fresh Worker admission

- New `rc72_captain_scheduling.py` calls the existing `TaskScheduler.lease_task` and `WorkerLifecycleService.assign_fresh_worker` under the **same** cross-process R1 ledger lock as Captain ownership checks.
- Requires explicit Mission, Team, Captain session/lease, ETU/WorkItem lineage and trusted role-capability profile. It blocks Full Access, capability gaps and stale task/inputs *before* creating worker state.
- Multiple independent ETUs in the same Mission receive different fresh Worker/Session identities. Lost Session state cannot authorize automatic duplicate WorkItem lease.
- Crash after WorkerSession creation but before scheduler lease leaves an orphan. `recover_unleased_orphan` checks R1 for absence of signed authority, observed DSH identity, data/browser/capability leases, Attempts, tool effects and worker evidence, then checkpoints the orphan and authorizes a new fresh successor with `parent_session_id`. If any provenance exists, it fails closed.
- Tool authority issuance, real DSH launch and observed Attempt are **not** side effects of this interface. Return state is explicitly `LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH`. Product entry must connect signed TaskLease/CapabilityLease + actual DSH WorkerInvocation before claiming the work executed.
- Tests: `tests/test_rc72_captain_scheduling.py`: same-Mission two workers, Captain A→B, cross-process task competition, wrong Captain and weak capability rejection, crash before dispatch, cold orphan reconciliation, negative unknown authority/effect, no leaked Captain tokens. These are engineering-level R1 tests, not real DSH/field execution.

## Explicit remaining gaps / NO claims

- C06 and C07 are **NOT** closed. No change to `rc72_release_driver.py`, `rc72_mission_factory.py`, or global R1 core schema. The new scheduler's orphan recovery only covers the proven pre-lease phase; post-lease/possible-business-effect orphans require independent recovery and cannot be retried automatically.
- `C06`: Tool boundary for BrowserSkill/4A, physical orphan process custody, multi-process end-to-end effects, real environment negative validation.
- `C07`: All role dispatch and live Worker/Attempt/CapabilityLease/ModelAssignment in same production product entrypoint, resource-bound model failover, all-role Fresh Worker lifecycle, Captain fencing integration and true session-expiry probes.
- No live DSH/BSK/4A/bank proof is claimed. No PASS, BANK_FINAL, Q3–Q9 evidence, or overall implementation percentage is asserted.
- New tests are engineering-level. PR CI must finish on exact current head before `ENGINEERING_VERIFIED` can be considered; no CI result here is presumed.

## Session A integration interface

1. Install `install_captain_dispatch_overlay()` before cold R1 replay (module import installs it).
2. Use exactly one canonical `TruthRuntime` instance for `CaptainDispatchFencer` and `WorkerLifecycleService` for a scheduling transaction.
3. Bind `release_id`, `mission_id`, `team_id`, and Captain session; never expose Captain credentials to a Worker.
4. Gate every scheduling admission at the product entry, not only CLI tests.
5. Complete atomic work-dispatch admission, orchestrator integration, and provider/field qualification prior to closure.

## Evidence verification

Run on exact PR HEAD (automated matrix in `.github/workflows/rc7.2-runtime-contracts.yml`):

```bash
python -m pytest -q tests/test_rc72_n7_tool_dispatch.py tests/test_rc72_n7_pipeline.py tests/test_rc72_captain_dispatch_fencing.py tests/test_rc72_captain_scheduling.py tests/test_rc72_phase5_worker_lifecycle_contract.py tests/test_rc72_resource_process_exclusion.py tests/test_rc72_phase7_data_lease_contract.py tests/test_rc72_phase7_browser_lease_contract.py tests/test_rc72_phase7_capability_broker_contract.py tests/test_rc72_phase7_model_failover_contract.py
```

Record: commit SHA, per-job check-run conclusion, number of tests, failure logs, code-path integration, platform and field boundary. Do not call all green until exact HEAD CI is complete.
