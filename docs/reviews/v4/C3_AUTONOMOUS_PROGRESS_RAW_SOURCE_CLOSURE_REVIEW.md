# C3 Autonomous Progress / Recovery — Raw Source Closure Review

## Authority and identity

- ArchitectureBaseline: v7 / FROZEN / UNCHANGED
- Architecture Drift: NO
- Engineering branch: `work/v1.13.0-recovery-turnkey-validation`
- Reviewed exact head: `c7dd400db1374c408c2b291bdb5e1e1d93bc7357`
- C2 predecessor closure: `C2_SOURCE_AND_EXACT_HOST_CLOSURE_REVIEW = PASS`
- Windows qualification workflow: `V4 isolated implementation review`
- Workflow run: `34844747868`
- Windows job: `103977900158`
- Current-head source regression step: PASS
- Exact OpenCode 1.18.3 provider-boundary step: PASS
- Exact-host artifact: `10348240266 / v4-context-provider-boundary`
- Downloaded artifact ZIP SHA256: `1c0d578ac071332fa1ddf8387066908de8a07de6b5a8b2f3e4de02478ac5f51e`
- Exact host: official OpenCode 1.18.3 Windows x64
- Host asset SHA256: `68bc62930f6cb5755e0409aa9de0bb270a66ed2b8c9cf0c029e9f2287ed5486e`
- Exact-host evidence classification: `REAL_OPENCODE_HOST_LOCAL_RECORDING_PROVIDER_NO_REAL_MODEL`

## Decision

```ini
C3_SOURCE_AND_EXACT_HOST_CLOSURE_REVIEW = PASS
C3_ENGINEERING_COMPONENT_GATE = PASS
C3_ENGINEERING_COMPONENT = PASS / FROZEN

C3_REAL_AUTHENTICATED_MODEL_GATE = PENDING
C3_FINAL_INSTALLED_INTERACTIVE_GATE = PENDING
C3_BANK_FIELD_VALIDATION = PENDING

C4_WINDOWS_PROCESS_ISOLATION = OPEN / NOT_PROVEN / SEPARATE
ARCHITECTURE_CHANGE_REQUIRED = NO
HARD_DEPENDENCY_FAILURE_FOR_NEXT_INDEPENDENT_COMPONENT = NO
D_ENGINEERING_INDEPENDENT_WORK = AUTHORIZED_TO_START
```

This closure freezes the C3 engineering component: R1-driven autonomous Mission progress, bounded wake/recovery/replanning, caller/session-safe handoff, unresolved-side-effect fencing, and TEST_SUFFICIENCY convergence. It does **not** claim a real authenticated bank model, final installed interactive package, Windows process confinement, full F26 business-effect execution/reconciliation, or bank field readiness.

## Raw-source findings

### 1. Business progress is durable R1 truth, not heartbeat/session activity

C3 adds durable `ProgressStateRecord` and `QualityDecisionRecord` records to the existing `g2_1_session_control` R1 extension.

The controller derives a business cursor from semantic R1 events. Session creation, rotation identity, prompt receipt, heartbeat and other operational churn do not manufacture semantic business progress.

No second Mission runner, conversation database, or session-local progress truth is introduced.

### 2. User conversation is not the execution clock

The existing background Control Loop owns repeated progress ticks. `progress_once()` rebuilds from current R1 Mission/Plan/Task/Attempt state and advances independently of a user `continue`.

The current Windows regressions prove:

- background progress does not require user continuation;
- a nonterminal worker can be automatically continued;
- no-progress can open a governed replanning Planner;
- a semantic PlanRevision can hand off directly to the next governed Worker without a user or manual Scheduler call;
- Control Loop restart rebuilds from R1 without state loss.

### 3. Busy, retry, HumanGate/control, unknown delivery and business-side-effect states fence liveness

Autonomous wake/replan is fail-safe.

The activity barrier prevents new work when the Host reports busy/retry, when Mission control/Gate state blocks progress, or when a context dispatch is CLAIMED/UNKNOWN and cannot be reconciled.

