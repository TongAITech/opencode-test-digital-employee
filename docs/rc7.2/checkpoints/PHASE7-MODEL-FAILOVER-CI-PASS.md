# RC7.2 Phase 7 Model / Provider Failover checkpoint

Status: `CI_PASS` (repository qualification only)

Qualified code HEAD: `6a132d28930dd79c938a8694dfd5a4778cd9b402`
Qualified workflow run: `40726069936`

Qualification evidence:

- RC7.2 contracts Python 3.8: PASS — `116 passed`.
- RC7.2 contracts Python 3.11: PASS — `116 passed`.
- inherited RC7 regression Python 3.8: PASS — `492 passed, 1 skipped`.
- runtime compile: PASS.

TDD / fix chain:

- `ada525cc...` froze model/provider failover contracts and intentionally produced RED because `rc72_model_failover` did not yet exist.
- `27778721...` added attempt-scoped provider readiness, ModelAssignment, ProviderFailure and fresh-worker failover runtime.
- `effeb38a...` fixed dynamic R1 projection bucket initialization without weakening projection/replay integrity.
- `6a132d28...` upgraded the test fixture to include the real inherited `execution_attempt` required by canonical BLOCKED lineage; `CanonicalRC72Repository` was not weakened.

Delivered slice:

1. ModelAssignment is bound to WorkItem/Attempt/Worker/Session, not the whole Mission.
2. provider failures use the explicit namespace/classes `PROVIDER_AUTH`, `PROVIDER_QUOTA`, `PROVIDER_TIMEOUT`, `PROVIDER_UNAVAILABLE`, `PROVIDER_CONFIG_INVALID`; they do not become SUT defects.
3. provider failure checkpoints and closes the old Worker Session and marks the old binding/assignment blocked.
4. fallback selection only chooses an explicitly configured provider/model whose readiness is `MODEL_READY`.
5. an unavailable earlier fallback is skipped; no ready fallback fails closed as `NO_READY_FALLBACK_MODEL`.
6. `PROVIDER_CONFIG_INVALID` requires operator repair and is not automatically failed over.
7. failover never hot-swaps a model into the old long-running Agent/Session/Attempt.
8. successful failover creates a fresh Worker, fresh Session and new child Attempt for the same WorkItem/ETU with `parent_attempt_id` preserving lineage.
9. old ModelAssignment remains immutable as the failed provider/model identity and becomes `BLOCKED_PROVIDER`; replacement assignment is separate and ACTIVE.
10. provider readiness, assignments, failures and failover lineage persist in the same R1 and survive replay.

Important implementation boundary:

- this is repository/runtime control-plane qualification, not proof that the in-bank aicoder-plus/dsv4/BankGPT providers have been exercised by a real RC7.2 mission.
- startup authentication/readiness integration still requires Field validation against real Wizard/CAS/provider behavior.
- no existing long-lived AgentTeams member is mutated to another model.

With CapabilityBroker, BrowserPool/BrowserLease, DataLease and Model/Provider Failover all CI-qualified, **Phase 7 Resource / Capability Runtime is CI_PASS**.

Field validation: `NO`.

Next phase: **Phase 8 — coverage/convergence feedback must be rooted back through ReleaseBatch → Requirement → SST → TestObligation; Libra may prioritize/repair obligations but may not become the test-asset root.**
