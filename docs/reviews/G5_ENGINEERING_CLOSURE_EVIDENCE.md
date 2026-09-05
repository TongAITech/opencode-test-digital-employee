# G5 Engineering Closure Evidence

## Verdict boundary

```text
G5_ENGINEERING_PASS_CANDIDATE =
SUBMITTED_FOR_00_9_REVIEW

G6 =
HOLD
```

This file is engineering evidence only. It does not freeze or close G5, authorize
merge of PR #2, or authorize G6.

## Repository and authority identity

```text
Canonical repository = TongAITech/opencode-test-digital-employee
Branch = work/g5-defect-truth
EC7 starting head = 9c9652406ad075be91fad8c03060e05c9f980da2
Evidence commit parent head = 9c9652406ad075be91fad8c03060e05c9f980da2

Frozen CodeContract blob = fd0c85ef7ecbe01e990609b3e7e6f7f6490d5842
Frozen ExecutionContract blob = 361d791741b7ddf2aaa1bdfda5ec479187c3c2e4
Frozen G1-G4 runner blob = b006cecb48673a5b8735dda9e1b645ebafe7f1fc

Canonical frozen main = 4edd78536633d4258705c6083fe55b44e51f54bb
PR #2 = DRAFT / OPEN / UNMERGED
PR base = main
PR head = work/g5-defect-truth
```

The three frozen blobs were re-read mechanically after validation and were
unchanged. Remote `main` was re-read as the canonical frozen main. The worktree
was clean at the start of the evidence rerun.

## EC0-EC6 engineering status

The inherited 00.9 Governance Authority records EC0 through EC6 as PASS. The
final EC7 focused result also reports all corresponding progressive milestones
green:

- EC0: truthful RED oracle and execution completed.
- EC1: DEFECT_HUNTER router registration and non-durable contracts completed.
- EC2: product seam and exact worker binding completed.
- EC3: preconfirmation investigation and confirmation barrier completed.
- EC4: governed evidence deepening and durable recovery completed.
- EC5: defect confirmation policy, HumanGate, duplicate correlation, and exact
  R4.3 handoff completed.
- EC6: Director product surface and OpenCode Diagnosis canonical G5 surface
  completed.

The EC7 result reports `product_seam_green`, `worker_binding_green`,
`ec3_preconfirmation_green`, `confirmation_barrier_green`,
`ec4_governed_evidence_green`, `ec4_recovery_green`, `ec5_green`,
`director_surface_green`, and `opencode_surface_green` all true.

## EC7 focused validation

Exact command:

```bash
PATH="/usr/bin:$PATH" python tools/run_g5_validation.py --root . --wave EC7
```

Exact result summary:

```text
returncode = 0
status = PASS
wave = EC7
wave_expectation_satisfied = true
wave_oracle_ready = true
ec7_g5_focused_gate = PASS
g5_full_green = true
wave_failures = []
no_programming_exceptions = true
frozen_g1_g4_runner_exact = true
```

## Exact GREEN validation

Exact command:

```bash
PATH="/usr/bin:$PATH" python tools/run_g5_validation.py --root . --mode green
```

Exact result summary:

```text
returncode = 0
status = PASS
mode = green
suite_count = 6
all_g5_suites_accepted = true
g5_green = true
green_requires_runtime_behavior_in_every_suite = true
no_programming_exceptions = true
```

### Six-suite results

| Suite | Return code | Status | Fixture | Missing checks | Runtime GREEN | Accepted | Programming exception |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| `test_g5_product_path.py` | 0 | PASS | true | `[]` | true | true | false |
| `test_g5_worker_binding_and_recovery.py` | 0 | PASS | true | `[]` | true | true | false |
| `test_g5_adversarial_defect_truth.py` | 0 | PASS | true | `[]` | true | true | false |
| `test_g5_human_gate_and_duplicate_correlation.py` | 0 | PASS | true | `[]` | true | true | false |
| `test_g5_same_mission_e2e.py` | 0 | PASS | true | `[]` | true | true | false |
| `test_g5_opencode_surface.py` | 0 | PASS | true | `[]` | true | true | false |

## OpenCode canonical live probe

The OpenCode suite retained its TypeScript and agent boundary checks. The runner
also executed the real portable Python product boundary:

```text
python -m aitest_runtime.product_entry
g5
--role DIAGNOSIS
--action status
--payload {}
```

Probe result:

```text
canonical_substrate = ISOLATED_TEMP_RUNTIME_SPINE
returncode = 0
status = PASS
truth_source = R1_EVENT_STREAM
next_required_action = null
role = DEFECT_HUNTER
read_only = true
caller_prepared_AITEST_RUNTIME_SPINE_DB_required = NO
```

The temporary runtime-spine authority was construction-validation substrate
only and was removed automatically. The canonical runtime fallback rule was not
changed.

## Adversarial defect-truth matrix

