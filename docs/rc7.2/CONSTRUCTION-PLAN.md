# Signed N7 tool dispatch and frozen Oracle — 2026-11-02

status: COMPONENT_TESTED / OVERALL_INCOMPLETE / NO_DELIVERY
implemented: adapter dispatch from current signed preparation; scoped tool check;
durable intent before external I/O; task and binding RUNNING before invocation;
JSON raw receipt with hash; exceptions retain class only; unknown-side-effect
interruptions and failures never automatically re-invoke the same attempt.
Permanent exclusive-create per-dispatch claims provide fail-closed exclusion on
the same local event-store path. A claim without an intent requires diagnosis.
This is not global event-store locking or Data/Browser cross-process exclusion.
Oracle: reads only persisted receipt + current frozen N6 predicates; emits
content-addressed assertion result. Even a matching Oracle leaves task RUNNING
and resources held pending real cleanup/reverification and finalization.
Evidence: final dispatch/cold-process replay suite 14 passed; final combined
chain 77 passed / 2 existing collection warnings. Cold replay added afterward
and verified independently. No external target was exercised.
Adapters are injected construction fixtures. No target or Field PASS is claimed.
Remaining: production adapters; inherited execution_attempt and Evidence records;
actual cleanup + data verification; independent N8; N9/N10; product controller.
DELIVERY_AUTHORIZED=false; FIELD_VERIFIED=false; BANK_FINAL=NO.

---

# Signed N7 preparation and resource ownership — 2026-11-02

status: COMPONENT_TESTED / OVERALL_INCOMPLETE / NO_DELIVERY
implemented: exact-task scheduler leasing (including economy deferral); signed
Worker identity/task/Attempt scope, deny wildcard and professional artifact writes;
restore and verify leases on restart; deterministic data reservations and browser
auth-context selection; fresh takeover session/Attempt with parent lineage.
rollback_policy: reservation rollback only before tools start; RUNNING refuses it.
replay_fixes: tuple/list normalization; N6 content-addressed recompilation ignores
new wall-clock compiled_at and cannot be invalidated by unrelated valid N7 leases.
N6 still forbids lease/result material inside its own executable contracts.
evidence: final focused chain 64 passed (2 collection warnings); browser auth
context selection/revalidation and preparation subset 21 passed. External system calls are injected fixtures.
remaining: execution receipts, actual cleanup/data re-verification, independent
N8 diagnosis, N9/N10 and product ingress. No transport release is authorized.

---

# N7 canonical planning and executable Oracle checks — 2026-11-02

baseline_head: ab863663751d5b4271288bb738508ea2ce006b09
status: COMPONENT_COMPOSITION_TESTED
implemented: actual PersistentAdaptiveTaskDecomposer consumer; approved canonical
Case/Obligation → persisted snapshot/ETUs → RC7 WorkItems; same-input replay
resumes existing work; plan use revalidates sources, scope, Case denominator,
ETU state and snapshot digest. L1-L7 tool family must be explicitly established
by N1; labels cannot turn API work into Browser/performance/security work.
Oracle correction: executable N4 materialization must include actual_path,
operator and expected value where required. N6 copies approved machine checks;
N7 rejects descriptive Oracle labels as executable assertions.
evidence: planning 4 tests passed; machine-Oracle/source/planning combination
34 passed; additional descriptive-Oracle rejection test passed in later focused run.
remaining: signed preparation, actual execution/cleanup, independent diagnosis,
convergence and product controller integration. Overall INCOMPLETE.
next_atomic_step: signed scoped Worker/Attempt + deterministic resource acquisition.

---

# Canonical N4 → N6 → N7 source bridge — 2026-11-02

baseline_head: 123eaa2a0a31337938ae8a9a11e4f71f83762a41
phase: CANONICAL_DESIGN_EXECUTABLE_INTEGRATION
status: CODE_COMPLETE_COMPONENT_COMPOSITION
implemented: approved hash-verified N4 candidate assets → canonical TestObligation;
exact original Case + explicit reviewed execution materialization + current
canonical N1 route and verified N5 data → N6 compiler/gate → N7 preflight.
legacy_policy: old N4 candidates replay unchanged; missing concrete execution
inputs/request/cleanup blocks at N6 rather than manufacturing a runnable Case.
N7 now rechecks approved Case semantics, canonical Obligation and actual N1
binding bytes; read-only N1 revalidation cannot create a new binding.
test_evidence: 41 focused passed, including actual N1–N6 service composition
with external DSH/tool I/O fixtures; not Field evidence.
remaining: persistent N7 planner/WorkItem consumers, signed fresh workers,
resource acquisition/cleanup, execution/independent diagnosis, N10 and product wiring.
next_atomic_step: connect canonical assets and admissions to persistent N7 planning.
OVERALL_STATUS: INCOMPLETE

