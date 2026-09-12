# C1 execution independent raw-source review

> Latest component decision: **REVIEWED_COMPONENT_REGRESSION_PASS** for the reviewed General execution/admission-recovery component and its repaired findings. Full C1, Windows execution, all-role context/liveness and final product qualification remain OPEN. Earlier decisions below are preserved review history; the final appended verification is current.

**DECISION = CHANGES_REQUIRED_BEFORE_C1_EXECUTION_FREEZE.** Continue authorized repairs; no Architecture change or user approval is required. This is the requested C1 wave review, not another Resume Checkpoint. Sources are the live implementation plus existing tests; fingerprints/HEAD are in `c1-review-observation.json`. Only this review directory was written by Reviewer.

## What is now real

`GeneralExecutionService.start` re-reads actual Host user provenance, checks operation text/request digest, consumes the R1 operation receipt, creates a typed non-Mission root, uses shared pure task selection, provisions a separate Host Session and binds it to root-local epoch/lineage. Actual tool invocation is matched against the Host's running tool part/session/message/agent/input; model JSON is not authority. File effects and replies have R1 call claims/receipts. The old lifecycle completion shortcut and the original simple hash/spec mismatch are now rejected. Scoped directory listing uses guarded handles and enumeration/time bounds; explicit user-named ordinary config paths can be changed while product-owned paths remain protected.

Independently reread `general-host-01/host-messages.json`, not only the implementer's summary: write_file returned a completed disk receipt; complete cited the matching SHA256 and read-back; git_inspect returned **FAILED / GENERAL_OS_CONFINEMENT_UNAVAILABLE** despite the outer Host tool status being completed. Actual output is `green apple`; one user request, separate worker Session, zero Mission is supported by the retained component evidence. Default plugins were disabled for this isolated probe: this is not installed-product normal-entry L4 or Windows terminal qualification.

Fresh existing execution suite: **15 tests OK / 4.225s**. Those tests cover useful positive/negative cases but miss the following four adversarial transitions. Independent actual-product/temporary-disk reproductions are in `c1-independent-counterexamples.json`.

## Blocking findings

### C1-R1 — P1: General write job can report completion without work

`execution.py` worker complete accepts empty result_refs and any nonempty summary. The root COMPLETE checks only that this same complete call obtained a receipt, not that requested engineering work has supporting observations/effects. Reproduction: start the write job “把说明写到 notes/result.txt”; immediately complete “已写好 notes/result.txt” with no preceding read/write. Result: job **COMPLETED**, file absent. This is an engineering false success even though no formal TestCase verdict is mutated.

Minimum fix: purpose/action-aware completion obligation, backed by successful same-job receipts and verified current artifact references (or an explicit evidence-backed no-change outcome). Do not require every mentioned input filename to be written. Distinguish observed execution completion from semantic correctness; failed optional exploratory git inspection in the actual successful file task should not falsely fail that task. Add zero-work / only-failed-effects / unrelated-old-artifact negatives and valid read/write/diagnosis controls. Enforce the invariant during root transition/replay too, not only a model prompt.

### C1-R2 — P1: read-only crash fences the job forever

After CALL_CLAIM, kill/fail before `_write_receipt` during a read_file operation. `_reconcile_call` handles existing cache or postimage write only; a read with no cache is permanently GENERAL_EFFECT_RECONCILIATION_REQUIRED. Two supervisor ticks leave the sole call CLAIMED and job ACTIVE; later calls are fenced. A safe read-only operation requires autonomous recovery, not an external-side-effect UNKNOWN barrier forever.

Minimum fix: classify each action by effect; replay/reconstruct bounded read/status/search from durable validated request_spec, record a fresh observation with proper provenance, and finish/reconcile the original claim. Checkpoint/complete with missing cache can revalidate references from their recorded spec. Preserve no-blind-retry for mutating operations. Test abrupt process death, not only a Python exception, then supervisor-only recovery without a new user turn.

