from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from . import test_design_qualification as legacy


_CASE_CONTRACT_GUIDANCE = (
    " Every semantic_payload.cases item MUST also be downstream execution-contract-ready: "
    "include requirement_id, preconditions(list), steps(non-empty ordered list), expected(non-empty), "
    "evidence_requirements(non-empty string list), test_data_refs(list, may be empty only when no data setup is needed), "
    "oracle_refs(non-empty immutable oracle reference list), cleanup_policy(object), and runner_type exactly PYTEST or JUNIT. "
    "Do not invent these fields from convenience; derive them from the Test Obligation, Requirement/Code parents, real route/data reality, "
    "and the case Oracle. Missing execution semantics are a Test Design gap, not something the Script Worker may fill in later."
)


def _strict_objective(*, requirement_path: str, code_path: str, repo_path: str, codegraph_args: List[str]) -> str:
    return legacy._design_objective(
        requirement_path=requirement_path,
        code_path=code_path,
        repo_path=repo_path,
        codegraph_args=codegraph_args,
    ) + _CASE_CONTRACT_GUIDANCE


def _strict_reviewer_guidance(*, requirement_path: str, code_path: str, repo_path: str, codegraph_args: List[str]) -> str:
    raw = legacy._reviewer_guidance(
        requirement_path=requirement_path,
        code_path=code_path,
        repo_path=repo_path,
        codegraph_args=codegraph_args,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw + _CASE_CONTRACT_GUIDANCE
    data["execution_contract_case_review"] = {
        "required": True,
        "fields": [
            "requirement_id",
            "preconditions",
            "steps",
            "expected",
            "evidence_requirements",
            "test_data_refs",
            "oracle_refs",
            "cleanup_policy",
            "runner_type=PYTEST|JUNIT",
        ],
        "rule": "Return GAPS if any case leaves downstream Script Runtime to invent execution semantics.",
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def run_strict_test_design_qualification(**kwargs):
    original_objective = legacy._design_objective
    original_reviewer = legacy._reviewer_guidance
    # The strict helpers intentionally call the original functions captured here
    # rather than recursively calling patched globals.
    def objective(**values):
        base = original_objective(**values)
        return base + _CASE_CONTRACT_GUIDANCE

    def reviewer(**values):
        raw = original_reviewer(**values)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw + _CASE_CONTRACT_GUIDANCE
        data["execution_contract_case_review"] = {
            "required": True,
            "fields": [
                "requirement_id", "preconditions", "steps", "expected",
                "evidence_requirements", "test_data_refs", "oracle_refs",
                "cleanup_policy", "runner_type=PYTEST|JUNIT",
            ],
            "rule": "Return GAPS if any case leaves downstream Script Runtime to invent execution semantics.",
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    legacy._design_objective = objective
    legacy._reviewer_guidance = reviewer
    try:
        return legacy.run_real_test_design_qualification(**kwargs)
    finally:
        legacy._design_objective = original_objective
        legacy._reviewer_guidance = original_reviewer


def _parse_query_args(value: Optional[str]) -> Optional[List[str]]:
    return legacy._parse_query_args(value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RC7 strict real DSH Test Design qualification")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or str(Path.cwd()))
    parser.add_argument("--requirement-result", default=os.environ.get("PFC_RC7_REQUIREMENT_RESULT") or "")
    parser.add_argument("--code-result", default=os.environ.get("PFC_RC7_CODE_RESULT") or "")
    parser.add_argument("--repo-path", default=os.environ.get("PFC_RC7_CODE_REPO") or ".")
    parser.add_argument("--codegraph-args-json", default=os.environ.get("PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON"))
    parser.add_argument("--dsh-bin", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        codegraph_args = _parse_query_args(args.codegraph_args_json)
    except Exception as exc:
        print(json.dumps({"status": "NOT_PROVEN", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    result = run_strict_test_design_qualification(
        state_root=args.state_root,
        workspace=args.workspace,
        requirement_result=args.requirement_result,
        code_result=args.code_result,
        repo_path=args.repo_path,
        codegraph_args=codegraph_args,
        dsh_bin=args.dsh_bin,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    if result.status == "PASS":
        return 0
    if result.status == "NOT_PROVEN":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
