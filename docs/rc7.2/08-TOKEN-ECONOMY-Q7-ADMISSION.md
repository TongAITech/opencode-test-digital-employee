# RC7.2 Model Economy / Q7 Admission Contract

Status: **REPOSITORY_CONSTRUCTION — NOT FIELD VERIFIED**

This contract addresses the RC7.1 field symptom that a roughly 40M-token quota can be consumed in about 1.5 hours. It is additive to the frozen RC7.2 qualification sequence and does **not** create a new Q gate.

Frozen sequence remains:

`Q1 → Q2 → Q3 → Q4 → Q5 → Q6 → Q7 → Q8 → Q9`

This document is governed by `09-MISSION-COMPLETION-FIRST-MODEL-ECONOMY-DESIGN.md` and the amended `02-CONSTRUCTION-CONTRACT.md`.

Model economy is a mandatory Q7 evidence dimension, but **Mission completion and test sufficiency are the primary objective**. Model economy MUST NOT reduce mandatory test scope or turn a quota target into a Mission kill-switch.

## 1. Root cause established from live runtime

The dominant risk is aggregate token amplification, not simply one coordinator chat growing forever.

Observed runtime structure:

`Mission → Stage/WorkItem fan-out → DSH producer → independent evaluator → repair/retry/failover`

Specific contributing mechanisms already present in the codebase:

1. Worker prompts correctly avoid copying coordinator conversation history and prefer R1 references.
2. Every worker still pays a repeated fixed contract cost plus task/gap context.
3. Test-design and script evaluators can re-ingest produced artifacts for independent model review.
4. Parent/fan-out evaluators can add additional review calls.
5. Failure/recovery and provider failover can create fresh Worker/Attempt/Session calls.
6. RC7.2 WorkerLifecycle single-session limits do not by themselves control aggregate ReleaseBatch consumption.
7. The common DSH launcher must use emitted provider usage when available and MUST NOT fabricate missing usage.

The failure mode is therefore:

`many bounded sessions × repeated context × evaluator calls × retries = high ReleaseBatch consumption`

The correction is **not** to coarsen real test work. The correction is to decouple fine test/scheduling WorkItems from model-call granularity.

## 2. Canonical control

Implementation:

`rc7_runtime/rc72_model_economy.py`

The control stores model-economy policy and call observations in canonical R1. No shadow business truth store is introduced.

Lineage must support aggregation by:

- ReleaseBatch/Mission;
- N-node;
- Stage;
- WorkItem;
- Attempt;
- Agent;
- retry/non-retry;
- cost window;
- execution/batch identity when implemented.

## 3. Model-call classifications

Every governed model call must be classifiable as:

- `LLM_REQUIRED` — reasoning that legitimately needs a model.
- `LLM_BATCHABLE` — semantic work that should share bounded context when compatible.
- `DETERMINISTIC_NO_LLM` — JSON/state sync, aggregation, SHA/file checks, known routing, R1 lookup, structured tool execution or other deterministic work.

`DETERMINISTIC_NO_LLM` remains fail-closed: an attempted LLM launch is rejected because it is invalid/wasteful, not because the Mission exceeded a token target.

## 4. Mission-completion-first economy policy

The previous design of ordinary Mission budget exhaustion as a hard admission block is superseded.

Budget/cost thresholds are now telemetry, warning, forecasting and replanning inputs.

They may trigger:

```text
WARN
REPLAN_EXECUTION_MODE
BATCH_MORE
HYDRATE_LESS_CONTEXT
DEFER_NON_BLOCKING_SEMANTIC_WORK
PREFER_DETERMINISTIC_WORK
PREFER_CHEAPER_WINDOW
```

They MUST NOT by themselves:

```text
drop a mandatory TestObligation/Case/ETU/WorkItem
mark work PASS without execution/evidence
reduce required L1-L7 scope
prevent a BLOCKING critical-path semantic call from progressing
mark N10 CONVERGED to save quota
```

Hard admission blocks are reserved for correctness/waste conditions such as deterministic misuse, invalid attribution lineage, exact duplicate/no-progress loops, invalid provider/capability assignment or a call already satisfied by canonical output.

When a hard waste guard fires, the WorkItem remains incomplete and must be replanned. It is never silently discarded.

## 5. Bank quota windows

RC7.2 scheduling must support explicit bank-local quota windows.

Default bank deployment policy:

```text
workday normal working time before 18:00:
  quota pool: 40M
  quota_cost_factor: 1.0

18:00 <= Asia/Shanghai local time < 21:00:
  quota accounting: 10:1
  quota_cost_factor: 0.1

Asia/Shanghai local time >= 21:00:
  quota_limited: false
```

Timezone and windows must be configuration/runtime policy, not implicit machine-local time.

A NON_BLOCKING high-cost semantic unit may be deferred to a cheaper window while deterministic/tool work continues. A BLOCKING semantic unit on the active Mission critical path may proceed despite expensive quota accounting unless an explicit operational policy/Human Gate forbids it.

## 6. Fine task granularity versus model-call granularity

The following identities are forbidden:

```text
1 WorkItem = 1 fresh full-context LLM call
```

and:

```text
save tokens = merge/delete real test work
```

