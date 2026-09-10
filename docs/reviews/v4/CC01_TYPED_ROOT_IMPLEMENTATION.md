# CC-01 typed R1 root foundation

Implemented in an isolated checkout based on `240573ef054df1be57bba93fcbd2e981b17a2820`. This component adds real GeneralWork and RuntimeDiagnosis lifecycle roots to the existing R1 command/event transaction. It does not implement Worker I/O or claim F53/F54/full-product acceptance.

## Behavior

`SubjectRef(subject_kind, subject_id)` and `RuntimeService.get_subject_state(ref)` expose typed identity. For a non-Mission root the public `SubjectState` contains `subject`, `seq`, `root_version`, `owner_extension` and its owned `root_state`; no synthetic `mission_id`/Mission state is exposed. The original v1 event/command envelope and SQL column `mission_id` remain the storage compatibility name. Existing Mission accessors still reject non-Mission roots.

An explicitly registered `RootDefinition` owns a kind, disjoint namespace, creation command/event pair, version, root entity type and allowed commands/events. `ExtensionManifest.subject_kinds` defaults to `MISSION`; new root-only extensions do not initialize, serialize or project empty keys in Mission state. Kind is derived from the immutable sequence-one creation event. The bus validates an empty stream/sequence zero before creation, initializes the correct applicable contribution before its handler, and uses the existing transaction/CAS checks thereafter. Replay validates root metadata, command/event pair, namespace/entity and owned reducer membership. Core Mission events and other root-kind commands cannot mutate a non-Mission stream.

The generic root contract currently supports root lifecycle events, not nested Task/Attempt/session/lease entities. Every non-Mission command/event includes exact `payload.subject`; root event entity identity must match that subject and cannot claim a core execution session. GeneralWork's strict command schemas reject undeclared cross-root Task/lease fields. This restricted foundation must be explicitly extended before real Worker dispatch; it is not a claim that full cross-process caller fencing already exists.

`GeneralWorkService.create(subject_kind, operation_id, host_turn_ref, intent, actor)` consumes a runtime-derived operation command/idempotency identity and derives a namespaced job ID. It stores the verified-admission provenance reference without raw conversation text. Repeating an identical operation, including after completion, returns that same job; changing its intent or root kind conflicts. Concurrent identical creates append one root event. GeneralWork and RuntimeDiagnosis share lifecycle machinery but remain different immutable root kinds. Lifecycle supports CREATED/ACTIVE/PAUSED/BLOCKED/COMPLETED/FAILED/CANCELLED and bounded summaries/artifact references. A job completion is not a formal test PASS.

This service is a trusted internal port. It does not authenticate the model/user, accept raw tool calls as authority, issue effect leases, or execute files/terminal/network. The admission component must verify actual HostToolContext and operation scope before invoking it. The provenance mapping is `{schema_version,host_session_id,host_message_id,host_tool_message_id,parent_message_id,source_ref,source_digest,observed_at,valid_until}`. The typed receipt extension is owned by the separate interaction component.

Root-aware projection load/verify/full rebuild handles a mixed database, validates supported streams before clearing projections, and applies only root-applicable contributions in the existing transaction. Counterfeit Mission/Goal/Session projections on a non-Mission root are detected. Injected failures after clear or apply roll back all affected projections. R1 events and historical command results remain untouched.

`RuntimeService.assert_writable_compatible()` and the command-bus preflight reject absent root owners, unsupported root versions and unknown later root event/schema types before writes. Rebuild uses the same guard and validates affected replay before clearing. Scoped compatible Mission reads remain possible with the new root owner omitted. This is a guard in the new runtime; an unmodified older executable does not gain it retroactively. The launcher/upgrade path must retain a compatible runtime and prevent an unsupported executable from becoming a writable R1 owner. No safe writable old-binary downgrade is claimed here.

`SubjectSchedulingPort` and `SubjectReadiness` define a typed integration boundary. The existing pure R2.4 `select_ready_tasks` function accepts its ready-set shape and honors the same dispatch budget without a fake Mission/Plan. Durable Task/Attempt creation, Router provisioning, resource leases and continuous GeneralWork progress are still pending; no duplicate Scheduler implementation is added.

## Validation

The new `test_v4_typed_roots.py` suite passes **20 tests**, including:

- Both real root kinds with no Mission/core-session events or projections and no Mission extension keys.
- Four concurrent identical creates, replay after completion, changed intent/kind conflicts, lifecycle receipt retry and terminal-state rejection.
- Stale CAS, wrong typed reference, cross-job subject payloads, core/foreign commands, occupied streams, forged/repeated/pre-creation events and actual creation-command-row mismatch.
- Mixed Mission/GeneralWork/Diagnosis restart and full rebuild with exact event/command/hash preservation.
- Transaction faults after command insert, event insert, projection apply and before commit; mixed old Mission/Goal/Session/Plan plus jobs survives failures after rebuild clear/apply.
- Omitted root owner, future root version, unknown future event and counterfeit core projection rejection.
- Shared pure selection policy and exhaustion of its dispatch budget without durable writes.

The frozen golden was generated by `v4_mission_golden.py` against a `git archive` of exact `240573e`, before evaluating the modified runtime. It contains deterministic Mission/Goal/Plan/Session events, complete command rows/fingerprints/results, repeated-command results, composed replay and verification hashes. The modified canonical runtime matches that golden exactly. The fixture is synthetic compatibility evidence; its clock/UUID controls do not claim a real Host/model run. Regeneration is explicitly prohibited as a way to make an implementation pass.

Existing scripts also pass unchanged:

- `test_autonomous_orchestration.py`
- `test_g2_1_session_router_control_loop.py`
- `test_g2_waiting_human_nonblocking_scheduler_repair.py`

Reproduce the new suite with the bundled Python 3.12:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 workspace-template/.pfc-internal-field-validation/tests/test_v4_typed_roots.py
```

## Remaining integration work

Integrate the separately owned InteractionOperation receipt manifest/admission adapter; apply actual HostToolContext authority and OS-constrained effect leases; implement root-local Task/Attempt/session contracts behind the shared Scheduler/Router port; connect continuous progress; wire launcher/upgrade compatibility enforcement. Perform actual Host/model/default-entry and Windows package qualification afterward. Corpus-scale performance of the compatibility scan is not yet qualified. A passing component suite does not close those gates.
