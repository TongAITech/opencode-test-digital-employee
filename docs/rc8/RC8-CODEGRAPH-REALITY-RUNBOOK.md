# RC8 CodeGraph Bank Reality Runbook

Status: W1 REALITY GATE
Capability: `codegraph`

## Purpose
Prove the actual bank CodeGraph execution path, not package presence:

`Java change -> Git snapshot -> real CodeGraph structural queries -> graph-evidence.json -> Center Artifact AVAILABLE -> R1 -> WorkItem COMPLETED -> capability VERIFIED`.

Git is the sole source-change/snapshot authority. CodeGraph is structural enrichment only.

## Preconditions
- RC8 Center is READY.
- RC8 Node identity is registered and stable.
- Target project is a real Git repository.
- Real CodeGraph executable is available on the execution node.
- The selected base/head range contains at least one Java change, OR `--target-file/--target-line` is supplied.
- Windows uses Git Bash; Xinchuang Linux uses bash.

## Canonical command

```bash
bash packaging/rc8/rc8-codegraph-reality.sh \
  --center http://127.0.0.1:4098 \
  --node-id office-pc-01 \
  --operator test-user \
  --state-dir "$RC8_NODE_STATE" \
  --project-dir /d/PFC/bloan-prod-factory-cfg-center \
  --codegraph /path/to/real/codegraph \
  --base-ref HEAD~1 \
  --head-ref HEAD \
  --max-points 2
```

When the selected commit range does not contain a usable Java change, explicitly bind a target:

```bash
  --target-file cc-server/src/main/java/com/pfc/cc/.../SomeService.java \
  --target-line 120
```

The explicit target must exist in the same Git repository and is still bound to the current snapshot.

## Required real queries
For every selected query point RC8 executes these read-only CodeGraph tools:
1. `codegraph_get_ai_context`
2. `codegraph_get_callers`
3. `codegraph_get_callees`
4. `codegraph_get_dependency_graph`
5. `codegraph_analyze_impact`

A successful empty relationship graph is valid truth. A failed query is not. All required calls must execute successfully for CodeGraph execution to PASS.

## Snapshot gate
RC8 records a snapshot fingerprint composed from:
- Git HEAD revision;
- working-tree status digest;
- tracked diff digest;
- untracked Java content hashes.

The fingerprint is checked:
1. before graph queries;
2. after graph queries;
3. immediately before R1 publication.

Any mismatch fails closed as `CODEGRAPH_SNAPSHOT_STALE` / `CODEGRAPH_SNAPSHOT_STALE_BEFORE_PUBLISH`.

## Required outputs
Node local:
- `reality/<run-id>/preflight.json`
- `reality/<run-id>/capability/graph-evidence.json`
- `reality/<run-id>/execution/graph-evidence.json`
- `reality/<run-id>/reality-result.json`

Center:
- capability evidence Artifact = AVAILABLE;
- execution graph evidence Artifact = AVAILABLE;
- `codegraph` capability = VERIFIED;
- R1 event type = `CODEGRAPH_GRAPH_EVIDENCE_RECORDED`;
- execution WorkItem = COMPLETED.

R1 event must contain at least:
- Git HEAD;
- `snapshot_id`;
- base/head refs;
- changed Java files;
- query points;
- tool names/count;
- `graph_digest`;
- execution Artifact reference.

## PASS criteria
A bank run may be called `BANK_REALITY_VERIFIED` only when all are true:
- real bank CodeGraph executable was used;
- at least one Java query point was bound;
- every required structural call succeeded;
- source snapshot stayed unchanged through publication;
- graph evidence Artifact reached AVAILABLE;
- capability state reached VERIFIED only after Artifact acceptance;
- R1 receipt is `PERSISTENCE_VERIFIED` or idempotent replay;
- execution WorkItem is COMPLETED.

CI contract doubles must never be promoted to bank reality evidence.

## Fail-closed classifications
- `CODEGRAPH_COMMAND_NOT_FOUND`
- `CODEGRAPH_JAVA_CHANGE_OR_TARGET_REQUIRED`
- `CODEGRAPH_STRUCTURAL_QUERY_FAILED`
- `CODEGRAPH_SNAPSHOT_STALE`
- `CODEGRAPH_SNAPSHOT_STALE_BEFORE_PUBLISH`
- `CODEGRAPH_EVIDENCE_NOT_AVAILABLE`
- `CODEGRAPH_R1_NOT_PERSISTED`

## Anti-fake rules
- CodeGraph installed/registered is not VERIFIED.
- A model-written call chain is not graph evidence.
- Stale CodeGraph output from another Git snapshot is forbidden.
- Git diff is not replaced by CodeGraph inference.
- A failed relationship query cannot be silently treated as an empty graph.
- No R1 execution fact is written before evidence is accepted and snapshot freshness is rechecked.
