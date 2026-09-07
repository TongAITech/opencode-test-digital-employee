# V1.12.0 Context Pressure Recovery

ArchitectureBaseline v7 remains FROZEN and unchanged. G6 remains HOLD. This
repair uses the existing G2.1 observation/rotation events and R1.3B/R2.5 resume
path. No legacy `aitest.db` write or conversation-based Mission reconstruction
is introduced.

## Observation contract

The directory-scoped OpenCode provider reads session metadata. If message,
compaction, or context utilization metrics are missing, it additionally reads
`GET /session/{id}/message?directory=...&limit=60`. Each message must have an
`info.id`, matching `info.sessionID`, and `parts` array. Message content is held
only while computing counts/estimates; observation events contain scalar
diagnostics and hashes, never a copy of message/tool content.

Native message counts and compaction counts are reconciled with the sampled
messages. When available, latest assistant input/output/cache token usage is
used; cumulative billing totals are not treated as current context usage. An
unknown model context limit remains null.

The fixed fallback policy is `g2.1-opencode-1.18.3-pressure-v1`:

| Signal | Runtime rotation trigger |
| --- | --- |
| Actual context utilization | 85% |
| Messages / saturated sample | 60 messages |
| Compaction parts | At least one |
| Estimated context budget | 75% of 32,768 budget units |
| Assistant turns | 24 |
| Tool / step-finish activity | 48 |
| Message observation HTTP body | Over 8 MiB |
| Metadata-only observation | 12 metadata changes or 300 seconds without usable message observation |

The estimate counts UTF-8 bytes of serialized message parts, 128 units of
framing per message, and a 4,096-unit reserve. This is a conservative Runtime
budget, **not an asserted tokenizer count or model capacity**. It intentionally
rotates sooner for large tool outputs and non-ASCII text. Blind-mode start time
and activity count are persisted in the existing R1 observation provider state,
so restarting the supervisor cannot reset those budgets. Unchanged polling does
not increase activity count. Auth admission 401/403 remains WAIT and causes no
Session rotation.

Polling cannot prevent one arbitrarily large provider response from exceeding
a model window between observations. The bounded sample/response size and
early estimate threshold reduce this exposure; bank validation must still
exercise the configured model and actual BLOAN tool-output sizes.

## Rotation and recovery

Before external rotation effects, G2.1 records a checkpoint on its existing
rotation request event. It contains the R1 cursor/state digest and exact
Mission, Task, LogicalAgent, root Attempt and predecessor Session identities.
This cursor can replay all already-durable work. Undurable conversation-only
work cannot be recovered and is never represented as a checkpoint result.

The real provider aborts the predecessor generation, then creates the successor
under a durable deterministic provisioning token. Frozen R2.5/R1.3B creates the
resume Attempt and canonical ContextPack. Bootstrap reconstructs that pack at
its exact cursor, verifies its semantic digest, and includes its reference,
the rotation checkpoint, and a bounded extract. Bootstrap is capped at 16 KiB;
oversized Goal/Task bodies become canonical references. No full conversation is
copied into the successor. Planner rotation similarly references its checkpoint
and current R1 cursor.

Bootstrap uses `prompt_async`, so a running model does not block subsequent
control-loop ticks. The predecessor is closed durably after the successor is
accepted; a pending rotation is reconciled after a process restart. Completed
rotation retains Mission/Task/root Attempt/LogicalAgent lineage.

## Validation boundary

`test_g2_1_pressure_fallback.py` checks adversarial payloads, budgets, bounded
bootstrap and durable blind-mode restart. The independent-process HTTP test
removes metadata counters and verifies automatic fallback rotation, checkpoint,
ContextPack, abort and async submission. Existing router/crash-window and auth
admission regressions remain applicable. These are LOCAL_VALIDATION checks
against construction providers. Real Windows OpenCode/model behavior and bank
BLOAN scope remain separate Windows CI and bank field validations.
