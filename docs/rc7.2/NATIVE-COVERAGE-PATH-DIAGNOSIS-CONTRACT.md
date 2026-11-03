# Native observed-path routing and independent review

`NativeCoveragePathDiagnosisService` consumes the concrete actual coverage intake
and its read-only audit. Its current evidence-supported classification is
PATH_NOT_REACHED: the authoritative normalized report records uncovered units
for a uniquely mapped original obligation, and all original primary/approved
secondary Cases and Attempts for that obligation have accepted N7 proof. This
is an observation requiring N8 investigation. It is not an explanation of why
the path was missed, a product defect, a bounded repair plan or repaired coverage.
No caller supplies a reason, candidate selection, percentage or PASS flag.

Zero/ambiguous mappings remain investigation HOLD without a diagnostic process
or invented professional work. The implementation never picks one of multiple
candidate obligations. Other gap reasons require their distinct causal evidence;
this path does not infer missing data, missing analysis, executable failure,
unreachability or approved exclusion from coverage alone.

## Actual process and WorkItem flow

The service binds original intake, captured report hash and fixed report scope,
unique Requirement/SST/obligation mapping, accepted full original Case/Attempt
IDs and source hashes, original policy and accepted N7 Gate. An actual canonical
DIAGNOSIS WorkItem consumes the measurement Artifact and its original N1/N7
inputs. A signed IN_FLIGHT intent precedes the program invocation. The service
launches an actual isolated diagnosis process and a separate review process,
both over the same captured report and immutable execution facts. Each verifies
the body bytes; the reviewer independently recomputes and compares the candidate.
The parent recomputes the result and verifies exact request, output and error
capture hashes, distinct process IDs, exit codes and signed receipt scope.

The canonical routing Artifact, Evidence and independent Evaluation close only
the routing WorkItem. The gap is then CLASSIFIED/PATH_NOT_REACHED with actual
report and diagnosis evidence, and a canonical COVERAGE_PATH_INVESTIGATION
WorkItem is registered for N8 with original source artifacts and gap reference.
It remains pending, without a fabricated Evaluation or completed Attempt.
Classification creates no new Case, TestObligation or ETU and does not lower the
original release denominator.

These are deterministic program processes over captured evidence. This service
is not the DSH professional investigation worker, private provider profile,
all-role external-tool gate, business re-execution or complete N8 repair loop.
Those remain separate construction work. No business API, coverage endpoint or
other external effect is repeated by the diagnosis/review programs.

## Recovery and native N10

A returned signed diagnosis can resume metadata-only acceptance without another
process or HTTP read. IN_FLIGHT without an accepted process receipt remains
unknown and is not automatically restarted. Changed process bytes, validly
signed wrong scope/reason, changed Task/Artifact/Evidence/Evaluation or changed
classification/queued-work scope refuse acceptance. Original pre-intent task
registration/lease/start can reconcile its exact deterministic scope before the
first process intent; a foreign task is not adopted.

Read-only `audit` requires all accepted routing metadata and the existing
CLASSIFIED gap and N8 WorkItem. It launches no process, fills no metadata and
issues no external authority. Native N10 requires the same concrete diagnosis
provider whenever native diagnosis history exists; omitting it cannot regain
completion through raw terminal flags. Unattested RESOLVED/EXCLUDED status is
refused. Native post-repair observation/closure and approved exclusion providers
are still required before those later states can be accepted.

Engineering tests use real localhost report/business HTTP and separate actual
Python processes, with fixture source approvals. They do not establish vendor
Libra API origin, bank operation or Field/BANK_FINAL approval.
