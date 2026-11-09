"""Static L0/L1/L2 GitHub Actions admission auditor; NOT a QA_PASS oracle."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Mapping

WORKFLOWS = {
    "v3": ".github/workflows/rc7.2-abcd-v3-qualification.yml",
    "v4": ".github/workflows/rc7.2-abcd-v4-qualification.yml",
    "w0": ".github/workflows/dsh-wb-w0-contract.yml",
    "l1": ".github/workflows/dsh-wb-l1-integration.yml",
    "c": ".github/workflows/dsh-wb-c-w0-ui.yml",
    "c04": ".github/workflows/rc7.2-a-c04-native-n9-host.yml",
    "c07": ".github/workflows/rc7.2-a-c07-n9-host-fence.yml",
    "c10": ".github/workflows/rc7.2-a-c10-clock-ci.yml",
    "n8": ".github/workflows/rc7.2-a-recovery-cli.yml",
    "q1": ".github/workflows/rc7.2-platform-qualification.yml",
}
NON_DRAFT = "if: github.event_name != 'pull_request' || github.event.pull_request.draft == false"
PR_CANCEL = "cancel-in-progress: " + chr(36) + "{{ github.event_name == 'pull_request' }}"


def read_workflows(root: Path) -> Dict[str, str]:
    return {key: (root / path).read_text(encoding="utf-8")
            for key, path in WORKFLOWS.items()}


def event_block(contents: str) -> str:
    found = re.search(r"(?ms)^on:\s*\n(.*?)(?=^[a-zA-Z][a-zA-Z_-]*:|\Z)", contents)
    if not found:
        raise ValueError("NO_ON_EVENT_BLOCK")
    return found.group(1)


def problems(sources: Mapping[str, str]) -> List[str]:
    errors: List[str] = []
    if set(sources) != set(WORKFLOWS):
        return ["CI_POLICY_INPUT_FILES_INCOMPLETE"]
    try:
        e = {k: event_block(v) for k, v in sources.items()}
    except ValueError as exc:
        return [str(exc)]
    if re.search(r"(?m)^  pull_request:", e["v3"]):
        errors.append("DUPLICATE_V3_FULL_PR")
    if not all(x in e["v3"] for x in ("workflow_dispatch:", "push:")):
        errors.append("V3_EXPLICIT_OR_HISTORICAL_GATE_LOST")
    if not all(x in e["v4"] for x in (
        "pull_request:", "ready_for_review", "synchronize",
        "workflow_dispatch:", "'tests/test_rc72_*.py'",
    )):
        errors.append("V4_FULL_PR_ADMISSION_LOST")
    if sources["v4"].count(NON_DRAFT) != 2:
        errors.append("V4_DRAFT_FULL_TESTS_REENABLED")
    if PR_CANCEL not in sources["v4"] or re.search(
        r"(?m)^\s+group:.*github\.sha", sources["v4"]
    ):
        errors.append("V4_OLD_SHA_TASKS_NOT_CANCELLED")
    if not all(x in sources["v4"] for x in (
        "find tests -maxdepth 1 -type f -name 'test_rc7*.py'",
        "tests/test_rc72_c09_real_chromium_cdp_smoke.py",
        "python: ['3.8', '3.11']", "windows-2022",
    )):
        errors.append("V4_FULL_RELEASE_COVERAGE_DROPPED")
    if re.search(r"(?m)^  push:", e["w0"]) or not re.search(
        r"(?m)^  pull_request:", e["w0"]
    ):
        errors.append("W0_DUPLICATE_OR_MISSING_PR_TRIGGER")
    if not all(x in sources["w0"] for x in (
        "test_dsh_workbench*.py", "ci_admission.py", "workflow_dispatch:",
    )):
        errors.append("W0_FAST_GATE_NOT_WIRED")
    if not all(x in e["l1"] for x in (
        "pull_request:", "ready_for_review", "workflow_dispatch:",
        "expected_source_sha:", "include_browser:",
    )):
        errors.append("L1_ADMISSION_EVENTS_MISSING")
    if not all(x in sources["l1"] for x in (
        NON_DRAFT, "L1_SOURCE_HEAD_MISMATCH", "git rev-parse HEAD",
        "test_dsh_workbench*.py", "test_dsh_workbench_c_feature_reconciliation.mjs",
        "inputs.include_browser == true",
    )):
        errors.append("L1_SOURCE_PIN_OR_GATES_MISSING")
    if sources["c"].count(NON_DRAFT) != 2 or "ready_for_review" not in e["c"]:
        errors.append("C_BROWSER_DRAFT_GATE_MISSING")
    if any(s in e["c"] for s in (
        "08-CONSTRUCTION-PLAN.md", "09-GAP-MATRIX.md", "10-RELEASE-CHECKPOINT.md",
    )):
        errors.append("C_BROWSER_RERUN_ON_LEDGER")
    for name in ("c04", "c07", "c10", "n8"):
        if sources[name].count(NON_DRAFT) != 1:
            errors.append(name.upper() + "_DRAFT_MATRIX")
        if "paths:" not in e[name] or "pull_request:" not in e[name]:
            errors.append(name.upper() + "_UNSCOPED_MATRIX")
        if PR_CANCEL not in sources[name] or re.search(
            r"(?m)^\s+group:.*github\.sha", sources[name]
        ):
            errors.append(name.upper() + "_SHA_CONCURRENCY")
        if "workflow_dispatch:" not in e[name]:
            errors.append(name.upper() + "_EXPLICIT_GATE_LOST")
    # Keep the FG17 negative Py3.8 Chromium test on relevant PR changes.
    if not all(s in e["q1"] for s in (
        "pull_request:", "work/rc7.2",
        "tests/test_rc72_c09_real_chromium_cdp_smoke.py",
    )) or "q1-browser-py38-pr-admission:" not in sources["q1"]:
        errors.append("Q1_FG17_NEGATIVE_CHECK_REMOVED")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    found = problems(read_workflows(root))
    for code in found:
        print("CI_POLICY_BLOCKED: " + code)
    if found:
        return 2
    print("CI_ADMISSION_POLICY_PASS workflow_count=%d; NO_QA_PASS_CLAIM"
          % len(WORKFLOWS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
