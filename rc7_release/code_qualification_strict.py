from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.dsh_proof import DshR1ProofReader, DshToolCallProof
from rc7_runtime.dsh_reality_launcher import RC7BankFinalDshHeadlessWorkerLauncher

from . import code_qualification as legacy


class _StrictCodeQualificationLauncher(RC7BankFinalDshHeadlessWorkerLauncher):
    def __init__(self, *args, reviewer_guidance: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reviewer_guidance = reviewer_guidance

    def execute(self, assignment, prompt):
        if getattr(assignment, "agent_id", "") == "rc7-code-sufficiency":
            prompt = prompt + "\nQUALIFICATION_REALITY_GUIDANCE=" + self.reviewer_guidance
        return super().execute(assignment, prompt)


def _arguments_contain(actual, expected) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _arguments_contain(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def _has_exact_proof(
    proofs: Sequence[DshToolCallProof],
    *,
    tool_name: str,
    expected_arguments: Dict[str, object],
) -> bool:
    return any(
        proof.tool_name == tool_name and _arguments_contain(proof.arguments, expected_arguments)
        for proof in proofs
    )


def _verify_worker_targets(
    truth: TruthRuntime,
    *,
    mission_id: str,
    worker_id: Optional[str],
    repo_path: str,
    base_ref: str,
    head_ref: str,
    codegraph_args: List[str],
    label: str,
) -> Optional[str]:
    if not worker_id:
        return "%s_WORKER_ID_MISSING" % label
    proofs = DshR1ProofReader().tool_calls(
        truth,
        mission_id=mission_id,
        worker_instance_id=worker_id,
    )
    if not _has_exact_proof(
        proofs,
        tool_name=legacy.GIT_DIFF_TOOL,
        expected_arguments={
            "repo_path": repo_path,
            "base_ref": base_ref,
            "head_ref": head_ref,
        },
    ):
        return "%s_GIT_DIFF_ARGUMENT_PROOF_MISSING" % label
    if not _has_exact_proof(
        proofs,
        tool_name=legacy.CODEGRAPH_QUERY_TOOL,
        expected_arguments={"repo_path": repo_path, "args": list(codegraph_args)},
    ):
        return "%s_CODEGRAPH_ARGUMENT_PROOF_MISSING" % label
    return None


def run_strict_code_qualification(
    *,
    state_root: str,
    workspace: str,
    repo_path: str,
    base_ref: str,
    head_ref: str,
    target_id: str,
    codegraph_args: Optional[List[str]],
    dsh_bin: Optional[str] = None,
    timeout_seconds: int = 300,
):
    original_launcher = legacy._CodeQualificationLauncher
    legacy._CodeQualificationLauncher = _StrictCodeQualificationLauncher
    try:
        result = legacy.run_real_code_qualification(
            state_root=state_root,
            workspace=workspace,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            target_id=target_id,
            codegraph_args=codegraph_args,
            dsh_bin=dsh_bin,
            timeout_seconds=timeout_seconds,
        )
    finally:
        legacy._CodeQualificationLauncher = original_launcher

    if result.status != "PASS" or not codegraph_args:
        return result

    truth = TruthRuntime(Path(state_root).resolve() / "r1.jsonl")
    reason = _verify_worker_targets(
        truth,
        mission_id=result.mission_id,
        worker_id=result.analyzer_worker_id,
        repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        codegraph_args=list(codegraph_args),
        label="ANALYZER",
    )
    if reason is None:
        reason = _verify_worker_targets(
            truth,
            mission_id=result.mission_id,
            worker_id=result.reviewer_worker_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            codegraph_args=list(codegraph_args),
            label="REVIEWER",
        )
    if reason is not None:
        result = replace(result, status="FAIL", reason=reason)
        legacy._write_result(Path(state_root).resolve(), result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RC7 argument-verified real DSH Code qualification")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or str(Path.cwd()))
    parser.add_argument("--repo-path", default=os.environ.get("PFC_RC7_CODE_REPO") or ".")
    parser.add_argument("--base-ref", default=os.environ.get("PFC_RC7_CODE_BASE_REF") or "")
    parser.add_argument("--head-ref", default=os.environ.get("PFC_RC7_CODE_HEAD_REF") or "")
    parser.add_argument("--target-id", default=os.environ.get("PFC_RC7_CODE_TARGET_ID") or "")
    parser.add_argument("--codegraph-args-json", default=os.environ.get("PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON"))
    parser.add_argument("--dsh-bin", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        codegraph_args = legacy._parse_query_args(args.codegraph_args_json)
    except Exception as exc:
        print(json.dumps({"status": "NOT_PROVEN", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    result = run_strict_code_qualification(
        state_root=args.state_root,
        workspace=args.workspace,
        repo_path=args.repo_path,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        target_id=args.target_id,
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