The correct architecture is:

```text
fine TestObligation/TestCase/ETU/WorkItem truth
 -> deterministic/tool work where possible
 -> compatible ExecutionBatch for shared context
 -> minimum ContextEnvelope
 -> semantic model call only when needed
 -> per-WorkItem result/assertion/evidence/gap lineage
```

ExecutionBatch is a context reuse unit, not a new business truth root or a super-task.

## 7. Actual DSH usage only

`TokenMeteredDshLauncher` may wrap the existing DSH launcher and read already persisted DSH JSONL evidence.

Recognized provider usage fields can include common forms such as:

- `input_tokens` / `prompt_tokens`;
- `output_tokens` / `completion_tokens`;
- `total_tokens`.

A single unambiguous observation, or an unambiguous final-event observation, is `MEASURED`.

Missing or conflicting/multiple snapshots are `UNKNOWN`.

The control MUST NOT estimate tokens from characters and call that measurement. Character/context estimates may be used for planning only.

`UNKNOWN` does **not** automatically cancel mandatory Mission work. It means measured model-economy qualification is not proven.

## 8. Context economy

The runtime must prefer canonical refs and bounded projections over complete mission re-ingestion.

Required direction:

1. hydrate only context required for the semantic decision;
2. reuse immutable ReleaseBatch/Requirement/SST/CodeImpact/TestDesign refs by digest;
3. deterministic-first worker/evaluator checks;
4. retry with previous-attempt summary + explicit gap + delta evidence;
5. batch compatible sibling semantic review while preserving independent verdicts;
6. do not regenerate PASS siblings because one batch member failed review.

Full-context retry requires an explicit reason.

## 9. Q7 dual qualification

Q7 reporting must separate:

```text
MISSION_COMPLETION_STATUS
MODEL_ECONOMY_STATUS
```

Mission completion remains governed by N1-N10, sufficiency, execution, evidence, defect/RCA/regression and N10 convergence contracts.

Model-economy evidence should include:

- real model-call observations when emitted;
- measured/UNKNOWN truth;
- N-node/Stage/WorkItem/Attempt lineage;
- context bytes/digest/reuse factor;
- retry/review amplification;
- cost-window classification and quota-equivalent cost;
- batch/context reuse evidence when implemented;
- proof that economy policy did not reduce mandatory test scope.

Examples:

- Mission incomplete + good economy => Q7 cannot pass.
- Mission complete + usage UNKNOWN => functional completion may be true, economy qualification remains HOLD; BANK_FINAL must not claim economy verified.
- Mission complete + measured economy + no scope loss/waste regression => economy sub-contract may pass.

A hard percentage-reduction claim is prohibited until equivalent-scope field measurements exist.

## 10. Waste guards

A hard guard is valid only when continuing the same model call cannot validly advance the Mission, including:

```text
DETERMINISTIC step attempting LLM use
exact same-context loop beyond configured threshold
retry loop without semantic/evidence progress
invalid required call lineage
known duplicate call with canonical result already present
invalid model/provider/capability assignment
```

A waste guard must create durable reason/evidence and a replan path. It cannot manufacture PASS.

## 11. Metrics

At minimum report:

- model-call count;
- measured input/output/total tokens;
- pending/UNKNOWN usage;
- retry calls/tokens;
- evaluator/review calls/tokens;
- total and unique context bytes;
- context reuse/repetition factor;
- model calls per TestObligation / executed Case;
- quota-equivalent consumption by bank cost window;
- deferred non-blocking semantic work;
- hard waste-guard activations;
- incomplete lineage;
- Mission completion status beside economy status.

## 12. Integration rule

Existing RC7 worker/evaluator/business task truth must not be rewritten merely for token saving.

Construction should evolve the existing model-economy wrapper/policy and scheduler integration while preserving:

```text
ReleaseBatch -> Requirement -> SST -> TestObligation -> L1-L7 -> Case -> ETU -> WorkItem -> Attempt -> Evidence
```

The Adaptive Task Decomposer continues to decide what work should exist. Scheduler/model economy decides how and when semantic calls run.

## 13. Required regression proof

Repository tests must prove at least:

1. ordinary token-budget pressure does not drop/block mandatory work solely for economy;
2. deterministic LLM misuse remains hard-blocked;
3. same-context/no-progress loops remain hard-blocked and replanned;
4. BLOCKING semantic work can proceed in an expensive window;
5. NON_BLOCKING high-cost semantic work may defer while other useful work proceeds;
6. 18:00-21:00 classifies with factor 0.1;
7. >=21:00 classifies quota-unlimited;
8. timezone is explicit;
9. UNKNOWN usage is never zero/MEASURED;
10. retry-delta/context reuse does not weaken WorkItem/Evidence lineage;
11. token optimization does not change fine ETU decomposition semantics;
12. N10 cannot converge because economy targets were met.

## 14. Qualification boundary

Repository CI can prove policy and contract behavior. It cannot prove the in-bank DSH/provider token counters, actual 40M account behavior, 10:1 accounting, after-21:00 unlimited behavior, scheduler savings or real BLOAN-PF1.2.1 completion.

Those require real Field evidence after prerequisite Q gates are genuinely passed.
