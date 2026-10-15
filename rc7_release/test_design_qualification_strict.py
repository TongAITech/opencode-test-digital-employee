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
    " Every semantic_payload.cases item MUST also be downstream execution-contract-ready. "
    "preconditions MUST be a list of structured objects {id,type,requirement}, with type one of "
    "ENVIRONMENT/AUTH/BUSINESS_STATE/DATA/DEPENDENCY. test_data MUST be an object with initial_state and input_data lists; "
    "each data requirement MUST contain id, non-empty selectors, and allowed_strategies chosen from "
    "REUSE_EXISTING/DERIVE/API_CREATE/UI_CREATE/DB_CREATE/FIXTURE/MOCK. test_data.cleanup_policy MUST contain mode "
    "NONE/ROLLBACK/DELETE/RESTORE and MUST equal top-level cleanup_policy (one cleanup truth). Also include requirement_id, "
    "steps(non-empty ordered list), expected(non-empty), evidence_requirements(non-empty string list), test_data_refs(list; "
    "non-empty when structured data requirements exist), oracle_refs(non-empty immutable oracle reference list), and runner_type "
    "exactly PYTEST or JUNIT. Every oracle.check MUST be machine-executable before Script/Execution: include a stable id, type, "
    "actual_path into the structured runtime actual_result, operator one of EQ/NE/GT/GTE/LT/LTE/IN/NOT_IN/CONTAINS/EXISTS/"
    "NOT_EXISTS, expected for every operator except EXISTS/NOT_EXISTS, and durable evidence_ref. Execution Runtime will evaluate "
    "these fields deterministically; no AI interpretation is allowed after the actual result exists. Do not invent these fields "
    "from convenience; derive them from Test Obligations, Requirement/Code parents, route/data reality and the case Oracle. "
    "Missing preparation/execution/oracle semantics are a Test Design gap, not something Script or Execution workers may fill in later."
)


def _review_contract_fields():
    return [
        "requirement_id",
        "preconditions[{id,type,requirement}]",
        "test_data{initial_state,input_data,cleanup_policy}",
        "data requirements{id,selectors,allowed_strategies}",
        "steps",
        "expected",
        "evidence_requirements",
        "test_data_refs",
        "oracle_refs",
        "oracle.checks[{id,type,actual_path,operator,expected,evidence_ref}]",
        "cleanup_policy == test_data.cleanup_policy",
        "runner_type=PYTEST|JUNIT",
    ]


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
        "fields": _review_contract_fields(),
        "rule": (
            "Return GAPS if any case leaves downstream Script/Preparation/Execution Runtime to invent semantics, data construction, "
            "or reinterpret the Oracle after seeing the actual result."
        ),
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def run_strict_test_design_qualification(**kwargs):
    original_objective = legacy._design_objective
    original_reviewer = legacy._reviewer_guidance

    def objective(**values):
        return original_objective(**values) + _CASE_CONTRACT_GUIDANCE

    def reviewer(**values):
        raw = original_reviewer(**values)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw + _CASE_CONTRACT_GUIDANCE
        data["execution_contract_case_review"] = {
            "required": True,
            "fields": _review_contract_fields(),
            "rule": (
                "Return GAPS if any case leaves downstream Script/Preparation/Execution Runtime to invent semantics, data construction, "
                "or reinterpret the Oracle after seeing the actual result."
            ),
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
