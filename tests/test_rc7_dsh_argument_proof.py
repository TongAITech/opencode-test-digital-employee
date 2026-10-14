from __future__ import annotations

import time

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.dsh_proof import DshR1ProofReader
from rc7_runtime.dsh_reality_launcher import RC7BankFinalDshHeadlessWorkerLauncher


def test_rc7_launcher_preserves_direct_tool_input_arguments():
    events = [
        {
            "type": "tool_call",
            "tool_name": "mcp__pfc_aitest_rc7__codegraph_query",
            "input": {
                "repo_path": "cfg-data",
                "args": ["callers", "RateService.adjustRate", "--json"],
            },
        }
    ]

    calls = RC7BankFinalDshHeadlessWorkerLauncher._tool_calls(events)

    assert calls == [
        {
            "call_ref": "dsh-event://tool-call/0",
            "tool_name": "mcp__pfc_aitest_rc7__codegraph_query",
            "arguments": {
                "repo_path": "cfg-data",
                "args": ["callers", "RateService.adjustRate", "--json"],
            },
        }
    ]


def test_rc7_launcher_decodes_nested_json_arguments():
    events = [
        {
            "type": "tool_call",
            "tool": {
                "name": "mcp__pfc_aitest_rc7__git_diff",
                "arguments": '{"repo_path":"cfg-data","base_ref":"abc","head_ref":"def"}',
            },
        }
    ]

    calls = RC7BankFinalDshHeadlessWorkerLauncher._tool_calls(events)

    assert calls[0]["tool_name"] == "mcp__pfc_aitest_rc7__git_diff"
    assert calls[0]["arguments"] == {
        "repo_path": "cfg-data",
        "base_ref": "abc",
        "head_ref": "def",
    }


def test_r1_proof_reader_returns_persisted_tool_arguments(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    now = int(time.time())
    truth.append_atomic(
        "WORKER_TOOL_CALLED",
        {
            "id": "are-argument-proof",
            "release_id": "RC7",
            "artifact_version": 1,
            "mission_id": "MISSION-ARGUMENT-PROOF",
            "event_name": "WORKER_TOOL_CALLED",
            "coordinator_instance_id": "coordinator-arg",
            "occurred_at": now,
            "worker_instance_id": "worker-arg",
            "agent_id": "code-analysis",
            "attempt_id": "attempt-arg",
            "assignment_id": "assign-arg",
            "lease_id": "lease-arg",
            "parent_worker_id": "coordinator-arg",
            "scope": "task:arg",
            "input_refs": [],
            "tool_calls": [
                {
                    "call_ref": "dsh-event://tool-call/0",
                    "tool_name": "mcp__pfc_aitest_rc7__git_diff",
                    "arguments": {
                        "repo_path": "cfg-data",
                        "base_ref": "abc",
                        "head_ref": "def",
                    },
                }
            ],
            "output_refs": [],
            "evidence_refs": [],
            "started_at": now,
            "finished_at": now,
            "result": "PASS",
            "tool_call": {
                "call_ref": "dsh-event://tool-call/0",
                "tool_name": "mcp__pfc_aitest_rc7__git_diff",
                "arguments": {
                    "repo_path": "cfg-data",
                    "base_ref": "abc",
                    "head_ref": "def",
                },
            },
        },
    )

    proofs = DshR1ProofReader().tool_calls(
        truth,
        mission_id="MISSION-ARGUMENT-PROOF",
        worker_instance_id="worker-arg",
    )

    assert len(proofs) == 1
    assert proofs[0].arguments == {
        "repo_path": "cfg-data",
        "base_ref": "abc",
        "head_ref": "def",
    }