### C1-R3 — P1: create/bind-to-PREPARE crash is never supervised

`start` writes operation claim → job create → operation bind → PREPARE in separate canonical transactions. `supervise_once` skips every non-ACTIVE or execution-empty job. Reproduction interrupts immediately before PREPARE: a durable CREATED/bound job exists, no worker Session, supervisor returns jobs=[] indefinitely. An earlier claim-before-job gap also has no subject row for this scan. Retrying the user call is not autonomous recovery and later Host freshness expiration makes that retry insufficient.

Minimum fix: a runtime recovery owner scans pending Interaction receipts/created roots and deterministically resumes the already-authorized stages from R1, preserving exact source operation/subject and no duplicate Session or prompt. Authorization consumed earlier may be recovered without inventing a new fresh user turn; validate original bound identity, policy and current lease. Test crashes at every stage independently, including claim-before-create, create-before-bind, bind-before-prepare, provision/send and complete receipt gaps.

### C1-R4 — P1: displaced version can still be deleted on validation failure

POSIX write exchanges the current target with tmp, then reads displaced tmp using the ordinary <=4MiB broker reader; the outer finally unconditionally unlinks tmp. Inject a concurrent edit of MAX_FILE+1 bytes in the last exchange window. Result: GENERAL_FILE_BYTE_BUDGET error, target is six-byte “worker”, the concurrent version is deleted; only initial before.bin and change.diff remain. The earlier one-small-concurrent-edit test passes but does not cover failures after displacement.

Minimum fix: preserve/quarantine a displaced object atomically before attempting bounded inspection; never cleanup an unverified displaced object. Recovery metadata must distinguish not-applied/applied/conflicted/unknown so a later postimage readback cannot launder this failed overwrite into success. Test unreadable/oversized/changed-type displaced entries, backup/fsync failures, second concurrent edit and crash-after-exchange. Windows ReplaceFile branches need equivalent installed-byte tests; do not infer them from POSIX passes.

## Follow-through observations

- General supervision currently enumerates lifetime roots with LIMIT 257 and then raises if >256; completed roots count too. A mature workspace can disable all General supervision/status. Use active-filtered pagination plus bounded fair cursor; resource budget must not turn 257 historical jobs into a global service outage.
- `_prompt` reuses epoch+business_cursor; initial idle with no business progress sees ACCEPTED and never wakes. Status calls do not advance business cursor, correctly, but no independent wake budget/diagnosis exists. All-role rotation/poison handling remains C2/C3 work. Keep it OPEN rather than calling General execution continuous recovery complete.
- File broker holds the global coordination lock during bounded reads/search and Host requests; the existing budgets help, but prove Mission progress under active General work and timeout recovery before claiming mixed-work fairness.
- This review does not close the explicitly still-unwired Mission controls/update/HumanGate owners, Windows process confinement, or final provider Governor.

TASK_DIFFICULTY = HARD. REASONING_RECOMMENDATION = HIGH for the four race/recovery/authority fixes; ordinary wiring/tests may use MEDIUM. No global invariant contradiction was found.


## Repair verification — same C1 review, 2026-09-12

Fresh independently executed execution suite: **23 tests OK / 8.522s**, including actual two-process same-call coordination and os._exit(73) after disk effect. Reviewer reread the changed execution owner, root completion validator and atomic displacement path. This is an incremental working-tree review, not a final exact-installed-byte seal.

