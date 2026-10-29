# RC7.2 Construction Contract

Status: FROZEN CONSTRUCTION CONTRACT — AMENDED BY `09-MISSION-COMPLETION-FIRST-MODEL-ECONOMY-DESIGN.md`

## 1. Contract purpose

This document converts the RC7.2 design into enforceable implementation obligations. A phase is not complete because code exists or an Agent reports completion; it is complete only when the required code, tests, migration, evidence and qualification are present.

## 2. Construction invariants

The following are MUST NOT CHANGE without a prior design-baseline commit:

1. Release Batch is the business root and N10 convergence scope.
2. Canonical asset hierarchy is ReleaseBatch -> Requirement -> SST -> TestObligation -> L1-L7 -> Case -> ETU -> WorkItem -> Attempt -> Evidence.
3. N1-N10 are persisted runtime state-machine nodes, not Agent aliases.
4. R1/Evidence is canonical truth; Session is disposable.
5. Executor does not silently repair upstream analysis/design/data deficiencies.
6. Worker remains STRICT; temporary authority is lease-based.
7. Coverage is feedback/convergence, not the test-asset root.
8. Browser write ownership is exclusive.
9. Provider failures are infrastructure conditions, not SUT failures.
10. No PASS without evidence.
11. **Mission completion and test sufficiency outrank model/token economy. Model economy may optimize HOW/WHEN/CONTEXT/BATCH/MODEL, but MUST NOT reduce WHAT MUST BE TESTED, delete mandatory TestObligations, suppress required L1-L7 work, fabricate PASS, or converge N10 to save quota.**
12. **Business task granularity, scheduling granularity, ExecutionBatch granularity and model-call granularity are distinct. Fine ETU/WorkItem decomposition MUST NOT imply one fresh full-context LLM call per WorkItem.**

## 3. Required implementation phases

### Phase 0 — RC7.1 Reality Baseline

Deliverable: `docs/rc7.2/RC7.1-REALITY-BASELINE.md`.

Must capture current code/runtime truth for:

- AgentTeams roles and session lifetime;
- R1 schemas and event stream;
- current N1-N10 representation;
- current L1-L7 routing;
- Libra coverage loop;
- Browser/BSK ownership;
- model auth/failover behavior;
- Field Full vs Worker STRICT authority;
- current eight GAPs;
- known fake/partial/field-unverified paths.

Exit gate: baseline reviewed against current branch HEAD and field evidence. No architecture refactor before this baseline exists.

### Phase 1 — Canonical Domain Model

Implement persisted schemas/migrations/APIs/tests for:

- ReleaseBatch enhancements if needed;
- MissionNode;
- NodeDelivery;
- NodeGate;
- Gap;
- BackEdge/Transition;
- TestObligation;
- ETU;
- WorkItem/Attempt linkage and lifecycle;
- resource/capability lease references.

Exit gate: schema migration, backward compatibility strategy and repository-level contract tests PASS.

### Phase 2 — N1-N10 Runtime State Machine

Implement node lifecycle, gate enforcement, semantic transitions, back-edge persistence and stale propagation.

At minimum prove:

```text
N7 -> N8 -> N3
N7 -> N8 -> N4
N7 -> N8 -> N5
N7 -> N8 -> N6
N7 -> N8 -> N9
```

Exit gate: transitions are code/runtime state, not prompt-only conventions.

### Phase 3 — Sufficiency Gates

Implement enforceable gates for N2-N6.

N7 dispatch MUST fail closed if the active ExecutableContract references an upstream delivery that is missing, stale or not PASS.

Exit gate: negative tests demonstrate N7 cannot run with missing code constraints, Oracle, data readiness or executable readiness.

### Phase 4 — Adaptive Task Decomposer

Implement TestObligation -> ETU decomposition, split/merge/reprioritize and coverage-gap routing according to `04-ADAPTIVE-TASK-DECOMPOSER-CONTRACT.md`.

Exit gate: deterministic fixtures demonstrate Requirement/SST lineage is preserved and uncovered code cannot directly create an untraceable TestCase.

### Phase 5 — Fresh Worker Runtime

Implement worker creation, attempt binding, session closure/rotation, evidence checkpoint and fresh reviewer policy.

