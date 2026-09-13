# C2 Context / Session Recovery — Raw Source Closure Review

## Authority and identity

- ArchitectureBaseline: v7 / FROZEN / UNCHANGED
- Architecture Drift: NO
- Engineering branch: `work/v1.13.0-recovery-turnkey-validation`
- Reviewed source-bearing head: `ca3027a0b72e7b70f88e2647da4519d7b95cc8f2`
- Evidence-only head after qualification record: `6451558cf7f357d340200ea2943d80151c1016bc`
- Windows C2 workflow: `V4 C2 context qualification`
- Workflow run: `34790510182 / success`
- Windows job: `103813731728 / success`
- Exact-host artifact: `10328431337`
- Artifact digest: `sha256:bf0f20b2a7e5c91c5d96731d9b5b83535207956e44609d2e9128d13fe3ec5edb`
- Exact host: official OpenCode 1.18.3 Windows x64
- Host asset SHA256: `68bc62930f6cb5755e0409aa9de0bb270a66ed2b8c9cf0c029e9f2287ed5486e`

## Decision

```ini
C2_SOURCE_AND_EXACT_HOST_CLOSURE_REVIEW = PASS
C2_ENGINEERING_COMPONENT_GATE = PASS
C2_REAL_AUTHENTICATED_MODEL_GATE = PENDING
C2_FINAL_INSTALLED_INTERACTIVE_TUI_GATE = PENDING
C2_OVERALL = NOT_FROZEN
ARCHITECTURE_CHANGE_REQUIRED = NO
HARD_DEPENDENCY_FAILURE_FOR_C3 = NO
C3_ENGINEERING = AUTHORIZED_TO_START
```

This is not a claim that a bank model, final installed package, or human-visible TUI has already been qualified. It is a source + actual Windows + exact OpenCode host closure of the C2 implementation substrate.

## Raw-source findings

### 1. Final pre-provider admission is a real fail-closed boundary

`.opencode/plugins/aitest-context-governor.js` retains the live message/system/params references through OpenCode's hook sequence and executes admission in `chat.headers`, after the full `chat.params` chain and before provider transport.

The gate includes:

- system bytes,
- full message/history bytes including tool arguments/results,
- permitted tool definition/schema bytes,
- final params/options bytes,
- model context limit,
- independent model input limit when advertised,
- effective output-token reserve,
- message/tool framing reserve.

Unserializable request structures, missing model limits, or Runtime admission errors fail closed before provider transport. The implementation explicitly labels its token estimate as conservative UTF-8 byte upper-bound accounting rather than pretending to possess an exact provider tokenizer.

### 2. Primary recovery is rooted in R1, not an operational session pointer

`PRIMARY_INTERACTION` owns logical Director identity, host realm, session binding, epoch and lease. A Session that merely still exists is not sufficient for reuse. Pressure/poisoned state fences the predecessor and advances the durable epoch.

Old-session calls are rejected through current binding/epoch authority rather than trusted because a Host session ID exists.

### 3. Current-turn replay is exact and lossless-or-fail-closed

Primary recovery does not fall back to "latest user message." It requires the exact Host message identity for the current turn.

- missing exact message identity => fail closed;
- non-text/file/attachment turn => fail closed rather than silently dropping parts;
- replay text has a bounded byte budget;
- the replay digest is bound into the durable recovery identity.

This prevents a previous user instruction from being accidentally replayed after a context overflow.

### 4. TUI follow precedes replay

Primary recovery targets a clean successor, invokes the OpenCode 1.18.3 TUI session-select path, and only then begins the replay send.

A TUI-follow failure leaves the recovery journal in CLAIMED/targeted state with no replay message sent. A later recovery tick retries the control-plane follow first.

The final human-visible installed TUI still requires L3 interactive qualification; the engineering contract and host API path are closed here.

### 5. Crash window is side-effect safe

Primary replay has a durable journal:

```text
CLAIMED
→ TARGETED
→ SENDING
→ ACCEPTED
```

The transition reducer is pure; nested recovery journals are deep-copied so command validation cannot mutate the input state before event reduction.

If the Host accepted the user turn but the Runtime lost the acknowledgement:

- R1 remains SENDING;
- restart reads the exact successor Host message;
- exact digest readback upgrades the journal to ACCEPTED;
- no second send occurs.

If readback cannot prove acceptance, the state is RECONCILE_REQUIRED / UNKNOWN_SIDE_EFFECT and no blind resend is allowed.

### 6. Mission workers and GeneralWork retain durable lineage

Mission Planner/Worker pressure is persisted in R1 session observation state. Fresh Host observations cannot erase a final-request admission block before rotation. G2.1 rotation preserves logical agent/task/root-attempt lineage.

GeneralWork/RuntimeDiagnosis use their existing typed job root, durable epoch and dispatch journal. Context recovery advances the General epoch rather than creating a fake TestMission or second runtime truth. Prompt acceptance uses Host readback reconciliation.

### 7. Regression and actual-host evidence

Current-head Windows qualification:

```text
Context Governor plugin component        PASS
Primary recovery                         16/16 PASS
Final Context Admission                  13/13 PASS
All-role repeated recovery               2/2 PASS
General execution/reconciliation         33 tests PASS / 2 platform skips
>=10MB class context stress              PASS / two rotations
```

Exact OpenCode 1.18.3 provider-boundary qualification on the same source head:

```text
ALLOW_REACHES_PROVIDER                       PASS
BLOCK_1_PREVENTS_PROVIDER                    PASS
SUCCESSOR_1_BOOTSTRAP_REACHES_PROVIDER       PASS
BLOCK_2_PREVENTS_PROVIDER                    PASS
SUCCESSOR_2_BOOTSTRAP_REACHES_PROVIDER       PASS
WORKER_TWO_DURABLE_ROTATIONS                 PASS
PRIMARY_PLUGIN_BLOCK_REPLAYS_ON_CLEAN_SUCCESSOR PASS
PRIMARY_CRASH_AFTER_HOST_ACCEPT_READBACK     PASS
TWO_DURABLE_ROTATIONS                        PASS
provider_request_count                       7
blind_resend                                 false
R1 cursor                                    66
```

The recording provider is intentionally deterministic and local. It proves the OpenCode host/plugin/provider transport boundary, not bank-model semantics.

## Residual gates carried forward

The following are mandatory but are not source blockers for C3 construction:

1. `C2_REAL_AUTHENTICATED_MODEL_GATE`
   - use the existing `tools/recovery/qualify_context_real_model.py`;
   - preserve the user's Host model/provider authentication;
   - run two context recoveries with a real model;
   - no fixture provider may satisfy this gate.

2. `C2_FINAL_INSTALLED_INTERACTIVE_TUI_GATE`
   - final Windows package;
   - standard user;
   - Git Bash launch path;
   - visible TUI follows successor without manual `/sessions`.

These remain required before final V1.14 qualification.

## C3 entry contract

C3 may now build on the passed C2 substrate. It must not introduce a second Mission runner or durable truth.

C3 construction target:

```text
R1 Event Stream
  → Supervisor / Scheduler / Router
  → autonomous progress controller
  → no-progress Diagnosis / replan
  → busy / quota / HumanGate / pause / stop exclusions
  → bounded auto-wake
  → business side-effect intent / receipt / reconcile
  → TEST_SUFFICIENCY convergence
```

The user conversation is not the execution clock. `DETACH != PAUSE != STOP`. A heartbeat is not progress. Session creation must not be used to evade model quota.