| Original finding | Verification |
|---|---|
| C1-R1 zero-work write completion | **Original counterexample CLOSED**: root `validate_completion` requires successful same-job write receipt plus produced refs, run requires terminal observation, read/diagnosis require an actual observation. The former empty-summary-only success now returns FAILED and leaves job ACTIVE. This is evidence-of-work admission, not proof that all semantic user obligations are fulfilled. |
| C1-R2 read crash without cache | **Original counterexample CLOSED**: supervisor reconstructs bounded read/search/status from durable spec and records FRESH_READ_ONLY_OBSERVATION, explicitly not the lost original observation. Adjacent checkpoint/complete missing-cache gap remains below. |
| C1-R3 CREATED before PREPARE | **Exact reproduced window CLOSED; broader staged admission recovery remains OPEN**: durable operation_text lets CREATED + bound receipt recover after original Host conversation is deleted. Earlier claim-before-create still has no recovery candidate. |
| C1-R4 oversized displaced version | **Original POSIX counterexample CLOSED**: failed displaced inspection preserves the unknown object; when the installed worker version is unchanged it swaps back without reading the large old body. Test verifies every byte of MAX_FILE+1 original concurrent data survives. Windows replacement failure paths remain separately unqualified, not closed by this test. |

The lifetime 256-job unconditional failure has been replaced with active candidate pagination and R1 state reads; initial idle now has a grace period and one bounded AUTO_CONTINUE per cursor, with busy exclusion. Automatic no-progress Diagnosis remains explicitly C3 pending.

### Remaining P1 recovery windows (independently reproduced)

Machine evidence: `c1-recovery-followup-counterexamples.json`.

- **C1-R3 follow-through: claim-before-create**. Interrupt `jobs.create` after `owner.claim`: one durable Interaction receipt, zero job roots, zero sessions; supervisor returns empty jobs. The implemented scanner starts from general_work_projection, so this accepted operation is lost without another user invocation. Store enough verified operation text/policy in a durable pending admission record or atomically create the root with consumption, then scan/recover pending receipt owners without requiring a new Host turn. Do not relabel lack of a job as “nothing to recover”.
- **C1-R5: complete/checkpoint before receipt cache**. A valid write receipt exists; interrupt `_write_receipt` after complete's references were checked but before cache is written. Supervisor leaves complete CLAIMED and job ACTIVE with GENERAL_EFFECT_RECONCILIATION_REQUIRED on repeated ticks. Complete has no external side effect needing blind-retry prohibition: reconstruct from durable request_spec, revalidate refs and completion obligations, then record receipt/lifecycle. If refs changed, record a failed completion with the actual reason so the worker can correct it. Same approach applies to checkpoint. Add process-death variants of these exact windows.

**Current decision stays CHANGES_REQUIRED before C1 execution freeze** for these two reproducible recovery gaps. No new P0 or architecture contradiction was found. Continue repairs; no user permission or repeated Resume review is needed.


## Recovery closure recheck — same C1 review

The two remaining reproduced runtime recovery gaps are now **CLOSED for the tested component paths**. Independent results are retained in `c1-recovery-closure-checks.json`:

- Original claim-before-create crash: erase Host history, rebuild R1 projections, supervisor resumes one job and one separate Session/prompt, Mission count stays zero. Subsequent tick does not duplicate it.
- Original valid complete-before-cache crash: supervisor rechecks durable refs/effect obligations, records the receipt, and completes the job in the same tick. The new source handles checkpoint similarly and records FAILED when a reference changed.
- Exact authorization deadline, not merely nine hours later: at original observed_at + 8h, recovery returns GENERAL_EXECUTION_LEASE_EXPIRED, with zero created jobs/Sessions. It does not renew the lease from recovery time.
- Legacy receipt with operation_text absent: state is identical after projection rebuild, replay remains fresh=false, the optional field remains absent, and it does not start an ungrounded recovery job. This compatibility check does not infer text from old conversation.

Fresh independent suites: **26 execution tests / 9.563s; 17 interaction-receipt tests / 4.216s; 20 typed-root tests / 2.732s, all OK**. The typed-root suite includes the frozen old-Mission bytes/fingerprint/hash oracle. These are component checks in the incremental worktree, not final package/L4/Windows qualification.

### Compatibility assertion still needs correction/qualification