Exit gate: two ETUs use distinct worker sessions while sharing the same mission truth; deleting/losing a worker session does not lose completed work.

### Phase 6 — Diagnosis and Recovery

Implement independent N8 diagnosis and failure classification/routing.

Exit gate: Analysis/Design/Data/Executable gaps route to correct nodes and generate new downstream versions/attempts instead of executor-side mutation.

### Phase 7 — Capability and Resource Runtime

Implement CapabilityBroker, temporary lease amendment/delegation, BrowserPool/BrowserLease, DataLease and model failover.

Exit gate: browser contention, capability gap and provider quota are handled without Mission corruption or Full Access leakage.

### Phase 8 — Coverage Convergence

Move Libra integration to coverage feedback/convergence semantics. Implement CoverageGap -> CodeSlice -> Requirement/SST -> TestObligation -> GapReason mapping.

Exit gate: 92% target may influence priority and back-edge routing but cannot create orphan coverage cases.

### Phase 9 — Journey Teaching

Implement Teaching capture, Journey Compiler, Candidate, Replay, Benchmark, Human Review and official L4/L5 Journey asset consumption.

Exit gate: official Journey has ReleaseBatch/Requirement/SST/Obligation lineage and can be replayed by a worker with isolated browser ownership.

### Phase 10 — Mission-Completion-First Model Economy

Implement the design baseline in `09-MISSION-COMPLETION-FIRST-MODEL-ECONOMY-DESIGN.md` without changing the business task root or N1-N10 semantics.

Required slices:

```text
A. R1 model-call usage + decision telemetry
B. explicit bank-local cost-window policy
C. soft budget/warning/replan semantics
D. hard waste guards only for invalid/duplicate/no-progress behavior
E. deterministic-first execution/evaluation
F. minimum ContextEnvelope + retry-delta behavior
G. ExecutionBatch/EvaluatorBatch with per-WorkItem lineage
H. Q7 dual outcome: mission completion + model economy
```

Exit gate requires repository tests proving token/cost pressure cannot delete or silently block mandatory test scope solely for economy, while deterministic misuse and no-progress repeated-context loops remain fail-closed.

Field savings are not complete until equivalent real ReleaseBatch scope is measured in-bank.

## 4. Required commit discipline

Do not land the entire architecture in one giant commit.

Each phase should normally contain separate logical commits for:

```text
schema/migration
runtime/core
adapters/integration
tests/qualification
docs/checkpoint
```

Every commit message/body or associated construction checkpoint must identify:

```text
CONTRACT_CLAUSES_IMPLEMENTED
CONTRACT_CLAUSES_REMAINING
TEST_EVIDENCE
FIELD_EVIDENCE_STATUS
KNOWN_DEVIATIONS
```

Large commits that combine unrelated architectural changes are rejected unless a clean technical reason is documented.

## 5. Required construction checkpoint ledger

Maintain `docs/rc7.2/CONSTRUCTION-PLAN.md` during implementation.

Every checkpoint entry must contain:

```text
head_sha
phase
clauses
status: NOT_STARTED | IN_PROGRESS | CODE_COMPLETE | CI_PASS | FIELD_VALIDATED | BLOCKED
commits[]
ci_runs[]
evidence_refs[]
field_evidence
open_gaps[]
next_atomic_step
```

The ledger is a status record, not an authority over this contract.

## 6. Mandatory contract tests

### CT-01 ReleaseBatch lineage

Every canonical Case traces to ReleaseBatch -> Requirement -> SST -> TestObligation.

### CT-02 N3 insufficient

Missing DB/API/validation/graph evidence causes N3 gate failure and blocks dependent execution.

### CT-03 N4 incomplete case

Missing Oracle/precondition/expected/evidence requirement causes N4 failure.

### CT-04 N5 missing data

Unresolved required data causes N5/N6 failure and blocks N7.

### CT-05 Analysis back-edge

N7 failure -> N8 ANALYSIS_GAP -> N3; affected downstream assets become STALE.

### CT-06 Design back-edge

N8 TEST_DESIGN_GAP -> N4 and new case/delivery version.

### CT-07 Data back-edge

N8 TEST_DATA_GAP -> N5 and new/verified DataRef.

### CT-08 Fresh worker

