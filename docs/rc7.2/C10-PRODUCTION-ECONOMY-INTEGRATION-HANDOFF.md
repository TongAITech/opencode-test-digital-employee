# RC7.2 C10 — Product economy integration handoff

Status: PARTIAL — CANONICAL CLI PRODUCT INGRESS CODE IMPLEMENTED; FULL CI, N8–N10 AND FIELD MEASUREMENT PENDING.
This document does not override frozen RC7.2 contracts 02, 04, 09 or 10.

## Audit finding

The native product composer in rc7_runtime/rc72_mission_factory.py requires DshHeadlessWorkerLauncher instances and requires NativeN1ReadDshLauncher for the N1 role. Existing TokenMeteredDshLauncher and Rc72TokenUsageLauncherProxy are wrappers, so they cannot be substituted directly in MissionWorkerBinding without failing the production factory type checks. Rc72ContextAwareDshTaskWorkerBridge is not proof that native N1–N10 paths invoke minimum context or token accounting.

## Independently implemented slice

- rc7_runtime/rc72_production_economy_wiring.py exposes explicit bind_production_model_economy; it instruments the real launcher instance and keeps its identity and type intact. The model boundary is the underlying command runner, so the context SHA is calculated from the final DSH prompt, including native N1 prefixes. R1 model usage is measured only when counters are actually observed; otherwise UNKNOWN.
- rc7_runtime/rc72_model_economy.py accepts BankCostWindowConfig, with an explicit Asia/Shanghai timezone. The default is 18:00–21:00 cost factor 0.1, >=21:00 quota-unlimited; changing a cost window cannot remove required work.
- rc7_runtime/rc72_economy_scheduler.py accepts the same configurable schedule. It may reorder or temporarily defer non-critical work, not mutate WorkItem identities, obligations or results.
- tests/test_rc72_production_economy_wiring.py and tests/test_rc72_cost_window_configuration.py exercise the simulated DSH command boundary, metering, UNKNOWN, deterministic misuse, quota pressure and schedule cases on Python 3.8 and 3.11.
- .github/workflows/rc7.2-economy-c10.yml runs this independent regression.

## Formal native product ingress now installed

The real command-line ReleaseBatch Mission entry in rc7_release/rc72_mission_cli.py now invokes bind_release_batch_model_economy **before** create_mission_driver whenever command=run. It binds all eleven native role launchers, uses the same canonical R1 store, and preserves the concrete launcher types and N1 native gate. The parser accepts an optional trusted --economy-config JSON for explicit Shanghai windows / soft budget targets. status and mirror-check remain LLM-free and do not create economy call receipts. The R1 resolver supports task-scoped producers, native N1 worker assignment, and independent reviewers traced through approved artifacts.

The command-line run output now separates MISSION_COMPLETION_STATUS and MODEL_ECONOMY_STATUS and keeps ACTUAL_TOTAL_TOKENS null if usage is not fully observed. This is source integration, not Field evidence or proven token savings.

The same explicit bank-local policy is now validated and persisted in the canonical rc72_token_budget R1 artifact. Every RC72EconomyClosedLoopControlPlane instance reads it on construction, including cold replay. A legacy budget lacking this field is version-migrated without rewriting its existing soft token targets; an explicit contradictory operator policy fails closed before any provider launcher is bound. Context-loop hard guards are now scoped to the same canonical WorkItem; unrelated mandatory WorkItems sharing a context fingerprint remain executable.

A DSH process launch is **not** one confirmed provider inference. Accounting now distinguishes dsh_process_invocations from nullable provider_inference_call_count, with provider_inference_call_count_status=UNKNOWN until the bank DSH JSONL event grammar proves every inference. The real CLI Q7 view invokes field_qualification; it remains HOLD while this count is UNKNOWN even when a source-level measured-token fixture reports PASS. This is an intentional non-fabrication boundary, not a hard budget stop for required test work.

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

