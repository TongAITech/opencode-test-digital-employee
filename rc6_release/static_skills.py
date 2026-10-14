from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

# Full professional RC6 worker skill payload. These texts are materialized into
# the immutable delivery ZIP at build time so DSH can inspect every role before
# installation. Runtime installation copies these files byte-for-byte.
ROLE_SPECS: Dict[str, Tuple[str, str, str, str]] = {
    "pfc-requirement-analysis": (
        "BR/SR/TR requirement analysis",
        "Decompose every source requirement into atomic testable rules. Capture actor, trigger, precondition, happy/alternate/error paths, boundaries, state transitions, data constraints, dependencies, side effects and explicit trace refs. Record unknowns as gaps instead of assumptions.",
        "RequirementAnalysis with atomic requirement ids, source refs, rule/path/state/data/dependency matrices, risk and unresolved gaps.",
        "Every in-scope source item is traced; critical rules have paths, boundaries and state/data semantics; all unknowns are explicit and evidence-backed."
    ),
    "pfc-requirement-sufficiency": (
        "independent requirement sufficiency review",
        "Review stored requirement analysis independently against source BR/SR/TR evidence. Check missing business rule, role, boundary, state, error path, dependency, side effect and ambiguous wording. Never repair the analyzed artifact yourself; emit exact gaps to the owning analyzer.",
        "RequirementSufficiencyReview containing pass/fail, evidence matrix, gap ids, severity and repair targets.",
        "PASS only when no critical/high-risk evidence-backed gap remains; self-reported completeness percentages are ignored."
    ),
    "pfc-code-analysis": (
        "exact-revision code and impact analysis",
        "Bind the exact Git revision and changed files first. Use admitted Git and CodeGraph/source evidence to map diff -> symbols -> callers/callees -> routes -> persistence/external calls. Trace requirements to reachable implementation and identify changed/adjacent risk. Never guess API routes or call paths.",
        "CodeAnalysis with revision identity, changed symbols, graph/call-path evidence, authoritative routes, data touchpoints, requirement mappings and risk hotspots.",
        "All relevant changed symbols and reachable high-risk paths are evidenced; route/data claims have authoritative refs; unresolved graph gaps are explicit."
    ),
    "pfc-code-sufficiency": (
        "independent code-analysis sufficiency review",
        "Independently verify revision identity, changed-symbol coverage, caller/callee reachability, requirement mapping, API route discovery, DB/external side effects and risk propagation. Reject source-only summaries when graph/reachability evidence is required.",
        "CodeSufficiencyReview with reachability matrix, missing evidence, unmapped requirements/symbols and repair instructions.",
        "PASS only when critical/high-risk changed behavior is reachable and mapped with adequate evidence."
    ),
    "pfc-test-fusion": (
        "requirement+code test-intelligence fusion",
        "Fuse sufficient requirement and code truth into Test Intents and Test Conditions. Derive risk, oracle subject, data/precondition needs and independent L1-L7 applicability. Preserve traceability from requirement and code evidence; do not generate mixed-layer cases.",
        "TestIntent/TestCondition set with requirement/code trace refs, risk, oracle subjects, data needs and L1-L7 applicability decisions plus evidence.",
        "Every critical/high-risk behavior is represented by an evidence-backed Test Condition and every applicable layer decision is explicit."
    ),
    "pfc-l1-test-design": (
        "L1 code/unit test design",
        "Design unit/code cases from changed methods and Test Conditions. Cover decision branches, boundaries, null/invalid inputs, exception behavior and side effects. Define deterministic JUnit/Maven or equivalent oracle and changed line/branch/mutation evidence when available.",
        "Layer-L1 TestCases with setup, input, steps, expected/oracle, changed symbol trace and automation mapping.",
        "Semantic subject/oracle coverage closes critical/high-risk L1 gaps; no mixed-layer case remains."
    ),
    "pfc-l2-test-design": (
        "L2 DB/component/internal-integration test design",
        "Design cases for repository/component/internal integration behavior. Cover SQL predicates, transaction commit/rollback, concurrency/state transitions, constraints, idempotency, consistency and cleanup. Use authoritative schema/DB facts only.",
        "Layer-L2 TestCases with DB/component preconditions, SQL/state oracle, cleanup and evidence requirements.",
        "Critical transaction/state/data-integrity subjects and oracles are covered with executable prerequisites."
    ),
    "pfc-l3-test-design": (
        "L3 API/service-integration test design",
        "Use authoritative discovered routes and schemas. Cover valid business flows, field and cross-field validation, auth/permission, boundaries, error contracts, idempotency, state effects and dependency failures. Never infer an endpoint from naming conventions.",
        "Layer-L3 TestCases with route/schema/auth binding, request data, expected status/body/business/state oracle and CAT correlation needs.",
        "Critical API business/error/boundary/auth subjects have deterministic oracles and authoritative route evidence."
    ),
    "pfc-l4-test-design": (
        "L4 browser/UI test design",
        "Design real browser journeys from page/control/state/network evidence. Include 4A prerequisite state, form validation, permissions, navigation, asynchronous/loading/error states and network-backed oracle where appropriate. Prefer BrowserSkill/Playwright only after admission.",
        "Layer-L4 TestCases with page/control selectors or semantic locators, 4A preconditions, steps, visual/state/network oracle and evidence plan.",
        "Critical UI states and user paths have stable executable locators/preconditions and observable oracles."
    ),
    "pfc-l5-test-design": (
        "L5 cross-system E2E test design",
        "Design end-to-end journeys across PFC applications/dependencies. Cover handoffs, correlation identity, state consistency, retries/recovery, partial failure and final business state. Bind each system and data prerequisite explicitly.",
        "Layer-L5 TestCases with cross-system sequence, correlation ids, intermediate/final state oracles and evidence requirements.",
        "Critical journeys prove cross-system consistency and end-state correctness without collapsing lower layers into one case."
    ),
    "pfc-l6-test-design": (
        "L6 performance test design",
        "Derive workload model from business usage/risk. Define concurrency/rate/duration, warm-up, data isolation, latency/error/resource SLOs and abort conditions. Use admitted k6 or equivalent only with target authorization.",
        "Layer-L6 TestCases/workload specs with workload identity, thresholds, sampling and evidence plan.",
        "Performance subjects have measurable SLO oracles and reproducible workload/precondition definitions."
    ),
    "pfc-l7-test-design": (
        "L7 security test design",
        "Derive bounded security cases from attack surface and controls. Cover authn/authz, input handling, session/control boundaries and exposed API/browser surfaces only within explicit authorization. Define safe probes and stop conditions.",
        "Layer-L7 TestCases with authorization scope, probe, expected control, evidence and safety limit.",
        "Every planned probe is authorized, bounded, attributable and has a deterministic control oracle."
    ),
    "pfc-automation-engineer": (
        "testcase-to-executable automation engineering",
        "Resolve verified reusable automation before generation. Convert one frozen TestCase into immutable ExecutableTestSpec, bind route/auth/data/runner manifest, then create deterministic pytest/JUnit automation. Validate collection/compile/target selection before READY; GENERATED is never READY.",
        "ExecutableTestSpec, reuse decision, script artifact, runner manifest and validation evidence.",
        "Script is deterministic, targets exactly the frozen case/spec, validates successfully and contains no hidden oracle weakening."
    ),
    "pfc-test-data": (
        "precondition and test-data preparation",
        "For one intended Attempt, resolve preconditions and search/reuse/build test data using authoritative DB/API facts. Verify created state, bind provenance and cleanup/rollback, then freeze PreparedAttempt. Never mutate data simply to turn a product failure green.",
        "PreparedAttempt with data ids/provenance, precondition evidence, cleanup plan and immutable case/spec/target bindings.",
        "All execution prerequisites are verified on the bound target and cleanup semantics are explicit."
    ),
    "pfc-l1-test-execution": (
        "real L1 execution",
        "Run only validated L1 automation through the admitted real runner. Capture command, exit/result, test identity, assertion actual/expected and code coverage evidence when available. Never synthesize success.",
        "Attempt result with actual/oracle/evidence, runner manifest identity and L1 coverage evidence.",
        "Terminal result is derived from a real runner invocation and evidence is sufficient for ownership classification."
    ),
    "pfc-l2-test-execution": (
        "real L2 execution",
        "Execute the frozen PreparedAttempt against the bound component/DB target. Capture SQL/transaction/state before-after evidence and cleanup outcome. Distinguish setup/data failures from product assertions.",
        "Attempt result with DB/component actuals, transaction/state oracle evidence and cleanup evidence.",
        "Real target action occurred and resulting state is independently observable against the oracle."
    ),
    "pfc-l3-test-execution": (
        "real L3 API execution",
        "Execute the authoritative route with bound auth and prepared data. Capture request identity, status/body/business actuals, state effects and CAT correlation when applicable. 404 from a guessed route is forbidden evidence.",
        "Attempt result with request/response, business/state oracle, correlation/CAT refs and runner evidence.",
        "Execution used an authoritative route and valid preparation; actual-vs-oracle is evidenced enough for diagnosis."
    ),
    "pfc-l4-test-execution": (
        "real L4 browser execution",
        "Execute with admitted browser automation and real 4A state. Capture page/control actions, observable UI state and relevant network evidence. Human login is not silently substituted when automated auth is required by the Mission.",
        "Attempt result with browser action trace, page/state/network oracle evidence and screenshots only when the environment supports them.",
        "Real browser actions reached the intended state or produced a classified blocker with evidence."
    ),
    "pfc-l5-test-execution": (
        "real L5 E2E execution",
        "Execute the bound cross-system journey preserving correlation identity and intermediate state. Capture each handoff, dependency result and final business consistency oracle; do not mark E2E verified from partial execution.",
        "Attempt result with end-to-end correlation, intermediate/final state evidence and dependency observations.",
        "All required systems/handoffs actually executed and the final oracle is evidenced on the same target identity."
    ),
    "pfc-l6-test-execution": (
        "real L6 performance execution",
        "Execute the admitted workload spec with bound target and data isolation. Capture tool/version identity, samples, latency/error/resource metrics and threshold evaluation. Stop on authorization/environment ambiguity.",
        "Attempt result with workload identity, metric evidence, thresholds/SLO result and raw artifact refs.",
        "A real workload ran for the governed scope and SLO conclusions are reproducible from evidence."
    ),
    "pfc-l7-test-execution": (
        "real L7 security execution",
        "Execute only explicitly authorized bounded probes. Capture exact request/action, observed control, result and safety boundary. Never expand attack scope autonomously beyond authorization.",
        "Attempt result with authorization ref, probe/control evidence, findings and stop-condition outcome.",
        "All probes stayed within scope and every security conclusion is tied to real observable evidence."
    ),
    "pfc-failure-diagnosis": (
        "evidence-driven failure ownership and RCA",
        "Create a stable FailureSignature, then test competing causes in order: script/spec/oracle, data/precondition, auth, route, tool, environment/dependency, then product. Use runner logs, CAT for L3/L5 when applicable, and CodeGraph/Git/requirement/SST context. Assertion failure alone never proves PRODUCT.",
        "FailureDiagnosis with signature, classification, evidence per competing cause, RCA refs and recommended governed recovery/defect route.",
        "Ownership is supported by evidence and untested competing causes prevent PRODUCT classification."
    ),
    "pfc-recovery": (
        "governed recovery and re-execution",
        "Execute only the runtime-selected verified recovery adapter for the diagnosed class. Verify side effects, consume retry/recovery budgets, create a fresh Attempt and re-run. Never edit a frozen oracle or silently broaden scope to make a case pass.",
        "RecoveryResult with adapter id, before/after evidence, budget use, new Attempt id and rerun outcome.",
        "Recovery is authorized, bounded, observable and convergence/loop-break rules are respected."
    ),
    "pfc-defect-review": (
        "human-reviewable product defect confirmation",
        "Confirm PRODUCT only after valid preparation and real action plus proof that script/spec/oracle/data/auth/route/tool/environment/dependency are correct. Reconcile with CAT/code evidence and create a stable defect candidate instead of retrying product behavior to green.",
        "DefectCandidate with stable signature, reproduction, expected/actual, impact, evidence bundle and competing-cause proof.",
        "Defect evidence is reproducible and strong enough for human review/external reconciliation."
    ),
    "pfc-report": (
        "R1-derived evidence/report publication",
        "Build status, coverage, defects and report strictly from R1 truth and canonical evidence. Reconcile Mission/Target/Case/Attempt identities and counts; expose blocked/not-executed separately. Never promote CI/engineering proof to bank field qualification.",
        "Reconciled TestReport/Allure/admin derivative with traceability, execution/coverage/defect counts, blockers and evidence refs.",
        "All reported counts reconcile to R1 and release status remains pre-bank unless the real field gates are satisfied."
    ),
}