Different ETUs get different session identities under the same mission truth.

### CT-09 Session loss

Completed evidence/work state remains recoverable after worker session removal.

### CT-10 Captain handoff

A fresh Captain resumes the same Mission without creating duplicate Mission/Team or repeating completed WorkItems.

### CT-11 Browser isolation

AuthKeeper and L4/L5 workers have distinct BrowserLease write owners; conflicting write access is rejected.

### CT-12 Provider quota

Provider quota/auth failure does not fail the Mission; same WorkItem can resume in a fresh approved worker/model assignment.

### CT-13 Worker capability request

STRICT worker missing capability produces a request and temporary scoped lease/delegation, never Captain credential inheritance.

### CT-14 Coverage discipline

Uncovered code without Requirement/SST/Obligation mapping cannot directly create a canonical TestCase.

### CT-15 Fresh review

Independent reviews use fresh reviewer sessions and canonical delivery/evidence inputs.

### CT-16 Executor boundary

Executor encountering an upstream deficiency emits failure evidence and N8 routing; it may not mutate N3/N4/N5 canonical assets directly.

### CT-17 R1 consistency

NodeDelivery cannot be committed as complete if MissionNode/WorkItem/Attempt/lease state contradicts the claimed state.

### CT-18 N10 convergence

Coverage target alone is insufficient to mark ReleaseBatch CONVERGED when mandatory Requirement/SST/Obligation/L1-L7/defect/evidence gates fail.

### CT-19 Mission completion outranks token target

Crossing a configured model/token warning threshold MUST NOT by itself delete, PASS, skip or permanently block a mandatory WorkItem. The runtime must record warning/replan/defer decisions and preserve incomplete mission truth.

### CT-20 Cost-window policy

With explicit `Asia/Shanghai` bank-local time, normal workday time uses cost factor 1.0, 18:00-21:00 uses 0.1 quota-equivalent factor, and >=21:00 is quota-unlimited. Machine-local timezone MUST NOT change classification.

### CT-21 Critical-path override

A `BLOCKING` semantic WorkItem may proceed during an expensive window when it is required for mission progress; a `NON_BLOCKING` high-cost semantic unit may be deferred without deleting its requirement.

### CT-22 Deterministic-first

A deterministic step attempting an LLM call is rejected. Equivalent DB/API/CAT/CodeGraph/R1/tool work remains executable without a model call.

### CT-23 Waste guard

Exact same-context or retry-with-no-progress loops beyond configured guard are hard-blocked and replanned; the owning WorkItem remains incomplete rather than being silently dropped.

### CT-24 Unknown usage truth

Missing provider usage is recorded `UNKNOWN`, never zero/MEASURED. UNKNOWN blocks measured economy qualification but does not automatically cancel mandatory mission execution.

### CT-25 Batch lineage

ExecutionBatch/EvaluatorBatch preserves independent WorkItem/Attempt status, actual result, assertion result, evidence and gap lineage for every batch member.

### CT-26 Retry delta

Retry context defaults to prior attempt summary + explicit gap + delta evidence/changed refs. Unchanged full upstream context is not resent without an explicit full-context reason.

## 7. Required platform qualification

RC7.2 Definition of Done requires:

- unit tests;
- integration tests;
- contract tests;
- existing RC7 regression suite;
- Windows qualification;
- target Linux qualification;
- clean-unpack/offline package qualification where applicable;
- real field mission evidence before BANK_FINAL claims.

CI PASS is necessary but not equivalent to field validation.

## 8. Forbidden implementation shortcuts

The following are explicit contract violations:

1. Mock/fixture responses presented as DB/CAT/Browser/Libra/AgentTeams field evidence.
2. UI PASS without Evidence/R1 truth.
3. `uncovered method -> generate arbitrary request/case`.
4. Executor doing hidden code analysis/test redesign/data discovery to make execution pass.
5. Permanent Full Access for all workers.
6. Captain credentials delegated to workers.
7. Multiple write owners for one browser instance.
8. Hot-swapping model inside a long-running member session as the only failover strategy.
9. Session history as the only resume state.
10. A single long-lived reviewer/executor as normal architecture.
11. Fixed-size rounds used as the main task decomposition model.
12. Declaring N1-N10 implemented because prompt text names N1-N10.
13. Declaring Field capability based only on CI simulation.
14. **Using token quota/cost as justification to reduce mandatory TestObligations, L1-L7 scope, cases, assertions, evidence or defect/RCA/regression work.**
15. **Equating one fine WorkItem with one fresh full-context model call as a mandatory architecture rule.**
16. **Treating a Token Budget as a Mission kill-switch for otherwise legitimate mandatory testing.**
17. **Reporting guessed/character-estimated token counts as measured provider usage.**

