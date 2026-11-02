# RC7.2 Current Construction Checkpoint

Status: **TRUTH_COLD_START_REPAIR / SAME_HEAD_QUALIFICATION_PENDING / FIELD_HOLD**

BASELINE_HEAD=07835859b49605ca2906c13e54f4d4449f5a310c
CONTRACT_SET=docs/rc7.2/00..05 + 07 + 09

## Current verified facts (2026-11-02)

The baseline's platform run 41288965091 failed on both Windows and Linux.
Historical CI PASS recorded in the ledger does not qualify the current HEAD.

This repair adds an explicit, idempotent RC7.2 durable schema bootstrap and
registered-bucket lazy initialization in Projection, including version indexes.
Unknown event and projection types remain fail-closed. Runtime bootstrap does
not launch workers, execute tools, acquire leases, or manufacture PASS evidence.

IMPLEMENTED_CLAUSES: R1 consistency / deterministic replay / disposable sessions;
CT-17 and the durable node schema requirements in 01/03/05.
UNIMPLEMENTED_CLAUSES: no new N7 admission implementation in this repair;
Q3 real target Linux, Q4 offline payload, Q5-Q8 real field acceptance outstanding.
FIELD_EVIDENCE_STATUS: NOT_AVAILABLE; field_verified=false; BANK_FINAL=NO.
KNOWN_DEVIATIONS: local smoke uses macOS Python 3.9, not Windows/Linux evidence.

## Test evidence at repair preparation

- Focused N2/N5/N6: 22 passed.
- New independent-process cold-start tests: 5 passed.
- Full isolated RC7.2 + inherited RC7: running at preparation time.
- Same-HEAD Linux/Windows Q1 and clean-unpack Q2: pending new commit CI.

## Next step

Read actual branch HEAD and same-HEAD CI. Close all isolated regressions and
Windows/Linux qualification before freezing N6 or proceeding to new N7 work.
Download the exact-lineage Q2 package only after clean-unpack verification.
Q3 requires an approved target machine and external trusted attestation.
Do not call an engineering candidate an offline turnkey or BANK_FINAL release.
