# RC6 Wave 2 Qualification Contract

Wave 2 closes the field failure where raw R1 events existed but derived Intent/Condition/Case projections were incomplete or overwritten.

## Runtime invariants

- R1 JSONL is the sole durable truth.
- Live writes accept exactly one canonical domain entity per event.
- `TEST_CASE_UPSERTED` never accepts `{cases:[...]}`.
- Each Test Case has exactly one layer `L1`..`L7`; mixed values such as `L2|L3` are invalid.
- RC5 legacy batch events are replay-only migration input. They are expanded in memory and never repaired by writing replacement business events.
- Projection is disposable and must be reconstructable from R1.
- Replaying the same R1 stream repeatedly must produce the same projection.
- Same entity/version with conflicting payload fails closed.
- Case version N+1 supersedes N in latest projection while version history remains queryable.
- `release_id`, `requirement_id`, and `sst_id` are canonical top-level query fields.
- An append is successful only after read-after-write entity and query verification.

## Qualification scenarios

1. Reject mixed-layer Case.
2. Reject live batch-shaped Case write.
3. Atomic Case is immediately queryable.
4. Replay RC5-style legacy batches containing exactly 17 Intents, 17 Conditions, and 23 Cases without adding repair events.
5. Replay three times with byte-equivalent logical projection.
6. Fail closed on conflicting payload for same Case/version.
7. Preserve v1/v2 Case history while exposing v2 as latest.
8. Query Cases by release, requirement, and SST.
9. Re-run Wave 1 tests to prove no Runtime Kernel regression.

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 2 may be marked `ENGINEERING_PASS / FROZEN` only after the committed source passes GitHub Actions and the run id/head SHA are recorded in `RC6_CONSTRUCTION_STATUS.md`.
