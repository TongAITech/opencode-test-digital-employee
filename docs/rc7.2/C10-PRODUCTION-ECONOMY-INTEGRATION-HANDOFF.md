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


## 2026-11-04 follow-up: Q7 process-count truth and production ingress corrections

Production \`rc72_mission_cli.py\` now retains the actual
\`bind_release_batch_model_economy(...)\` service returned by the native
ingress and uses it for the Q7 dual-status report. The earlier draft's missing
assignment would have raised \`NameError\` at runtime; this is repaired with a
real CLI integration regression. A syntactically invalid multiline
same-WorkItem context guard was also corrected.

Model-call admission is **not** proof of a launched DSH process. The
C10-owned \`rc72_token_call\` receipt now records
\`process_outcome=NOT_STARTED|RETURNED|RAISED|UNKNOWN\`, including R1 replay
defaults for historical records. The native command runner records \`RETURNED\`
only when it returns, and \`RAISED\` when it throws. Summary and CLI expose
nullable \`DSH_PROCESS_INVOCATIONS\`, explicit
\`DSH_PROCESS_INVOCATION_COUNT_STATUS\`, and a separate launch-error count.
A direct/synthetic \`admit_call\` or historic R1 token row without native
process truth yields \`UNKNOWN\`, not a fictitious launched process. This
does **not** prove distinct provider inference rounds, which remain UNKNOWN
pending actual in-bank DSH event contract and Q7 Field evidence.

The above are committed engineering corrections, **not yet verified at the
same source HEAD by queued CI**; do not upgrade C10 status until CI and
negative/native recovery tests pass.


## 2026-11-04 production reference-envelope provenance (not context-saving proof)

\`rc72_native_context_projection.py\` now composes a real
\`ContextEnvelopeBuilder\` envelope from canonical R1 \`rc7_task\` parent refs,
worker \`input_refs\` (important for independent reviewer candidates), and
canonical Gap refs. The product ingress attaches the projection to native
producer/reviewer metadata before the real final \`--json\` command is metered.

When a real \`rc72_retry_context\` receipt exists for the exact
WorkItem/Attempt, an \`OBSERVED\` \`RETRY_DELTA\` projection references the
previous Attempt summary + explicit Gap + changed Evidence/dependencies;
\`UNKNOWN\` retains the unchanged canonical refs instead of silently shrinking
mandatory test context. Full-context retries must carry an explicit reason.
No synthetic N8 parent Attempt or Gap is invented.

The C10-owned \`rc72_token_call\` R1 record now carries
\`context_envelope_id\`, \`context_envelope_sha256\`, \`context_mode\`, ref
counts, parent Attempt ID and
\`context_projection_status=REFERENCE_ONLY\`. Importantly
\`context_projection_applied_to_prompt=false\` remains **false**: the
source-approved N1–N5 native prompts are deliberately unchanged until the
actual prompt composer is proven to consume the bounded projection without
losing source/Oracle/negative-test/coverage requirements. Reference counts are
not a measurement of savings. Token-summary
\`verified_context_savings_bytes=null\` and
\`native_minimal_prompt_proven_calls=0\` remain truthful. The previously named
\`context_reuse_factor\` denotes *observed duplicate input bytes*, **not**
saved tokens; the clearer \`context_duplication_factor\` is now also emitted.

**Remaining owner integration:** A's real N8 and all live N2–N5 independent
semantic prompt authors need to take these canonical refs as the *actual*
prompt hydration source, and return real output/evidence per WorkItem. Batch
shared model-call dispatch must still verify independence and raw evidence.
No C10 full closure or economy savings claim is permitted until those product
routes, same-HEAD CI, and Field evidence pass.


## 2026-11-04 actual lossless final-DSH-prompt optimization

`rc72_lossless_prompt_compaction.py` is now executed inside the production
DSH process wrapper, **after** the approved native launcher has assembled
its final prompt (including source-read/auth prefix) and **before** the
actual `command_runner` invocation and R1 prompt SHA metering.

The transformer only rewrites a strict terminal
`Context={...} [RequiredShape={...}]` JSON suffix that it can decode
unambiguously as JSON *objects*, without duplicate keys, nonfinite
values, trailing prompt text or altered business fields. It uses compact
JSON separators while preserving insertion-ordered object fields, every
string value, every required case/Oracle/Gap/source/tool ref, all array
ordering, the native instruction prefix and the RequiredShape schema.
Anything uncertain stays byte-identical, without an inference or omission.

C10 token-call truth now stores:
`prompt_original_bytes`, `context_bytes` (actual bytes passed to DSH),
`prompt_serialization_saved_bytes`, `prompt_compaction_status`, and the
SHA of the **actual compacted final prompt**. Summary records only byte
reductions on native process calls that actually RETURNED; preflight
admission alone does not prove model execution. The real observed output
can establish **prompt serialization bytes reduced**, *not* saved
provider Token counts: `verified_prompt_token_savings=null`, and
`verified_context_savings_bytes=null` until a real
baseline/optimized same-scope field measurement and true contextual
hydration proof exist.

This first safe lexical optimization does **not** prove the frozen
`ContextEnvelope` is already the native prompt-hydration source,
does not batch independent WorkItems into one model inference, and does
not replace R1 Attempt/Evidence/Defect authority. Those remain separate
construction and qualification gates.


## 2026-11-04 continuation: nested tool usage truth + executable compaction tests

A nested CAT/MCP/CodeGraph tool result in a DSH final JSON event may
carry counters named `input_tokens` or `total_tokens`. These are **not**
model provider inference counters. All three source pathways now share
`rc72_provider_usage_filter.py`: the direct native runner usage extractor,
the independent R1 `TokenUsageAuditService` parser and the JSONL
model-response signal detector. Tool/MCP subtrees are excluded even when
embedded in a final response alongside real provider usage. Real provider
usage outside those subtrees remains measurable; tool-only data must be
UNKNOWN/no model signal, never fake MEASURED model tokens.

Source tests now cover tool-only nested final output, mixed provider +
tool events, native command metering, valid/invalid/duplicate/nonfinite
JSON prompt suffixes, non-ASCII content, malformed Unicode surrogates and
cold R1 replay of the optimized actual prompt SHA/byte telemetry.
The workflow compiles `rc7_release` as well as runtime and uses a
branch-scoped GitHub Actions concurrency key to cancel stale C10 checks.

An **isolated, copied-algorithm smoke** was performed on a synthetic N4
`Context`+`RequiredShape` example and confirmed JSON equality with
18 fewer input bytes; this is NOT a same-HEAD source-suite CI result
and does NOT imply a provider tokenizer saving percentage.

Current release CLI output includes
`LOSSLESS_JSON_COMPACTED_CALLS`,
`VERIFIED_PROMPT_SERIALIZATION_SAVED_BYTES`,
`VERIFIED_PROMPT_TOKEN_SAVINGS=null` for truthful Q7 reporting.
The actual bank field comparison, ContextEnvelope-driven hydration,
true single-call batch dispatch, N8/N9/N10 end-to-end execution and
same-HEAD multi-platform acceptance remain open.


## 2026-11-04 C10 new construction: actual RetryDelta DSH hydration + shared batch dispatch APIs

### Native RetryDelta applied to actual final DSH prompt

\`rc72_native_delta_prompt.py\` now replaces *only*
\`Context.input_refs\` in the final authorized DSH command with a real
\`ContextEnvelopeBuilder\` retry delta (parent summary, Gap and changed
Evidence/dependency refs) when **all** of the following hold: R1 child
WorkItemAttemptBinding exists with RESOLVED MissionNode and exact parent
Attempt; R1 RetryContext observation is OBSERVED with matching child
Attempt and assignment ID; role is a producer, not an independent reviewer;
the Context object contains the exact Mission and WorkItem ID; every old
input_ref belongs to canonical source/assignment refs; a real prior summary
appears in the new effective refs; resulting UTF-8 prompt is smaller; the
rest of Context, every business Case/Oracle/parent obligation, RequiredShape,
auth/tool instructions remain unchanged.

If any item fails, the original input refs are retained. No new model
assumption is treated as a signed retry; no Task, TestObligation or Attempt
business state changes. C10-only R1 token-call receipts now differentiate
\`REFERENCE_ONLY\` from \`NATIVE_RETRY_DELTA_VERIFIED\`, with
\`context_projection_applied_to_prompt=true\` and
\`native_retry_delta_saved_bytes\` only after actual substitution.
\`observed_native_retry_delta_prompt_saved_bytes\` is *input bytes*, NOT
provider Token savings. This does NOT close the A-owned full N8
diagnosis→repair→fresh Attempt→N9 regression→N10 convergence orchestration.

### One actual native DSH process per multi-WorkItem semantic ExecutionBatch

C10 adds these dedicated interfaces, instead of altering A-owned Mission
Factory / ReleaseBatchDriver:

- \`rc72_native_shared_batch_composition.compose_native_batch_services\`:
  validates two **different** real native DSH launchers, the same Mission
  R1 store/release, and real model token auditors; installs both native
  command-boundary meters before dispatch, fail-closes prior to partial binding.
- \`rc72_native_shared_batch.NativeSharedExecutionBatch.dispatch\`:
  requires an actual host-issued \`execution-batch:<batch_id>\` WorkerAssignment,
  exact authorized ContextEnvelope refs, approved tool list, explicit
  \`SEMANTIC\` R1 classification for EVERY member, and an admitted
  SafeExecutionBatch receipt whose independent WorkItem/ETU/Case/Attempt IDs
  belong to one resolved MissionNode. It makes ONE real
  \`DshHeadlessWorkerLauncher.execute\` call, so one corresponding model-call
  receipt (named \`EXECUTION_BATCH:<batch_id>\`) exists for all members.
  Each member must cite a **distinct actual** \`dsh-event://tool-call/N\`
  observed by that native DSH invocation, otherwise its output is rejected.
  Only an additive R1 \`rc72_native_batch_candidate\` with state
  \`UNVERIFIED\`, signed raw JSONL proof, model call ID and independent member
  identities is recorded, never fabricated business PASS.
- \`rc72_native_shared_batch_review.NativeSharedEvaluatorBatch.review\`:
  requires a separate approved \`evaluation-batch:<batch_id>\` scoped
  WorkerAssignment, EXACT producer raw JSONL file as minimal input, different
  worker and actual DSH session, and a second actual model-call receipt
  (\`EVALUATOR_BATCH:<batch_id>\`). Each original member gets an independent
  \`SUFFICIENT_CANDIDATE / INSUFFICIENT / UNKNOWN\` review. It records only
  \`UNVERIFIED_INDEPENDENT_REVIEW\`, not a business PASS or release gate.

The proof distinguishes: **one model call for N WorkItems** versus N
independent business WorkItems/Attempts. The model cannot turn a missing
N7 actual tool, Oracle, cleanup, repair, independent evidence verification
or N9 regression into PASS. On any invalid/missing member or forged tool
call ref, no candidate/review is recorded; R1 preserves the admitted batch
and failed attempt for fail-safe retry with a NEW authorization. Cold R1
replay and idempotent resume are covered by tests.

### Product integration still required: do not call this finished C10

The actual N7 product entrypoint must acquire **fresh batch and reviewer
DSH WorkerAssignments** with real authority / tools and invoke these
services only after formal N7 binding/leases are granted; the reviewer
assignment cannot be minted until the real producer raw proof exists.
Then **existing N7 ExecutionEvidenceService and deterministic Oracle
and independent Evidence Review** must consume the member observations
and independently establish actual results. No direct bridge from
\`UNVERIFIED\` model candidate to canonical PASS exists or should exist.
The A-group N8/N9/N10 Mission controllers must also exercise the real
retry/repair/reexecution loop. None of those shared A-owned source files
have been edited in this C10 branch.

Same-HEAD Python 3.8/3.11 + Ubuntu/Windows CI is still required; bank
provider runtime, tool permission and equal-scope Token baseline
measurements remain FIELD_PENDING. No schedule/date or token savings
percentage can be justified from isolated contract tests alone.


## 2026-11-04 C10 additional hardening — actual batch model evidence, tool-first, cold replay

The model-batch services are now composed through
\`rc72_native_shared_batch_composition.compose_native_batch_services\`:
both native launchers and auditors are validated **before either is bound**,
so a missing/incorrect reviewer cannot leave a half-instrumented execution
worker. A real host-issued \`execution-batch:<batch_id>\` lease must cover
EXACTLY the ContextEnvelope's shared and member refs. Every member must
have an explicit R1 \`rc72_work_schedule_semantics.execution_mode=SEMANTIC\`;
deterministic or hybrid work remains tool-first and is not silently
merged into a model batch. The native batch execution candidate and
independent reviewer each require exactly one corresponding
\`rc72_token_call\` with \`process_outcome=RETURNED\` and persist
\`token_call_id\` in R1, separate from the member WorkItem IDs.
A model admission without a returned native process is NOT batch evidence.

Per-member candidate tool refs must occur in the real DSH tool-call event
stream and be disjoint across members. A forged/missing member, shared
tool ref, wrong Attempt, unapproved scope, repeated prior model attempt
or claimed PASS fails closed. Reviewer inputs are restricted to exactly
the producer's real raw DSH JSONL evidence ref, and its worker/session
must be fresh. Cold replay and duplicate assignment resume do not
create another model call. The real canonical business N7
\`execution_attempt\` and \`assertion\` entities remain completely
untouched.

**R1 replay before any new Mission dispatch:** additively install all
C10 token-budget, TokenUsageAudit, cost schedule, N8 RetryContext,
SafeExecutionBatch, native batch candidate/reviewer projection types
before opening a previously used \`TruthRuntime(path)\`. The formal
\`rc7_release.rc72_mission_cli\` now calls
\`install_rc72_economy_replay_bindings()\` before opening the ledger, even
for \`status\`. The historical UNKNOWN model usage stays UNKNOWN.

**Integration / qualification remains OPEN:** A's actual formal N7
ExecutionPreparation/NativeTool/DeterministicOracle/EvidenceReview
pipeline must obtain the real host-issued batch and reviewer leases and
call the C10 services, then independently consume each member evidence
under the existing N7 case/ETU/Attempt gates. The services intentionally
DO NOT turn semantic candidates or reviewer opinions into PASS. A must
also drive actual N8 parent→child retries and N9/N10 convergence. An
in-repo simulated native-command contract test demonstrates the one-call
batch boundary but is NOT proof of a successful in-bank DSH model
session. CI and Field evidence remain mandatory.


## 2026-11-04 C10 formal N7 closure bridge (source implementation, not Field PASS)

A new C10-only formal reconciliation module,
rc72_native_batch_formal_n7.NativeBatchFormalN7Reconciler, accepts a
REAL N7PipelineService instance, the source SafeExecutionBatch receipt,
the single native producer candidate and the independent reviewer receipt.
It performs a read-only A-owned
AcceptedObligationExecutionProof(pipeline).audit(release_batch_id=...)
before writing SafeExecutionBatch.RESULTS_RECORDED. That audit requires
accepted N7 full source Case denominator, all canonical obligations,
tool execution, independent N7 reviewer, captured evidence, cleanup,
finalized Case/Attempt lifecycle and actual deterministic Oracle truth.
The bridge then rechecks every original WorkItem+Attempt+Case identity
against the accepted N7 evidence bundle; each execution_attempt PASS,
assertion.passed, real tool_call_refs and evidence_refs must exist.
Only the ORIGINAL canonical N7 dispatch artifact is used as each member's
actual_result_ref: NEVER a native model candidate or a semantic opinion.
If one member/reviewer/evidence fails, the entire C10 batch result
reconciliation remains HOLD, with no invented N7 PASS.

The existing production C10 NativeBatchServices composer exposes both
reconcile_accepted_n7() and drive_formal_n7(). The latter invokes ONE
approved native ExecutionBatch DSH call, asks the HOST (not the model)
to issue a fresh reviewer WorkerAssignment after producer raw output
exists, invokes ONE separate native EvaluatorBatch DSH call, then
calls the REAL N7PipelineService.complete(release_batch_id=...) and
reconciles only if that returns actual N7_PASS. Otherwise returns HOLD.
The host remains responsible for real batch/reviewer lease authority,
actual worker/tool configuration, fresh session, bank SUT readiness and
N8→N9→N10 recovery. This adds an explicit callable integration
path without editing A-owned Mission Factory, N7PipelineService,
ReleaseBatchDriver, canonical TestObligations or the shared R1 schema.

Tests include negative incomplete-review HOLD, two native DSH boundary
calls followed by stubbed formal N7 HOLD, and a clearly labeled
UNIT-ONLY accepted-audit stub to exercise member-wise result receipt
logic. The stub is NOT evidence of an actual accepted N7 run. No
component/CI-only result may be promoted to BANK_FINAL.