---

# N7 admission construction slice — 2026-11-02

baseline_head: 9476b57cf70056f958352762c14a5ec3b2b2151d
phase: N7_EXECUTION_ADMISSION
clauses: 01 sections 3/5/9; 02 Phase 3, CT-01/04/17; 03 section 10
status: CODE_COMPLETE_COMPONENT_ONLY
implemented: read-only current N1-N6 active gate/delivery checks, immutable N6
content identity, full canonical Case denominator, live hash-verified N3/N4/N5
inventory, current verified resources/Evidence, DataRef and expiry checks,
replay-safe admission, revalidation before use, no leases/results on admission.
test_evidence: 25 focused passed (11 new N7 + N5 inventory/resolution + cold start).
field_evidence: unavailable
remaining: actual planning/WorkItem/worker/resource/tool consumer; result/diagnosis
and product wiring; N4 canonical asset promotion/N6 canonical compiler integration.
next_atomic_step: canonical approved N4 assets and N6 contract adapter, then
persistent N7 planning and actual dispatch. Overall remains INCOMPLETE.

---

# Authoritative construction correction — 2026-11-02

OVERALL_STATUS=INCOMPLETE; DELIVERY_AUTHORIZED=false.
User clarified: finish all design implementation before producing delivery.
The portable-preparation interpretation below is superseded.

Read DESIGN-CONSTRUCTION-RECONCILIATION.md for phase/GAP/CT obligations,
located components, confirmed integration gaps and corrected construction order.
A component's CI PASS is not whole-phase or whole-product implementation closure.
Next atomic slice: N7 ExecutionAdmission, followed by actual execution/resource/
diagnosis integration and product entry wiring. Field evidence remains absent.

---

# Portable transport preparation — 2026-11-02

User delivery scope: first provide transport, final acceptance occurs on site.
Functional repair source: 55ca13f77775fbb747381261a2a51aa211469c57.
Construction run 41377525518: PASS (Python 3.8/3.11 + inherited regression).
Q2 run 41377525556: PASS (clean unpack, package Python, R1/session/Git Bash).
Q1 run 41377525473: Linux passed, Windows pending at checkpoint preparation.

New workflow prepares all runtime-lock payloads on Windows at build time,
reseals the RC7.2 identity, and verifies a second clean extraction. It is
preparation for transport; it does not advance Q3/Q4 or claim field acceptance.
Next: same-HEAD CI and complete portable artifact; final acceptance on site.

---

# Current repair entry — 2026-11-02

phase: TRUTH_COLD_START_REPAIR
baseline_head: 07835859b49605ca2906c13e54f4d4449f5a310c
status: IN_PROGRESS
clauses: R1 replay consistency, complete known schema registration, CT-17
commits: see current git log
ci_runs: baseline 41288965091 FAILED; new same-HEAD runs pending
field_evidence: unavailable; Q3 target HOLD; BANK_FINAL=NO
open_gaps: same-HEAD Q1/Q2, N7 admission, Q3-Q9 field/offline qualification
next_atomic_step: full isolated tests and same-HEAD platform qualification

The entries below are historical; their earlier PASS does not qualify current HEAD.

---

# RC7.2 Construction Plan / Checkpoint Ledger

Status: **REPOSITORY_CONSTRUCTION_CI_PASS / Q1_CI_PASS / Q2_CI_PASS_ENGINEERING_ONLY / Q3_PACKAGE_BOUND_ATTESTATION_CONTRACT_PASS_TARGET_HOLD / FIELD_VALIDATION_PENDING**

Future sessions MUST read current branch HEAD, same-HEAD CI, frozen contracts, this ledger and `CURRENT-CHECKPOINT.md`. Live repository/R1/CI/Evidence truth overrides stale chat history or stale SHAs.

## 1. Repository construction

