# F08/F29 API Oracle integrity

At baseline `240573e`, each cross-channel assertion wrote to `checks['channel_'+channel]`. A later successful DB/CAT read erased an earlier mandatory failure. This change repairs the existing `recovery_api.run_journey` and canonical G4 Case injection; it adds no alternative executor.

Each status, business assertion, cross-channel read and idempotency observation has an ID derived from the frozen Case version, unique step ID, kind, channel and ordinal. Every declaration retains a digest; cross-channel results also retain the bound query ID and resolved parameter digest. Individual statuses are PASS, FAIL, ERROR or NOT_RUN. Overall PASS requires every mandatory ID to have a PASS observation and every journey step to complete. Later successes cannot erase failures. Missing providers, missing values, invalid JSON and observation exceptions cannot become PASS. Explicitly optional assertions remain visible but do not override a mandatory failure. Failed prerequisites stop subsequent HTTP steps and idempotency repeat sends.

The frozen Case must independently bind its human-reviewed expectation to the executable assertion model:

- `oracle_contract.api_oracle_version` is 1; in G3 detailed specifications this is `oracle.api_oracle_version`.
- `oracle_contract.api_variables` equals the initial journey variables, or `{}`.
- Journey steps, ordered steps and expected results have matching, unique `step_id` values in the same order.
- Each `expected_results[].api` contains the exact `status_code`, `assertions`, `cross_channel`, `extract` and `idempotency` expectation. Defaults are `[]`, `{}` and `null` where applicable. Execution rejects any drift before provider execution/HTTP transmission.

This validates structured assertion consistency; it does not claim to infer equivalence between arbitrary natural-language business requirements and code. Case authors and independent reviewers remain responsible for that semantic review. Old Case versions without this binding fail closed and require a newly reviewed version. No historical event or frozen expectation is automatically rewritten. Test fixtures were extended with declarations before execution; their existing business assertions were retained.

Canonical G4 also replaces caller-supplied `step.expected` with the frozen Case expected results and Oracle contract. The caller cannot record a different expectation while the executor runs the stored Case. Generated pytest continues to reference the same Case identity and canonical G4 path.

Receipts retain bounded selected expected/actual values and a readable diff classification, plus safe error type/code; they do not dump response bodies or provider exception messages. Sensitive fields and identifier paths are redacted. Each diagnostic is limited to 1024 UTF-8 bytes, the journey to 128 Oracles, 32 steps and 64 KiB of specification. Response streaming retains the existing 2 MiB input cap. The tests exercise readable numeric mismatch evidence, Unicode size bounds and secret suppression. This is a bounded redaction baseline, not a claim that arbitrary business data has been classified for every bank environment.

Validation includes DB and CAT first/middle/last mandatory failures and all-true controls, absent/missing/exception observations, optional versus mandatory aggregation, duplicate IDs, missing/drifting frozen bindings rejected before HTTP, later-step suppression, stable IDs, frozen array variables, bounded diagnostics, and a canonical G4 failure that remains FAIL after runtime reconstruction. Existing business, generated-pytest/knowledge and offline-executor regression suites are also run against real synthetic loopback HTTP.

Scope limit: UNKNOWN_SIDE_EFFECT pre-send intents, durable send/receipt ledgers, non-idempotent reconciliation and replay authorization are not implemented by this patch. The independently demonstrated interrupted-POST gap remains open. No full F08/F29, G4, model, bank, Windows or production qualification PASS follows from this focused repair.
