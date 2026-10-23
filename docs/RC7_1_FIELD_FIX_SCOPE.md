# RC7.1 Field Fix Scope

RC7.1 is a bounded field-fix release built from RC7. It does not introduce the RC8 Center/Node architecture and must not relabel FIELD_REQUIRED bank bindings as PASS.

Baseline: `ac890eebeae96c9704d777e5ba8cac428f7a25b8` (`repair/rc7-nonblocking-dsh-bootstrap`).

## Release objective

Deliver one Windows bank-turnkey ZIP that preserves RC7 truth/authority invariants while fixing verified RC7 field failures and preventing false PASS.

## P0 fixes

### P0-01 DSH startup must not be blocked by plugin/package-manager work

Preserve the existing clone-first/nonblocking bootstrap repair. `AITEST.cmd` must never run `dsh plugin add/install` before starting DSH. Plugin persistence remains post-start and nonblocking.

### P0-02 Startup/model/session recovery must be bounded and diagnosable

Add a startup trace and watchdog around RC7-owned startup phases. Distinguish package verification, DSH profile preparation, patch generation, host launch, provider/model readiness, and session recovery. RC7-owned stages must never wait forever. A provider/model/session problem must be reported as DEGRADED/RECOVERY_REQUIRED rather than a generic permanent `LOADING` state.

Because bank DSH internals are external to RC7, RC7.1 must not claim to fix an unverified DSH-internal behavior. It must provide a safe fresh-entry/recovery path that does not require replaying RC7 project truth from chat history; canonical R1 remains authoritative.

### P0-03 Worker launch failure / timeout truth

A DSH Worker timeout or launch error must persist stdout/stderr/session diagnostics and remain `ROUTING_INTEGRITY_FAIL`; it must never become execution PASS. Add a bounded retry/recovery policy only when the failure is retry-safe. Repeated worker launch failure must stop the affected task with actionable evidence rather than consume another long blind wait.

### P0-04 L1 Maven/JUnit reality gate

RC7.1 must reject stale Surefire/Failsafe XML and must not infer JUnit PASS from Maven exit code or pre-existing reports.

Required reality checks:
- record pre-run report inventory/fingerprints;
- execute the real configured Maven command;
- require post-run XML created or changed by the current run;
- parse test totals/failures/errors/skips from current-run XML;
- persist stdout/stderr/XML/command/tool identity as evidence;
- if offline dependencies are missing, return `BLOCKED_ENVIRONMENT` / dependency detail, never PASS;
- no stale XML contamination.

### P0-05 Evidence/provenance fail-closed

Execution PASS requires Actual + Oracle result + evidence refs. Director/agent narrative may not mint `TEST_COMPLETE`, `RELEASE_GO`, confirmed defect, or executable PASS without canonical R1 evidence. Evidence must carry producer/task/attempt/source identity sufficient to audit who produced it.

### P0-06 Capability self-check before autonomous testing

Before a Mission consumes a capability, RC7.1 must distinguish `NOT_PROBED`, `VERIFIED`, `DEGRADED`, `UNAVAILABLE`, and bank `FIELD_REQUIRED` states for at least DSH host/model route, Maven/JUnit, CodeGraph, Browser/Playwright/Chromium, Python/pytest, DB, CAT, 4A, k6/security tooling where packaged. Presence of a binary/plugin is not capability PASS.

### P0-07 Package identity and clean-unpack gate

Build a new RC7.1 identity. Final ZIP must pass clean-unpack, package-local Python 3.8 regression, SHA256 verification, toolchain qualification, nonblocking DSH bootstrap gate, and startup/recovery smoke. No runtime pip/npm/playwright install is allowed in the bank runtime.

## P1 fixes

### P1-01 Context growth / poisoned session avoidance

Do not make RC7 project recovery depend on loading a giant chat session. Persist and prefer R1-backed Mission/Task/Attempt/Cursor/evidence references. Add a safe operator action that starts a clean DSH entry session and resumes RC7 from canonical state when the previous chat/session is oversized or poisoned.

### P1-02 Failure classification

Keep at least these distinct: provider rate limit/auth, DSH launch timeout, missing capability, offline dependency missing, auth-required, route/method/oracle drift, endpoint unavailable, product failure. Do not collapse them into one generic worker/model failure.

### P1-03 Field validation status honesty

Preserve the RC7 Reality Certification boundary: L1-L3 may be READY only when current-run evidence proves it; L4/L5/L7 remain PARTIAL until real bank execution proves them; L6 remains BASELINE_ONLY until its real approved provider path is proven. Final release remains HOLD when bank-only evidence is missing.

## Explicit non-goals for RC7.1

- no RC8 Center/Node architecture backport;
- no fake provider or synthetic fixture used to close bank-only field gates;
- no replacement of R1 with chat/memory;
- no weakening Oracle/evidence gates to make CI green;
- no automatic change of business Oracle or security authorization policy.

## Qualification matrix

RC7.1 cannot be sealed unless all local/CI gates below pass:

1. Full `test_rc7_*.py` under Python 3.8 on Windows.
2. Clean-unpack package qualification.
3. Nonblocking DSH bootstrap: no pre-start plugin package-manager call.
4. Worker launch failure injection: timeout -> fail-closed + diagnostics.
5. Stale Surefire XML negative test: must not PASS.
6. Missing offline Maven dependency negative test: BLOCKED, not PASS.
7. Current-run JUnit XML positive fixture: Actual parsed from XML.
8. Capability self-check truth-state tests.
9. Evidence/provenance negative tests: no evidence -> no PASS/complete/release.
10. Startup/recovery smoke: package-owned startup stages bounded; clean-entry recovery available.
11. ZIP SHA256 + metadata + source commit recorded.

Bank-only gates remain explicitly FIELD_REQUIRED and are not a prerequisite for engineering package creation, but they are a prerequisite for declaring bank-final release PASS.