Phase 0-9 repository construction is closed at repository CI level.

Original repository functional head before qualification additions:

- `d43f233ace9c691f881a8b5e0d5be23257b9c5f5`
- run `40737549865`
- RC7.2 contracts: `206 passed` on Python 3.8 and Python 3.11
- inherited RC7: `492 passed, 1 skipped`

Latest same-head qualified functional source:

- `495a12f35430443d7f9cfb59ad6691894a8c8125`
- Construction run `40815666704`
- RC7.2 contracts Python 3.8: `253 passed`
- RC7.2 contracts Python 3.11: `253 passed`
- inherited RC7: `492 passed, 1 skipped`

The Construction workflow includes `rc7_release/**`, so qualification/release-layer changes cannot bypass full same-head contract validation. Repository CI is not Field validation and not BANK_FINAL.

## 2. Frozen qualification sequence

```text
Q1 source-platform engineering baseline
 -> Q2 Windows clean-unpack
 -> Q3 target Linux
 -> Q4 offline/portable delivery
 -> Q5 real Browser/BSK
 -> Q6 real Human Approval verifier
 -> Q7 real ReleaseBatch N1-N10 mission
 -> Q8 recovery/failure exercises
 -> Q9 BANK_FINAL decision
```

Qualification contract: `07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`.

Q4 qualification MUST NOT begin while Q3 remains target-environment HOLD.

## 3. Q1 — Source platform engineering baseline

Status: `CI_PASS_ENGINEERING_ONLY`.

Same-head run: `40815666700` on `495a12f35430443d7f9cfb59ad6691894a8c8125`.

- Windows engineering: SUCCESS
- Linux engineering proxy: SUCCESS
- Q1 summary: SUCCESS
- Windows artifact id: `12872207615`
- Windows artifact digest: `sha256:22d39d64264d70032d03e2f100be49306f68ee16ee90ee1f98b3bcea91391183`
- Linux proxy artifact id: `12872466187`
- Linux proxy artifact digest: `sha256:88a4dabafec41ad5790cd53c0ad9368c3c44ad2df5446a9361865600def6d65d`

Q1 proves Windows and generic Linux engineering portability only. Generic Linux is not target 信创 Linux Field evidence.

Checkpoint: `checkpoints/Q1-SOURCE-PLATFORM-BASELINE-CI-PASS.md`.

## 4. Q2 — Windows clean-unpack

Status: `CI_PASS_ENGINEERING_ONLY`.

Same-head workflow run: `40815666705` on `495a12f35430443d7f9cfb59ad6691894a8c8125`.

### Q2-A

- exact-lineage package build: PASS
- delete build root + clean re-extract: PASS
- package-local Python / identity / strict checksum verification: PASS
- artifact id: `12871584284`
- artifact digest: `sha256:e61738fa3ba5b7de283922cacfca8652281447d75656b780fee155757a3e6795`

Content-level transport inspection confirmed:

- embedded `SOURCE_COMMIT` = `495a12f35430443d7f9cfb59ad6691894a8c8125`;
- `packaging/rc7.2/Q3-FIELD-HANDOFF.sh` present;
- `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh` present;
- `packaging/rc7.2/AITEST.sh` present;
- `rc7_release/rc72_target_linux_attestation.py` present with package-evidence binding;
- `rc7_release/rc72_target_linux_reality.py` present with the strengthened release path.

### Q2-B

- exact Q2-A transport download: PASS
- second clean extraction: PASS
- clean-package R1 / Session A -> B -> C continuity: PASS
- active session: `SESSION-C`
- chat history transferred: `false`
- business root: `RELEASE_BATCH`
- runtime control backbone: `N1_N10_MISSION_GRAPH`
- real Git Bash entrypoint engineering probe: PASS
- isolated profile: `rc7.2-bank`
- mature RC7 delegate path: `packaging/rc7/AITEST.sh`
- `offline_payload_verified=false`
- `field_verified=false`
- `bank_final=false`
- artifact id: `12872715575`
- artifact digest: `sha256:e874280b8eddd0c10d1e69fc1957ab114f2462d76206c81d169bddf599592706`

Complete offline DSH/plugin/tool payload qualification remains Q4. No Q4 payload claim was used to close Q2.

Checkpoint: `checkpoints/Q2-WINDOWS-CLEAN-UNPACK-CI-PASS.md`.

