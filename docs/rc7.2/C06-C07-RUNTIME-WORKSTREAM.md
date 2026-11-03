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
- `rc72_n7_no_effect_attestation.py` verifies signed N7 precondition/probe failure and captured evidence SHA256, rejects unsigned/fabricated error claims, and rejects any observed business process/native call. **Raw append-only R1 effect events** for the same attempt/preparation/worker override even a valid signed negative check, including cold interpreters with optional tool overlays not imported.
- Tests: `test_rc72_n7_tool_dispatch.py` now verifies timeout **after simulated remote commit**, cold resume, error redaction, no additional call, retained DataLease, and forged failure-class refusal.
- CI first Windows 3.11 run (old SHA `0ca7aaf`) found 96 passed, 7 failed, due to the earlier overbroad UNKNOWN classification and one cold test ordering error; both were specifically corrected in follow-up commits. Final HEAD CI results must be verified independently.
- IMPORTANT: This is an engineering failure-injection test, not proof of a real bank payment, DSH provider, or environment.

### Slice C06-U02 — exact-second TTL and call-time authority gate

- DataLease, BrowserLease and CapabilityLease use **exclusive** TTL end `now >= expires_at`; `rc72_authority.RC72AuthorityRuntime` likewise enforces the exact second at its HMAC-signed TaskLease tool gate, rather than inheriting RC6's one-second tolerance. Historical signature audit is permitted; execution authority is not revived.
- At that same second, Data/Browser `_expire_due` classifies the lease `EXPIRED` but retains its exclusive custody until verifiable N8 physical/resource recovery. Normal `release` cannot bypass the expired-custody cleanup gate.
- `CapabilityBroker.assert_capability_lease_usable` now serializes with capability grant/revocation under the shared OS/R1 lock, so a concurrent revoke cannot be ignored by an independent decision transaction.
- Added boundary tests in `test_rc72_signed_authority_ttl.py`, `test_rc72_phase7_{data_lease,browser_lease,capability_broker}_contract.py`. Real browser/4A/DB tool invocation and post-authorization external I/O still require field validation.

### Slice C07-U01 — Captain dispatch leader fence

- New `rc72_captain_dispatch_fencing.py` maintains mission-scoped exclusive Captain dispatch custody in R1.
- Admission/ownership and takeover protected by existing cross-process OS-backed ledger lock.
- Explicit `acquire_initial`, `assert_owner`, `heartbeat`, `prepare_handoff`, `takeover`.
- `prepare_handoff` quiesces dispatch **before** `WorkerLifecycleService.create_captain_handoff`; crash leaves old Captain disabled.
- Takeover requires existing canonical `rc72_captain_handoff` and delegates readiness to `WorkerLifecycleService.takeover_captain` under the same R1/ledger.
- New generation fences old Captain; authority expires **at** `expires_at`, never one second after the TTL boundary.
- Tests: `test_rc72_captain_dispatch_fencing.py` covers R1 cold replay, two Captain contention, safe takeover, crash before checkpoint, expiry, multi-process race.
- Intended product integration contract for Session A: call `assert_owner(mission_id,lease_id,captain_session_id)` before accepting new scheduling commands; route Captain checkpoint/takeover via `prepare_handoff`/`takeover`. To close the dispatch race fully, the production scheduler must also atomically persist per-WorkItem dispatch admission under the leader fence; the current fencer alone is **not** a C07 product-closure proof.

### Slice C07-U02 — canonical TaskScheduler + Fresh Worker admission