1. The CLI run product ingress is source-wired. A group must verify its real controlled Mission Factory + native N1 admission end-to-end, and any alternate embedded/API factory entry must call the same binder before dispatch (CLI-only wiring does not cover these entrypoints).
2. Consume minimum ContextEnvelope in the N2–N5 production prompt compilers and N8 RetryDelta in the retry producer, rather than only in the separate DshTaskWorkerBridge subclass.
3. Wire SafeExecutionBatchService and independent EvaluatorBatch where compatibility is proven, without collapsing per-WorkItem Attempt, oracle, evidence, gap or TestObligation denominator.
4. Propagate the same explicit bank policy into the live Scheduler and model ledger. Critical-path semantic work must continue at full price when mandatory.
5. Integrate quota/auth/timeout, model switching and Fresh Worker recovery with C07; no-progress loops must hard-block and replan without synthetic PASS.
6. The CLI now shows separate Q7 MISSION_COMPLETION_STATUS and MODEL_ECONOMY_STATUS. Provider inference counts remain UNKNOWN; obtain actual bank DSH per-inference events before granting economy PASS. UNKNOWN token usage never becomes measured zero.
7. Carry out same-scope ReleaseBatch baseline and optimized field trials with actual DSH usage, negative/positive testing, L1–L7, RCA/repair/regression, N8/N9/N10 and independent Evidence.

## Truth boundary

Repository CI cannot prove bank provider usage format, model quota, real token savings, an executed system test, N8/N9/N10 convergence or the offline install. Keep C10 at PRODUCT_INGRESS_CODED / ENGINEERING_VERIFICATION_PENDING until full same-HEAD regression and Field R1/Evidence establish the higher statuses. Never infer a saving percentage from simulated usage.


## Working-day quota correction — 2026-11-04 (C10)

**Quota limits apply only to Shanghai-calendar working days.** On non-working
days, the entire 00:00–24:00 Asia/Shanghai local day is unrestricted:
- Saturday/Sunday default to non-working days (no quota, cost factor 0).
- A weekday listed in \`non_working_dates\` (e.g., an officially declared
  statutory holiday) is unrestricted for the whole day.
- A Saturday/Sunday listed in \`makeup_work_dates\` (officially adjusted
  compensatory workday) is **working**, and follows the ordinary workday
  schedule: before 18:00 full-rate quota; 18:00–21:00 10:1 quota; from 21:00
  unrestricted.
- Local date/time is always derived from an aware datetime converted to
  Asia/Shanghai; the worker machine's local timezone must not be consulted.

Bank administrators supply an *authoritative, current working calendar* in the
existing trusted \`--economy-config\` JSON input, under \`bank_cost_window\`:

\`\`\`json
{
  "bank_cost_window": {
    "timezone_name": "Asia/Shanghai",
    "normal_end_hour": 18,
    "discount_end_hour": 21,
    "normal_factor_millis": 1000,
    "discount_factor_millis": 100,
    "unlimited_after_discount": true,
    "post_discount_factor_millis": 0,
    "non_working_dates": ["2026-01-01"],
    "makeup_work_dates": []
  }
}
\`\`\`

**The example is not a complete 2026 calendar.** The code does not guess
official statutory holidays or adjusted workdays. Operators must maintain
both lists from the approved bank / statutory calendar for the whole planned
execution period and update them on policy changes. Without those overrides,
only the regular Saturday/Sunday weekend rule is known. The schema requires
canonical \`YYYY-MM-DD\` dates, deduplicates by rejection, rejects conflicts
between working/non-working overrides, serializes stable sorted lists, and
persists the selected schedule in canonical R1. Cold recovery without a new
operator policy reuses the exact approved R1 schedule, including holidays and
adjusted workdays. An explicit, validated calendar update **version-increments**
the R1 budget while preserving existing soft targets and every required test;
it does not block Mission execution merely due to quota-policy drift. Invalid
or contradictory date lists still fail validation before dispatch.

**Acceptance truth:** this changes *only* quota-window classification and
economic scheduling/admission telemetry. It must never remove WorkItems,
TestObligations, L1–L7 cases, Evidence, independent review, RCA, repair or
regression. It does not prove a provider actually grants free quotas, nor does
it authorize fictitious Token-savings percentages. Check bank provider billing
against the configured dates in Field before declaring bank quota qualification.
