# RC7.2 Design Baseline & Mandatory Read Order

Status: FROZEN DESIGN BASELINE
Branch: `work/rc7.2-design-baseline`
Base: RC7.1 Field Turnkey `366e196826afb3be17d2811044699891bdd28ea5`

## 1. Purpose

This directory is the anti-drift source of truth for RC7.2 construction. RC7.2 keeps the validated RC7.1 capabilities and replaces the orchestration/runtime core that currently behaves as long-lived Agent sessions + prompt-driven rounds.

The target is a release-batch-centric autonomous test runtime:

```text
ReleaseBatch
  -> ReleaseBatchMission
  -> N1-N10 MissionGraph
  -> SufficiencyGate
  -> TestObligation
  -> AdaptiveTaskDecomposer
  -> ETU / WorkItem / Attempt
  -> Fresh Worker Session
  -> Capability/Browser/Data/Model Lease
  -> Real Tool/Skill
  -> Evidence
  -> Canonical R1
  -> Fresh Review
  -> Semantic Back-edge
  -> N10 Release Convergence
```

## 2. Mandatory read order for every construction session

Every new construction/repair session MUST do all of the following before changing code:

1. Read the latest HEAD of the current construction branch. Never trust an old SHA copied from chat.
2. Read this file.
3. Read `01-AUTONOMOUS-TEST-RUNTIME-DESIGN.md`.
4. Read `02-CONSTRUCTION-CONTRACT.md`.
5. Read `03-N1-N10-RUNTIME-STATE-MACHINE-CONTRACT.md`.
6. Read `04-ADAPTIVE-TASK-DECOMPOSER-CONTRACT.md`.
7. Read `05-AGENTTEAMS-WORKER-LEASE-CONTRACT.md`.
8. Inspect current code, R1 schemas, migrations, CI/check-runs and field evidence.
9. Produce a short contract-impact statement before implementation: which clauses are being implemented, which remain incomplete, and what evidence will prove completion.

Chat history, prompts, screenshots, old implementation notes and old checkpoints are secondary. If they conflict with this directory, the latest repository contract plus current code/R1 truth wins.

## 3. Frozen business hierarchy

The canonical business/test asset hierarchy is:

```text
Release Batch
  -> Version / Application
  -> Requirement
  -> SST
  -> Test Obligation
  -> L1-L7
  -> Test Case
  -> ETU
  -> WorkItem
  -> Attempt
  -> Evidence
```

Coverage, risk, defects, code impact, round number and execution status are attributes/feedback dimensions. They are NOT allowed to replace the hierarchy.

A case without `release_batch_id + requirement_id + sst_id + obligation_id` is not a canonical RC7.2 test asset unless it is explicitly classified as an investigation/exclusion candidate.

## 4. Frozen control hierarchy

```text
Mission
  -> MissionNode(N1-N10)
  -> NodeDelivery
  -> NodeGate
  -> Stage
  -> ETU / WorkItem
  -> Attempt
  -> Team Role
  -> Fresh Worker
  -> Tool/Skill
  -> Evidence
  -> R1
```

`MissionNode != Agent` and `Role != Session`.

AgentTeams is an execution substrate, not the mission state machine.

## 5. Current RC7.1 gaps that RC7.2 MUST close

- GAP-01 Startup/model authentication sequencing and explicit readiness states.
- GAP-02 Adaptive task decomposition not implemented; current rounds are too large and coarse.
- GAP-03 Journey Teaching / business-flow recording not productized.
- GAP-04 Provider quota/model failover and fresh-worker takeover missing.
- GAP-05 Browser/BSK resource isolation and lease ownership missing.
- GAP-06 Worker STRICT permission lacks capability request / lease amendment / delegation.
- GAP-07 N2-N8 stage boundaries and sufficiency gates not enforced; executor absorbs analysis/design/data/RCA work.
- GAP-08 ReleaseBatch->Requirement->SST test organization has been displaced by Libra coverage-gap-driven rounds.

Cross-cutting symptoms that MUST be eliminated by the above architecture, not patched individually:

- long-lived executor/designer/reviewer sessions and context growth;
- reviewer history contamination;
- R1/runtime state inconsistent with Agent-reported completion;
- inability to hand off captain/session based purely on canonical truth;
- coverage-driven attack execution;
- provider/browser/capability failures incorrectly mixed with SUT failures.

## 6. Non-negotiable principles

1. Release Batch is the business root and N10 convergence target.
2. R1/Evidence is runtime truth; Session is disposable.
3. N1-N10 are real persisted runtime objects with gates and transitions.
4. Insufficiency returns to the responsible node; executor may not silently repair upstream work.
5. Coverage is a convergence signal, never the asset root or sole objective.
6. Test cases must be generated from Requirement/SST Test Obligations, not directly from uncovered methods.
7. Worker is STRICT by default; dynamic temporary authority is granted by lease, not by sharing Captain credentials.
8. Browser write ownership is exclusive and leased.
9. Model/provider failure is infrastructure state, not product failure.
10. No UI PASS without canonical evidence.
11. No mock/simulation may be presented as field capability.
12. No construction phase may be declared complete without contract tests and the required evidence.

## 7. Document authority

- `01` defines target architecture and detailed design.
- `02` defines construction obligations, sequencing, deliverables and Definition of Done.
- `03` defines N1-N10 node semantics, gates, state transitions and back-edges.
- `04` defines ReleaseBatch/SST-centric adaptive decomposition and coverage feedback.
- `05` defines AgentTeams worker lifecycle, session rotation and resource/capability leases.

If an implementation choice is not covered, it may be decided locally only when it does not violate any frozen principle. Material changes to hierarchy, state semantics, authority boundaries or acceptance criteria require updating these documents first in a dedicated design commit.

## 8. Anti-drift rule for plans/checkpoints

Every implementation plan/checkpoint MUST include:

```text
BASELINE_HEAD=<current head>
CONTRACT_SET=docs/rc7.2/00..05
IMPLEMENTED_CLAUSES=[...]
UNIMPLEMENTED_CLAUSES=[...]
FIELD_EVIDENCE_STATUS=...
KNOWN_DEVIATIONS=[...]
```

A plan is not a source of truth if it conflicts with the contract or current code/R1 evidence.