C3 additionally fences unresolved `r1_4_tool_execution` business effects. An intent with no durable terminal/reconciled outcome, including UNKNOWN/ATTEMPTED states, blocks autonomous wake/replan rather than allowing a blind POST/DB/UI replay. Only the canonical ToolExecution reconciliation path releases that fence.

This is C3 liveness safety. Full business-effect intent/sent/receipt/oracle implementation remains the phase-D/F26 owner and is not falsely closed here.

### 4. Replanning is bounded and semantic

A stalled generation receives a durable `ProgressStateRecord` with a failure signature and business cursor.

The replanning path:

- creates/reuses a Router-owned Planner Session under the same Mission;
- sends one initial bounded ContextPack;
- permits at most one AUTO_CONTINUE at the same semantic cursor;
- rotates to a clean successor on repeated idle/no-progress;
- preserves replanning lineage across restart;
- rejects identity-only/new-revision churn as fake progress;
- resolves a stalled generation only after semantic business progress;
- caps repeated replanner failure and moves the durable generation to BLOCKED instead of retrying forever.

Current-plan-revision filtering prevents obsolete PlanRevision tasks from being woken after a successful replan.

### 5. Active Host tool calls are not destroyed by terminal cleanup

During a real Planner/Executor ToolContext call, Runtime may durably close a logical Planner Session before the OpenCode plugin process has returned.

C3 therefore separates durable Core closure from external Host deletion:

- the active Host caller is not deleted inside the still-running Planner tool call;
- background terminal reconciliation deletes only after Host activity is observably idle;
- unknown/busy/retry external activity defers cleanup.

The Windows regressions model in-flight Host calls as busy and prove the Planner can author a semantic replan without `STALE_CALLER` caused by premature cleanup.

### 6. PLAN_COMPLETE remains different from TEST_SUFFICIENT

The Scheduler may legitimately return `PLAN_COMPLETE` after all tasks in the current PlanRevision are terminal.

C3 does not complete the Mission from that state.

`progress_once()` routes `PLAN_COMPLETE` through the G4 TestObjectiveController:

- missing testing goal -> governed replan;
- missing measurement -> WAIT;
- G4 REPLANNING -> governed replan;
- any nonterminal quality state -> WAIT;
- unresolved completion blockers -> governed no-progress/replan;
- only `SATISFIED` or `COMPLETED_WITH_ACCEPTED_GAP`, with no completion blockers, can transition the Mission to TEST_SUFFICIENT completion.

Quality decisions are durably recorded and replayed by generation identity.

### 7. Exact OpenCode 1.18.3 ToolContext loop is closed

The current-head exact-host artifact reports:

```text
ALLOW_REACHES_PROVIDER                         PASS
BLOCK_1_PREVENTS_PROVIDER                      PASS
SUCCESSOR_1_BOOTSTRAP_REACHES_PROVIDER         PASS
BLOCK_2_PREVENTS_PROVIDER                      PASS
SUCCESSOR_2_BOOTSTRAP_REACHES_PROVIDER         PASS
WORKER_TWO_DURABLE_ROTATIONS                   PASS
PRIMARY_PLUGIN_BLOCK_REPLAYS_ON_CLEAN_SUCCESSOR PASS
PRIMARY_CRASH_AFTER_HOST_ACCEPT_READBACK       PASS
C3_REPLANNING_CONTEXT_REACHES_PROVIDER         PASS
C3_REPLANNER_PRESSURE_ROTATES_ON_EXACT_HOST    PASS
C3_REPLAN_REENTRY_DEDUPED_BY_R1_AND_HOST       PASS
C3_REPLAN_RESTART_REUSES_SUCCESSOR              PASS
C3_EXACT_HOST_PLANNER_TOOL_CALL_PERSISTS_PLAN  PASS
C3_EXACT_HOST_EXECUTOR_TOOL_CALL_COMPLETES_TASK PASS
C3_EXACT_HOST_TOOL_LOOP_SAME_MISSION            PASS
TWO_DURABLE_ROTATIONS                           PASS
```

