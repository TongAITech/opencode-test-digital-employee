# RC7.2 C10 — Product economy integration handoff

Status: PARTIAL — COMPONENT / CONTRACT TESTED; PRODUCT INGRESS AND FIELD MEASUREMENT PENDING.
This document does not override frozen RC7.2 contracts 02, 04, 09 or 10.

## Audit finding

The native product composer in rc7_runtime/rc72_mission_factory.py requires DshHeadlessWorkerLauncher instances and requires NativeN1ReadDshLauncher for the N1 role. Existing TokenMeteredDshLauncher and Rc72TokenUsageLauncherProxy are wrappers, so they cannot be substituted directly in MissionWorkerBinding without failing the production factory type checks. Rc72ContextAwareDshTaskWorkerBridge is not proof that native N1–N10 paths invoke minimum context or token accounting.

## Independently implemented slice

- rc7_runtime/rc72_production_economy_wiring.py exposes explicit bind_production_model_economy; it instruments the real launcher instance and keeps its identity and type intact. The model boundary is the underlying command runner, so the context SHA is calculated from the final DSH prompt, including native N1 prefixes. R1 model usage is measured only when counters are actually observed; otherwise UNKNOWN.
- rc7_runtime/rc72_model_economy.py accepts BankCostWindowConfig, with an explicit Asia/Shanghai timezone. The default is 18:00–21:00 cost factor 0.1, >=21:00 quota-unlimited; changing a cost window cannot remove required work.
- rc7_runtime/rc72_economy_scheduler.py accepts the same configurable schedule. It may reorder or temporarily defer non-critical work, not mutate WorkItem identities, obligations or results.
- tests/test_rc72_production_economy_wiring.py and tests/test_rc72_cost_window_configuration.py exercise the simulated DSH command boundary, metering, UNKNOWN, deterministic misuse, quota pressure and schedule cases on Python 3.8 and 3.11.
- .github/workflows/rc7.2-economy-c10.yml runs this independent regression.

## A group — exact formal integration interface

At the native host worker-composition stage, before any assignment is launched:

    policy = BankCostWindowConfig.from_mapping(bank_local_schedule)
    economy = TokenEconomyService(truth, release_id=release_id, cost_window_config=policy)
    audit = TokenUsageAuditService(truth, release_id=release_id)
    # Load or configure SOFT economy targets for each Mission.
    for role, binding in workers.items():
        bind_production_model_economy(
            binding.launcher,
            economy=economy,
            usage_audit=audit,
            metadata_resolver=make_canonical_assignment_resolver(truth, role),
        )

The metadata resolver MUST use R1 canonical mission, WorkItem, Attempt, node, stage and role provenance, not infer lineage from prompt/model text. Supply actual workitem_id, node, stage and explicit model-call class, retry status, criticality and semantic cost. Missing budget or missing lineage must fail visibly; do not bypass accounting or mark work PASS.

Every new model/provider/Captain/Fresh Worker launcher needs a fresh binder call and shared canonical R1. A group must not remove Mission Factory's type checks or use a shadow ledger. The owner runtime must convert any model/process exception into incomplete or replanned work, not SUT defect or PASS.

## Product integration pending

1. Bind the hook for ALL native semantic and reviewer roles in the actual Mission Factory path; verify N1 native service and lease remain valid. Current independent tests only simulate the process boundary.
2. Consume minimum ContextEnvelope in the N2–N5 production prompt compilers and N8 RetryDelta in the retry producer, rather than only in the separate DshTaskWorkerBridge subclass.
3. Wire SafeExecutionBatchService and independent EvaluatorBatch where compatibility is proven, without collapsing per-WorkItem Attempt, oracle, evidence, gap or TestObligation denominator.
4. Propagate the same explicit bank policy into the live Scheduler and model ledger. Critical-path semantic work must continue at full price when mandatory.
5. Integrate quota/auth/timeout, model switching and Fresh Worker recovery with C07; no-progress loops must hard-block and replan without synthetic PASS.
6. Show separate Q7 MISSION_COMPLETION_STATUS and MODEL_ECONOMY_STATUS. UNKNOWN token usage must never become zero measured tokens.
7. Carry out same-scope ReleaseBatch baseline and optimized field trials with actual DSH usage, negative/positive testing, L1–L7, RCA/repair/regression, N8/N9/N10 and independent Evidence.

## Truth boundary

Repository CI cannot prove bank provider usage format, model quota, real token savings, an executed system test, N8/N9/N10 convergence or the offline install. Keep C10 COMPONENT_TESTED or PRODUCT_INTEGRATION_PENDING until factory calls, full regression and Field R1/Evidence establish the higher statuses. Never infer a saving percentage from simulated usage.