- New `rc72_captain_scheduling.py` calls the existing `TaskScheduler.lease_task` and `WorkerLifecycleService.assign_fresh_worker` under the **same** cross-process R1 ledger lock as Captain ownership checks.
- Requires explicit Mission, Team, Captain session/lease, ETU/WorkItem lineage and trusted role-capability profile. It blocks Full Access, executor/reviewer role confusion, missing **both WorkItem and ETU capability scopes**, cross-Mission source artifacts and stale task/inputs *before* creating worker state. Formal N7 Case WorkItems additionally require a **unique exact match** in the canonical N7 plan (`Case → ETU → WorkItem`) and decomposition snapshot; same-Mission membership alone is insufficient.
- Multiple independent ETUs in the same Mission receive different fresh Worker/Session identities. Lost Session state cannot authorize automatic duplicate WorkItem lease.
- Crash after WorkerSession creation but before scheduler lease leaves an orphan. `recover_unleased_orphan` scans **raw R1 history** for exactly one initial WorkerSession event referencing **both Worker ID and Session ID**, as well as signed authority, observed DSH identity, data/browser/capability leases, Attempts, tool effects and worker evidence. If any extra raw provenance exists (including an overlay not imported in this interpreter), it fails closed. Only then is the orphan checkpointed and a fresh successor linked by `parent_session_id`. **Repeated prelease crashes** traverse a strictly linear canonical `parent_session_id` chain: every earlier generation must be CLOSED with verified prelease checkpoint; role/ETU/team scope drift, cycles, ambiguous branches or known business execution are denied.
- Tool authority issuance, real DSH launch and observed Attempt are **not** side effects of this interface. Return state is explicitly `LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH`. Product entry must connect signed TaskLease/CapabilityLease + actual DSH WorkerInvocation before claiming the work executed.
- Tests: `tests/test_rc72_captain_scheduling.py`: same-Mission two workers, Captain A→B, cross-process task competition, wrong Captain and weak capability/role rejection, N7 cross-ETU Case mismatch, missing planning snapshot, cross-Mission input artifact, crash before dispatch, cold orphan reconciliation and unknown R1 capability provenance. Tests simulate failures; they are NOT live DSH/field execution.

### Slice C07-U04 — production N7 signed-preparation handoff

- `CaptainFencedWorkItemScheduler.dispatch_etu` accepts actual professional `L1_EXECUTE ... L7_EXECUTE` role profiles (besides non-N7 synthetic test roles); a formal N7 Case WorkItem **requires** exactly `etu.test_level + '_EXECUTE'`, rejecting generic roles before allocating a Session. After the **existing** scheduler leases the WorkItem, it emits additive, strictly validated `RC72_CAPTAIN_ETU_ADMITTED` → `rc72_captain_etu_admission` R1 truth with exact Mission/Team/Captain generation/ETU/WorkItem/Worker/Session; neither Captain tokens nor fake execution results are stored.
- `ExecutionPreparationService.prepare(..., fenced_admission=dispatch)` now optionally consumes that **same R1-proven Fresh Worker and LEASED WorkItem** instead of creating another Worker or double leasing the Task. It verifies the original Captain lease is still the ACTIVE owner, role equals the canonical ETU's `Lx_EXECUTE`, the R1 admission record is exact and immutable, and WorkerSession canonical context matches the frozen N7 contract and DataRefs **before** signing a TaskLease. AgentTeams may use an arbitrary verified Team ID; no `TEAM-` + Mission naming convention is imposed on the fenced path. Signed Attempt/Capability/Data/Browser preparation continues through the inherited real N7 runtime.
- The legacy `prepare(plan_id, workitem_id)` entry remains available for existing callers and regression compatibility; C07 is **not** closed until Session A wires the explicit fenced path to the formal product entry. No changes to `rc72_release_driver.py` or `rc72_mission_factory.py`.
- `tests/test_rc72_fenced_n7_preparation.py` covers actual canonical N7 Plan + TaskScheduler → Captain admission → signed Worker/TaskLease/DataLease, R1 cold replay, missing admission record, forged Worker/Team/role/ETU/generation, arbitrary real AgentTeams Team ID, and old Captain quiescence. `tests/test_rc72_captain_scheduling.py` additionally injects a process crash **after Task lease and before R1 admission** to prove cold replay cannot silently reassign or sign work. It does not execute SUT/DSH or assert Case PASS.
- If a process dies after the Task is leased but before its R1 admission is written, the WorkItem remains LEASED without an admission proof: signing is blocked and R1 needs independent safe reconciliation. This is an explicit fail-closed crash window, not a success claim.

### Slice C07-U05 — cold bootstrap and idempotent authority admission