## 9. Field acceptance scenario

Use a real ReleaseBatch and prove end-to-end:

```text
ReleaseBatch import
 -> Requirement/SST tree
 -> N1 real readiness
 -> N2 requirement analysis
 -> N3 CodeGraph-backed analysis
 -> N4 obligations/cases
 -> N5 data readiness
 -> N6 executable contracts
 -> adaptive ETU split
 -> fresh worker execution
 -> evidence/R1
 -> N8 semantic back-edge on injected/real gaps
 -> fresh attempts
 -> Libra feedback mapped back to obligations
 -> N9 real defects where applicable
 -> N10 release readiness/convergence
```

Field acceptance must deliberately exercise at least:

- ANALYSIS_GAP;
- TEST_DESIGN_GAP;
- TEST_DATA_GAP;
- ENVIRONMENT_GAP;
- CAPABILITY_GAP;
- Browser conflict;
- Provider quota/auth failure;
- genuine product failure/defect path;
- Captain/session handoff;
- model-economy telemetry with real usage when provider emits it;
- cost-window classification;
- at least one retry-delta or context-reuse path;
- proof that economy policy did not reduce mandatory test scope.

## 10. RC7.2 release acceptance metrics

A. 100% canonical Cases trace to ReleaseBatch/Requirement/SST/Obligation.

B. N1-N10 states/transitions are persisted and queryable.

C. Required semantic back-edges are field/contract verified.

D. Executor does not routinely absorb analysis/design/data/RCA responsibilities.

E. Worker/session rotation prevents normal design from producing giant multi-round executor sessions.

F. Coverage-driven additions retain business lineage.

G. Browser ownership isolation is enforced.

H. Provider failure does not lose Mission truth.

I. A fresh Captain can resume from R1.

J. N10 can explain with evidence why the ReleaseBatch is or is not ready for production.

K. Model/token economy is reported separately from mission completion using measured/UNKNOWN truth; no budget threshold may manufacture mission completion.

L. Equivalent-scope field measurements, not guesses, are required before claiming percentage token savings.

## 11. Definition of Done

A feature/phase may be `COMPLETED` only when:

```text
code implemented
+ schema/migration as required
+ unit/integration tests
+ applicable contract tests
+ CI pass
+ platform qualification
+ field evidence if feature is field-dependent
+ documentation/checkpoint updated
+ no unresolved contract violation
```

Otherwise status must remain one of:

```text
PARTIAL
CODE_COMPLETE
CI_PASS_FIELD_PENDING
FIELD_VALIDATION_PENDING
BLOCKED
```

## 12. Architecture regression clause

If RC7.2 drifts back to:

```text
one Captain
+ a few long-lived Agent sessions
+ coverage-gap rounds
+ executor-side improvisation
```

it is an architecture regression even if coverage or CI numbers look good. Such a build MUST NOT be accepted as RC7.2 completion.

The same applies if model economy regresses into either extreme:

```text
one fine WorkItem = one full-context LLM call
```

or

```text
save quota by deleting/coarsening mandatory test work
```

Both are construction-contract violations.

## 13. Model-economy amendment authority

`09-MISSION-COMPLETION-FIRST-MODEL-ECONOMY-DESIGN.md` is the governing design baseline for model/token economy. Where the older `08-TOKEN-ECONOMY-Q7-ADMISSION.md` or existing code treats ordinary Mission budget exhaustion as a hard stop, construction MUST migrate that behavior to the mission-completion-first semantics defined here and in design 09.

Hard blocking remains valid only for correctness/waste guards such as deterministic misuse, invalid lineage required for safe attribution, exact duplicate/no-progress loops, invalid provider/capability assignment, or other conditions where continuing the same call would not validly advance the Mission.
