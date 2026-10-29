# RC7.2 Token Economy / Q7 Admission Contract

Status: **REPOSITORY_CONSTRUCTION — NOT FIELD VERIFIED**

This contract addresses the RC7.1 field symptom that a roughly 40M-token quota can be consumed in about 1.5 hours. It is additive to the frozen RC7.2 qualification sequence and does **not** create a new Q gate.

Frozen sequence remains:

`Q1 → Q2 → Q3 → Q4 → Q5 → Q6 → Q7 → Q8 → Q9`

Token economy is a mandatory **Q7 admission sub-gate** before a real ReleaseBatch N1-N10 run may be accepted.

## 1. Root cause established from live runtime

The dominant risk is aggregate token amplification, not simply one coordinator chat growing forever.

Observed runtime structure:

`Mission → Stage/WorkItem fan-out → DSH producer → independent evaluator → repair/retry/failover`

Specific contributing mechanisms already present in the codebase:

1. Worker prompts correctly avoid copying coordinator conversation history and prefer R1 references.
2. Every worker still pays a repeated fixed contract cost plus task/gap context.
3. Test-design and script evaluators re-ingest produced artifacts for independent model review.
4. Parent/fan-out evaluators add additional review calls.
5. Failure/recovery and provider failover can create fresh Worker/Attempt/Session calls.
6. RC7.2 `WorkerLifecyclePolicy.max_tokens=50000` protects one Worker Session, but does not bound aggregate Mission/ReleaseBatch consumption.
7. The inspected common DSH launcher does not expose provider token usage in `WorkerInvocation`/`HeadlessRunResult`; therefore a 50K session policy alone is not proof of account-level consumption.

The failure mode is therefore:

`many bounded sessions × repeated context × evaluator calls × retries = unbounded ReleaseBatch consumption`

## 2. Canonical control

Implementation:

`rc7_runtime/rc72_token_economy.py`

The control stores budget and call observations in canonical R1 using:

- `rc72_token_budget`
- `rc72_token_call`

No shadow business truth store is introduced.

Budget hierarchy begins at Mission/ReleaseBatch scope and records sufficient lineage for later aggregation by:

- Mission
- N-node
- Stage
- WorkItem
- Attempt
- Agent
- retry/non-retry

## 3. Model-call classifications

Every governed model call must be classified:

- `LLM_REQUIRED` — reasoning that legitimately needs a model.
- `LLM_BATCHABLE` — model work that should be grouped when practical.
- `DETERMINISTIC_NO_LLM` — JSON conversion, state sync, aggregation, SHA/file checks, known routing, R1 lookup or other deterministic work.

`DETERMINISTIC_NO_LLM` is fail-closed: admission is rejected before DSH is launched.

## 4. Admission rules

A Mission must have an explicit token budget. There is no silent unlimited default.

Before each DSH launch the control reserves `max_single_call_tokens` and checks:

- Mission total-token budget;
- Mission model-call count;
- retry-token budget;
- retry-call count;
- exact repeated-context call limit;
- prior UNKNOWN usage under strict measurement mode.

Budget exhaustion blocks the next call before quota overshoot.

The architecture deliberately does not hard-code a production budget from the user's 40M account quota. The first real RC7.2 Field run must choose an explicit ReleaseBatch budget and then calibrate it using measured DSH usage. A guessed quota is not qualification evidence.

## 5. Actual DSH usage only

`TokenMeteredDshLauncher` transparently wraps the existing DSH launcher.

It fingerprints the exact prompt before execution and reads the already persisted raw DSH JSONL evidence after execution.

Recognized provider usage fields include common forms such as:

- `input_tokens` / `prompt_tokens`
- `output_tokens` / `completion_tokens`
- `total_tokens`

A single unambiguous observation, or an unambiguous final-event observation, is `MEASURED`.

Missing or conflicting/multiple snapshots are `UNKNOWN`.

The control MUST NOT estimate tokens from characters and call that measurement. Character/token estimates may be used later for planning, but never to make Q7 green.

## 6. Q7 token-economy admission

Strict Q7 admission is `PASS` only when:

1. an explicit Mission budget exists;
2. at least one real model-call usage observation exists;
3. no call is still pending;
4. all model calls have `MEASURED` usage when `require_measured_usage=true`;
5. N-node/Stage/WorkItem lineage is complete when `require_complete_lineage=true`;
6. Mission total tokens remain within budget;
7. model-call count remains within budget;
8. retry tokens and retry calls remain within budget.

If DSH does not emit usable token counters, the result is:

`HOLD / TOKEN_USAGE_UNKNOWN`

It is never converted to a guessed PASS.

## 7. Context amplification metrics

The ledger records:

- model-call count;
- measured input/output/total tokens;
- pending and UNKNOWN reserved tokens;
- retry call/token consumption;
- exact prompt SHA-256;
- exact prompt UTF-8 byte count;
- total context bytes;
- unique context bytes;
- `context_reuse_factor`;
- incomplete lineage call ids.

This makes repeated-context amplification visible even before provider-specific optimization.

## 8. Integration rule

Existing RC7 worker/evaluator code does not need to be rewritten.

Construction must wrap the existing `DshHeadlessWorkerLauncher` with `TokenMeteredDshLauncher`, then pass that wrapper into the existing `DshTaskWorkerBridge`.

For strict Q7, a metadata resolver must bind each assignment to real:

`node + stage + workitem_id + retry state`

If the resolver cannot bind those fields, Q7 remains `HOLD / TOKEN_CALL_LINEAGE_INCOMPLETE`.

## 9. What this does and does not solve

This slice immediately prevents uncontrolled aggregate quota consumption and creates trustworthy measurement.

It does **not** by itself optimize every duplicated evaluator prompt. Once measured field data identifies the highest-cost nodes, the next optimization should target:

1. batch sibling Case/Evidence review where independence is preserved;
2. replace full artifact re-ingestion with canonical refs + bounded evaluator projections;
3. keep deterministic checks ahead of model evaluators;
4. bound repair loops by both semantic progress and token budget;
5. tune decomposition granularity against measured cost per Test Obligation.

The priority is evidence-driven reduction, not weakening test quality to save tokens.

## 10. Qualification boundary

Repository unit/contract tests can prove the control behaves correctly.

They cannot prove the in-bank DSH/provider actually emits usable token counters or that BLOAN-PF1.2.1 stays within the selected Field budget.

That proof belongs to the real Q7 ReleaseBatch run after Q3-Q6 are genuinely passed.