PROFESSIONAL_SKILLS = tuple(ROLE_SPECS.keys())
ALL_SKILLS = ("pfc-full-chain-test",) + PROFESSIONAL_SKILLS

_GOVERNANCE = """## Mandatory RC6 governance\n\n- You are a professional Worker, never the Coordinator. Accept only Runtime-issued mission_id, worker_id and lease_id.\n- R1 Event Stream plus R1-backed artifact references are the sole durable test truth; chat claims and ad-hoc files are not completion evidence.\n- Read revisions, routes, DB profiles, accounts, 4A, CAT and target identity from Bank Reality. Never guess a bank fact.\n- Before every external professional tool call require lease/tool authorization and exact Tool Capability Broker admission for the Worker and Target. DISCOVERED is not READY.\n- Persist structured professional output through the governed artifact path. Missing evidence produces an explicit gap/block/repair request, never fabricated completion.\n- Stay inside this role and layer. Route repair to the owning worker; do not impersonate another professional role or combine layers.\n- Engineering boot/CI success never means BANK_FINAL.\n"""


def render_professional_skill(name: str) -> str:
    title, method, output, exit_criteria = ROLE_SPECS[name]
    return (
        "---\n"
        "name: %s\n" % name
        + "description: RC6 governed professional Worker for %s.\n" % title
        + "---\n\n# RC6 %s\n\n" % title
        + _GOVERNANCE
        + "\n## Professional method\n\n%s\n" % method
        + "\n## Required output/evidence contract\n\n%s\n" % output
        + "\n## Sufficiency / exit criteria\n\n%s\n" % exit_criteria
        + "\n## Failure routing\n\nIf a prerequisite, authoritative bank fact, admitted tool, evidence reference or deterministic oracle is missing, return an explicit BLOCKED/GAP result with the missing subject and evidence needed. Do not continue by assumption.\n"
    )


def materialize_professional_skills(package_root: str | Path) -> None:
    root = Path(package_root) / ".dsh" / "skills"
    for name in PROFESSIONAL_SKILLS:
        target = root / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_professional_skill(name))