## 5. Q3 — Target 信创 Linux

Status:

```yaml
reality_binding_contract: CI_PASS
target_probe_contract: CI_PASS
field_handoff_contract: CI_PASS
external_attestation_boundary: CI_PASS
generic_linux_negative_control: PASS
target_linux: HOLD_TARGET_ENVIRONMENT_BINDING_REQUIRED
target_linux_verified: false
field_verified: false
bank_final: false
```

Qualified functional head: `495a12f35430443d7f9cfb59ad6691894a8c8125`.

Workflow run: `40815666715`, SUCCESS.

Artifact:

- id: `12872261627`
- name: `rc72-q3-generic-linux-negative-control-495a12f35430443d7f9cfb59ad6691894a8c8125`
- digest: `sha256:099237561300c9e049a2d4dbf8972e6fdccd2219a1294fbd103199cec38548f1`
- Q3 contracts: `28 passed`

Implemented and qualified on the same functional SHA:

1. packageable `packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh`;
2. packageable `packaging/rc7.2/Q3-FIELD-HANDOFF.sh`;
3. observation-only OS/arch/Python/shell/source/runner identity capture;
4. transported-package evidence with critical-file SHA-256 digests;
5. no network install and no self-approval in probe/handoff;
6. attestation request bound to exact observation digest and transported-package evidence digest;
7. trusted external verifier boundary restricted to approved verifier kinds;
8. fail-closed source, dual-digest and machine identity matching;
9. local-file/self-reported/model approval remains untrusted;
10. the legacy reality positive path delegates to the same strong attestation evaluator, so no weaker PASS bypass remains;
11. Q3 can never set `bank_final=true`.

The engineering handoff generated on generic Ubuntu remains deliberately awaiting external attestation. Its transported-package evidence digest was:

`fca93c2bf518ee524d2edd0a98f4d58bfcc8746358c3e169e16c7a11ff718154`

Content-level generic Linux evidence remains deliberately HOLD:

```yaml
source_commit: 495a12f35430443d7f9cfb59ad6691894a8c8125
platform_family: Ubuntu
platform_release: "24.04"
architecture: x86_64
runner_kind: GITHUB_HOSTED_GENERIC
status: HOLD
reason: GENERIC_LINUX_PROXY_NOT_TARGET
target_linux_verified: false
field_verified: false
bank_final: false
```

Workflow SUCCESS proves the Q3 mechanism, package handoff and negative-control policy behave correctly. It does **not** mean a real target 信创 Linux environment passed qualification.

Trusted verifier kinds remain restricted to:

- `APPROVED_SELF_HOSTED_TARGET_LINUX`
- `BANK_FIELD_TARGET_LINUX`

Generic hosted Ubuntu, local file approval, model assertion, self-reported approval, missing package evidence, source mismatch, observation-digest mismatch, package-evidence-digest mismatch or machine mismatch cannot promote Q3.

Checkpoint: `checkpoints/Q3-TARGET-LINUX-REALITY-CONTRACT-HOLD.md`.

### Next Q3 slice

`Q3_REAL_TARGET_INVOCATION_AND_TRUSTED_ATTESTATION_BINDING`

Next execution must use an actual approved target 信创 Linux environment and the packageable field handoff from exact source lineage. The real target handoff must create observation + transported-package evidence + request + manifest. A trusted external attestation must bind to the same source, observation digest, package-evidence digest and machine identity before Q3 may PASS.

Until that real target evidence exists:

- `target_linux_verified=false`
- `field_verified=false`
- Q3 remains HOLD
- Q4 qualification remains blocked

## 6. Later gates

```yaml
q4_offline_portable: NOT_RUN
q5_real_browser_bsk: NOT_RUN
q6_real_human_approval: NOT_RUN
q7_real_release_batch: NOT_RUN
q8_failure_recovery: NOT_RUN
q9_bank_final: NO
```

## 7. Anti-drift rule

Always verify:

```text
current work/rc7.2 HEAD
+ same-HEAD source
+ same-HEAD CI/check-runs
+ frozen 00-05 and 07 contracts
+ CURRENT-CHECKPOINT.md
+ this ledger
+ R1/evidence where applicable
```

If these differ, live repository/R1/CI/Evidence truth wins and the ledger must be corrected in the same construction turn.