The implementer raised the Interaction manifest to 1.1.0 intending to make old composition reject writable downgrade. **The version bump alone does not implement that guard.** Independent check creates a composition advertising Interaction extension_version=1.0.0 over a new store containing operation_text; `assert_writable_compatible()` returns normally. Evidence: `c1-manifest-version-guard.json`. This is a version-guard counterexample with otherwise current reducers, not a claim that an entire old binary was executed.

Raw `durable_core/subjects.py:assert_runtime_compatible` checks registered root version, event type and event schema, not manifest extension_version. The persisted claim still uses root_version=1 / the same event type. The historical payload reader may reject unknown fields when that root is read, but that is not a proven global writable downgrade fence.

Minimum next action: implement and independently test an actual compatibility fence or explicitly retain this as an upgrade/old-runtime qualification gap; do not describe the manifest-number change itself as downgrade protection. Existing old-event bytes must stay unchanged. Unmodified historical executables cannot be assumed to understand a newly introduced guard; package/launch/upgrade exclusion and evidence scope must be honest.

The five actual execution/recovery counterexamples previously reported are repaired at the tested scope. This review therefore supports proceeding with remaining C1 controls and C2–C4 work, while **full C1 freeze and writable-downgrade qualification remain pending**. No architecture contradiction or new external authorization requirement has been found.


## Atomic intent-event and compatibility verification — current component decision

**REVIEWED_COMPONENT_REGRESSION_PASS.** The reviewed GeneralWork execution and recovery changes have no remaining reproduced P0/P1 blocker from this review. This permits committing this component and proceeding; it does not freeze full C1 or qualify missing controls, all-role context/rotation, Windows terminal, installed product or final L4.

Reviewer reread the actual diff and existing R1 command transaction. The claim handler now emits the historical claimed event without operation_text, plus `interaction.general_intent_recorded.v1` in the **same command transaction**. The new reducer validates root/entity/actor, CLAIMED state, General intent kind, no duplicate text, matching request digest and bounded text. Old no-text claims stay on the original one-event path. The 1.1.0 manifest number is release identity; the actual guard is the old registry's rejection of the new event type.

Fresh independent execution: **28 General execution tests / 10.035s; 17 Interaction receipt tests / 4.101s; 20 typed-root tests / 2.633s — all OK (65 tests)**. This includes:

- An old event-owner composition, with the new event removed from both extension and root registration, rejects compatibility admission, rebuild and new Mission write as ROOT_EVENT_UNSUPPORTED. Full SQLite logical dump remains unchanged across the rejected operations.
- Interruption before the second event reduction and after both event inserts rolls back command/events/receipt state to zero. Successful claim has two events with one command_id. Existing R1 transaction provides atomicity; no new cross-transaction recovery window was introduced.
- Earlier source-operation recovery, exact deadline, read/complete crash recovery, duplicate process call, actual process death after disk effect and POSIX concurrent-edit preservation regressions continue to pass.
- Frozen old-Mission bytes/fingerprints/hashes remain equal. Optional legacy text-absent receipt replay is preserved in the earlier independent counterexample closure evidence.

Source fingerprints are in `c1-intent-event-source-seal.json`; this is an incremental worktree source seal, not a final commit/package seal. The “old composition” proof is specifically the registered old event-owner contract using the current compatible core. It does not claim that every unmodified historical launcher/binary was executed; installed upgrade/downgrade behavior remains a packaging qualification responsibility.

**Finding closure:** C1-R1, R2, R3, R4 (POSIX tested scope), R5, and the ineffective-manifest-only guard assertion are closed by the recorded repairs and negative controls. Windows displaced-object/ReplaceFile cases remain C4 validation obligations. Mission control/update/HumanGate wiring and real no-progress RuntimeDiagnosis remain explicitly outside this component closure.

TASK_DIFFICULTY = HARD. REASONING_RECOMMENDATION = HIGH for subsequent context/fencing and Windows review; ordinary follow-on product wiring can continue at MEDIUM.