The structured adversarial suite reports all of the following checks true:

| Probe | Required outcome | Structured check |
| --- | --- | --- |
| Single API 500 | Not confirmed | `single_api_500_safe_non_confirmed` |
| Error string only | Not confirmed | `error_string_only_safe_non_confirmed` |
| LLM 99% confidence | Not confirmed | `llm_99_confidence_safe_non_confirmed` |
| Static code suspicion | Not confirmed | `static_code_suspicion_safe_non_confirmed` |
| Wrong test data | Not confirmed | `wrong_test_data_safe_non_confirmed` |
| Stale expected result | Not confirmed | `stale_expected_safe_non_confirmed` |
| Auth/session expiry | Not confirmed | `auth_session_expiry_safe_non_confirmed` |
| CAT unavailable | Not confirmed | `cat_unavailable_safe_non_confirmed` |
| Conflicted evidence | Not confirmed | `conflicted_evidence_safe_non_confirmed` |
| Direct provider bypass | Rejected | `direct_provider_action_rejected_canonically` |
| Raw secret injection | Rejected | `raw_secret_injection_rejected_canonically` |
| G6 mutation | Rejected | `g6_mutation_rejected_canonically` |

```text
no_probe_persisted_confirmed_defect = true
```

## Same-Mission canonical E2E

The structured E2E suite reports:

```text
single_same_mission_chain = true
```

The runtime-proven chain is:

```text
G2 Task
-> DEFECT_HUNTER
-> G4 FAIL
-> UNEXPECTED_OBSERVATION
-> G5 exact admission
-> R3.6 TestAnomaly
-> DefectCandidate
-> evidence deepening
-> governed reproduction when required
-> durable typed references
-> EvidenceAssessment
-> CrossSourceCorrelation
-> Reproducibility
-> false-positive exclusion
-> CONFIRMED_DEFECT
-> RCA
-> R4.3 ConfirmedDefectLifecycle
```

The suite additionally proves exact G4 lineage, G5 v7 origin lineage without
rewriting frozen R3.6 history, bounded raw-payload-free WorkSets, durable
checkpoint recovery, current binding after rotation, and R4.3 handoff
idempotency.

## Frozen G1-G4 regression

Exact command:

```bash
PATH="/usr/bin:$PATH" python tools/run_wave2_validation.py \
  --root . \
  --output G5_WAVE2_VALIDATION_RESULT.tmp.json
```

Exact result summary:

```text
returncode = 0
status = PASS
fresh = true
combined = 434 / 434
failed_suites = []

original_267 = 267 / 267
wave2_new = 72 / 72
post_closure_22 = 22 / 22
closure_repair_new = 73 / 73
```

`G5_WAVE2_VALIDATION_RESULT.tmp.json` was removed after its structured result
was read. The frozen runner itself was not modified.

## Legacy truth and authority prohibition

The source and structured-result audit establishes:

```text
aitest_runtime/defects.py used by canonical G5 = NO
legacy SQL defect truth used by canonical G5 = NO
aitest.db used as Product Truth by canonical G5 = NO

new G5 SQLite store = NO
new G5 JSON store = NO
new G5 durable Event extension = NO

G5 direct provider execution = NO
G5 direct G3/G4 mutation shortcut = NO
G5 Plan mutation = NO
G5 Task mutation = NO
G5 Session ownership = NO

R4.3 fix mutation from G5 = NO
G6 behavior from G5 = NO
```

Mechanical evidence:

- Canonical G5 and `product_entry` contain no import or call to
  `aitest_runtime.defects` and no `AUTO_CONFIRMED` path.
- The G5 package contains only `contracts.py`, `admission.py`, `policy.py`,
  `service.py`, and `__init__.py`; it has no store or extension module.
- The canonical extension inventory has no G5 extension. The product-path
  fixture reports `no_g5_durable_extension_registered = true`.
- The adversarial suite reports `legacy_defect_module_not_imported = true`,
  `legacy_auto_confirm_not_reused = true`, `no_second_store_files = true`, and
  `fix_and_session_mutation_attrs_absent = true`.
- The E2E suite reports `g5_does_not_execute_provider_directly = true` and
  `g5_does_not_create_workgraph_task_directly = true`.
- The Director product suite reports
  `director_open_investigation_does_not_create_plan = true` and
  `director_open_investigation_does_not_create_task = true`.
- OpenCode checks report that the helper owns neither provider execution nor
  Session lifecycle.

## Final governance boundary

At evidence creation time:

```text
PR #2 = DRAFT / OPEN / UNMERGED
main = 4edd78536633d4258705c6083fe55b44e51f54bb / UNCHANGED
product source modified by this rerun = NO
validation runners modified by this rerun = NO
G6 = HOLD

G5_ENGINEERING_PASS_CANDIDATE =
SUBMITTED_FOR_00_9_REVIEW
```