- The RC7.2 package's explicit `rc72_truth_bootstrap._INSTALLERS` now includes both `rc72_captain_dispatch_lease` and `rc72_captain_etu_admission` overlays. These are **additive** event types; no `rc6_runtime.truth` global core schema was changed. A fresh Python interpreter that imports only `rc7_runtime` can replay a previous Captain lease and preleased ETU admission rather than failing `UNSUPPORTED_EVENT_TYPE`.
- Formal `ExecutionPreparationService.prepare(..., fenced_admission=...)` also revalidates the **same immutable R1 Captain admission and current Captain generation inside the execution resource ledger lock** when a `PREPARED` record already exists. Previously its early idempotent return could skip all caller fence checks and restore scoped TaskLease authority with a forged/stale dispatch object.
- Added a separate-process cold-replay regression and a valid-idempotence / forged admission / quiesced Captain suite. True DSH/Provider/browser/4A validation still remains FIELD_PENDING. 
- With `concurrency.cancel-in-progress` enabled, every new PR commit cancels older queued CI jobs. Only the exact final HEAD's completed checks qualify; prior queued/cancelled statuses are never counted as passing evidence.

### Slice C07-U06 — governed formal N7 production pipeline

- `N7PipelineService(preparation, runner=..., capture_root=..., captain_scheduler=..., captain_session_id=..., captain_lease_id=..., team_id=...)` is now the **existing N7 product pipeline's opt-in governed entry**, not a disconnected scheduling demo. The unchanged `RC72ReleaseDriver(..., n7_pipeline=...)` already accepts this concrete `N7PipelineService`. A supplied scoped Captain context must be complete and backed by the **same** R1, release and original execution preparation graph, or construction fails closed.
- For each freshly planned canonical N7 Case, `N7PipelineService.complete` executes `CaptainFencedWorkItemScheduler.dispatch_etu` (R1 Captain generation / exact professional role / capability / Case-ETU-WorkItem / real TaskScheduler WorkItem lease), then `ExecutionPreparationService.prepare(..., fenced_admission=...)` (the **same** Fresh Worker/Session with signed TaskLease and Data/Browser leases), followed by the inherited actual `SignedToolDispatchService`, formal runner, Oracle, signed cleanup, independent Evidence and N7 finalization. No fake PASS/fake DSH events. If a preparation exists, the pipeline does not create a second Worker or reexecute a recorded business call.
- Every governed preparation now persists `captain_admission_id`; **all** `assert_current` call paths, including runner/cleanup/tool dispatch *without* a Captain object and cold restart, automatically reload this immutable R1 admission and validate the current Captain owner **under the same OS/R1 ledger lock before restoring tool authority**. Starting a new legacy/unfenced preparation on a Mission with an existing Captain lease is forbidden. Neither quiescence nor takeover can silently restore old business permissions.
- Targeted `tests/test_rc72_captain_n7_pipeline.py` uses the actual formal N7 pipeline with local HTTP business operations/Oracle/cleanup/Evidence and checks unique Fresh Worker for each ETU, as well as legacy bypass and quiesce-before-I/O rejection. This is engineering evidence when tests run; it is **not bank/DSH Field evidence**. `tests/test_rc72_fenced_n7_preparation.py` now covers R1-driven automatic cold authority and idempotent admission.
- **Still pending for C07 closure:** Session A must instantiate the governed pipeline at the real app entry, integrate DSH AgentTeams per-role WorkerInvocation, prove Windows/Linux same-HEAD tests, cover all N1–N10 roles/provider takeover, then perform real bank qualification. Until those gates, `C07=PARTIAL`, not `ENGINEERING_VERIFIED` or `FIELD_VERIFIED`.

### Slice C07-U03 — Provider failure and Fresh Worker failover fencing