The deterministic exact-host Tool Loop uses one Mission and real OpenCode 1.18.3 ToolContext:

```text
aitest-planner
  -> propose_plan
  -> durable PlanRevision
  -> Scheduler / Router
  -> aitest-executor Worker Session
  -> report_task_outcome
  -> Task SUCCEEDED
```

The final Executor Host ToolPart is `completed`. Its structured Runtime result is:

```text
status      = SUCCEEDED
next.status = PLAN_COMPLETE
Task        = SUCCEEDED
Mission     = ACTIVE
```

That last line is a positive invariant: exact-host Task completion does not equate Scheduler `PLAN_COMPLETE` with Mission completion.

The recording provider is deterministic and local. It proves the actual OpenCode host/plugin/ToolContext/provider boundary, not real bank-model semantics.

### 8. Closure oracle corrections did not weaken acceptance

Two false-red races were corrected during closure:

1. `ProgressState.phase=REPLANNING` is persisted before the initial Host bootstrap/provision bind completes. Tests now declare a replanner ready only when the R1 provision is BOUND and the Host Session/bootstrap are both observable.
2. R1 Task completion occurs inside the plugin tool process before OpenCode persists the final ToolPart output. Exact-host acceptance now waits for the real Host ToolPart to become terminal/completed and then structurally requires `output.next.status == PLAN_COMPLETE`.

These changes synchronize durable Runtime and Host clocks; they do not accept weaker product behavior.

## Regression evidence

Current Windows source/pressure qualification on this construction line proves, among other checks:

```text
background_no_progress_creates_governed_replanner       PASS
background_process_rotates_without_agent_observe        PASS
background_progress_does_not_require_user_continue      PASS
background_replan_remains_same_mission_truth            PASS
background_worker_auto_continue_precedes_replan         PASS
control_loop_restart_rebuilds_from_r1_without_state_loss PASS

background_reaches_replanner_without_user_continue      PASS
replanner_host_tool_authors_semantic_plan_revision      PASS
runtime_handoff_dispatches_diagnosis_without_scheduler  PASS
background_continues_new_task_without_user_or_scheduler PASS
stalled_generation_resolves_on_semantic_revision        PASS
```

The existing autonomous-progress and PLAN_COMPLETE convergence regression suites additionally cover busy/retry barriers, HumanGate/control precedence, bounded wake/replan budgets, unresolved side-effect fencing, semantic no-change rejection and quality convergence.

## Residual gates carried forward

### C3 real authenticated model

A real authenticated model normal-entry run remains mandatory before final L4 qualification. The deterministic recording provider cannot prove model semantic competence.

It must prove a user can give one testing goal and the actual Planner/Workers make governed progress across multiple Sessions without repeated user continuation.

### Final installed interactive Windows package

The final no-admin installed package, standard-user Git Bash launch, visible TUI follow/recovery and exact installed-byte identity remain L3 work.

### C4 Windows process isolation

The current `windows-isolation` job remains separately red / NOT_PROVEN. C3 does not hide or reinterpret it.

Dangerous GeneralWork/RuntimeDiagnosis terminal execution that depends on Windows confinement remains fail-closed until C4 is proven.

### Phase D / F26

C3 closes the autonomous **fence** around unresolved side effects. Phase D still owns full per-step business-effect intent/sent/receipt/UNKNOWN/reconcile semantics and real API/UI/DB/CAT oracle/evidence closure.

## Next engineering route

C3 source/exact-host engineering is frozen. Do not reopen it for unrelated C4 or phase-D findings unless evidence proves a C3 frozen invariant is false.

Proceed in parallel:

1. continue C4 Windows process-confinement qualification/repair as its separate open gate;
2. start phase D engineering for structured source/requirements/change intelligence, standard cases, oracle/evidence and full business-effect reconciliation;
3. carry C3 real-model and final-installed gates to the final L4/L3 qualification rather than blocking independent phase-D construction.