- `rc72_model_failover.py` now protects canonical readiness updates, provider failure recording and failover with the **same cross-process R1 ledger lock**. Two cold processes must not both create a fresh replacement Worker for one provider failure. This is the runtime's **model/provider namespace**, not a product SUT FAIL or Defect.
- On failover, raw R1 N7 intent/HTTP/native-tool/process/runner events and inherited `execution_attempt.tool_call_refs` or non-preexecution outcomes **block before any successor session**. Provider timeout after a potentially committed business operation requires independent effect reconciliation, never blind fresh-worker replay.
- The N7 dispatch overlay is installed before the failover ledger-replay decision so a cold process cannot infer safety from an unloaded projection.
- Atomic guard alone does **not** make a multi-event operation crash-atomic: a crash between checkpoints/attempt binding/model assignment remains a BLOCKED recovery case. The formal runtime must continue via R1 recovery / diagnostics rather than assuming automatic repeated failover is safe.
- `tests/test_rc72_phase7_model_failover_contract.py`: concurrent cold processes compete for one provider failure, suspected N7 UNKNOWN effect, and prior canonical business tool-call all require no duplicate replacement worker.
- Additional Captain dispatch guards recheck task dependencies are still PASS and ETU not STALE/BLOCKED/SPLIT_REQUIRED at the **actual lease boundary**; an old READY label cannot override new upstream invalidation.
- CI matrix now emits per-platform JUnit XML artifacts, has `concurrency.cancel-in-progress` to reduce stale PR check accumulation, and **actually executes** the new Captain scheduler suite. This is an execution configuration, not a verification result.

## Explicit remaining gaps / NO claims

- C06 and C07 are **NOT** closed. No change to `rc72_release_driver.py`, `rc72_mission_factory.py`, or global R1 core schema. The new scheduler's orphan recovery only covers the proven pre-lease phase; post-lease/possible-business-effect orphans require independent recovery and cannot be retried automatically.
- `C06`: Tool boundary for BrowserSkill/4A, physical orphan process custody, multi-process end-to-end effects, real environment negative validation.
- `C07`: Actual production entry still has to call `CaptainFencedWorkItemScheduler.dispatch_etu` then `ExecutionPreparationService.prepare(..., fenced_admission=...)` for formal N7; other N1–N10 professional role dispatch, real DSH WorkerInvocation/Evidence, CapabilityBroker decisions in product path, model failover and true session-expiry probes remain incomplete.
- No live DSH/BSK/4A/bank proof is claimed. No PASS, BANK_FINAL, Q3–Q9 evidence, or overall implementation percentage is asserted.
- New tests are engineering-level. The matrix must **execute**, not just compile, `tests/test_rc72_captain_scheduling.py`. PR CI must finish on exact current head before `ENGINEERING_VERIFIED` can be considered; no CI result here is presumed. Attempted local clone for additional tests was blocked by outbound DNS, so it is not counted as test execution.

## Session A integration interface

1. Install `install_captain_dispatch_overlay()` before cold R1 replay (module import installs it).
2. Use exactly one canonical `TruthRuntime` instance for `CaptainDispatchFencer` and `WorkerLifecycleService` for a scheduling transaction.
3. Bind `release_id`, `mission_id`, `team_id`, and Captain session; never expose Captain credentials to a Worker.
4. For N7: call `CaptainFencedWorkItemScheduler.dispatch_etu` with `role=etu.test_level + '_EXECUTE'` and canonical N7 ETU/contract/data refs, then `ExecutionPreparationService.prepare(plan_id=..., workitem_id=..., fenced_admission=dispatch)` against the **same R1**; never directly call the inherited `TaskScheduler.lease_task` from an unfenced Captain path. A signed TaskLease/CapabilityLease plus real DSH WorkerInvocation/Attempt/Evidence is still required before claiming execution.
5. Complete product scheduling/orchestrator integration, real DSH launch and Attempt/Evidence binding, provider/field qualification and all-role coverage prior to closure.

## Evidence verification

Run on exact PR HEAD (automated matrix in `.github/workflows/rc7.2-runtime-contracts.yml`):

```bash
python -m pytest -q tests/test_rc72_n7_tool_dispatch.py tests/test_rc72_n7_pipeline.py tests/test_rc72_captain_dispatch_fencing.py tests/test_rc72_captain_scheduling.py tests/test_rc72_phase5_worker_lifecycle_contract.py tests/test_rc72_resource_process_exclusion.py tests/test_rc72_phase7_data_lease_contract.py tests/test_rc72_phase7_browser_lease_contract.py tests/test_rc72_phase7_capability_broker_contract.py tests/test_rc72_phase7_model_failover_contract.py
```

Record: commit SHA, per-job check-run conclusion, number of tests, failure logs, code-path integration, platform and field boundary. Do not call all green until exact HEAD CI is complete.
