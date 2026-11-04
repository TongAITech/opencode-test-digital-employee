"""C04 real DSH N9 cause-analysis intake: handoff must match actual R1 task.

These are narrow security/receipt tests, NOT bank reproduction/RCA/defect PASS.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService


def _candidate():
    return {
        "finding": "INCONCLUSIVE",
        "hypotheses": ["Need independent API/DB reproduction"],
        "reproduction_steps": ["Request new scoped work item and recheck Oracle"],
        "tool_evidence_refs": ["dsh-event://tool-call/0"],
    }


def _handoff():
    service = object.__new__(NativeN9ProfessionalDshAnalysisService)
    service.allowed_tools = ("api_read_only",)
    service.release_id = "RC7.2"
    service.source_commit = "a" * 40
    service._raw = lambda ref, mission_id, assignment_id: ("a" * 64, _candidate())
    service._one = lambda kind, **scope: {"worker_id": "ORIGINAL-N7-WORKER"}
    workitem = "N9QUAL-ORIGINAL-REAL-GAP"
    scope = {
        "qualification_workitem_id": workitem,
        "preparation_id": "PREP-ORIGINAL",
        "diagnosis_id": "DIAG-REAL",
        "original_attempt_id": "N7-ORIGINAL-ATTEMPT",
        "gap_id": "GAP-REAL",
    }
    task = {
        "mission_id": "M-REAL",
        "task_id": workitem,
        "lease_owner": "N9-INDEPENDENT-WORKER",
        "state": "RUNNING",
    }
    returned = {
        "event_name": "HANDOFF_RETURNED",
        "mission_id": "M-REAL",
        "scope": "task:" + workitem,
        "result": "PASS",
        "exit_code": 0,
        "tool_calls": [{"tool_name": "api_read_only", "call_ref": "dsh-event://tool-call/0"}],
        "evidence_refs": ["file:///private/dsh/worker-evidence.jsonl"],
        "assignment_id": "ASSIGN-N9",
        "worker_instance_id": "N9-INDEPENDENT-WORKER",
        "dsh_session_id": "session-n9-distinct",
        "attempt_id": service._attempt_id(workitem),
    }
    return service, scope, task, returned


def test_n9_real_returned_task_scope_is_a_string_not_an_intake_dictionary():
    service, scope, task, returned = _handoff()
    receipt = service._expected(scope, task, returned)
    assert receipt["state"] == "ANALYSIS_CANDIDATE_REVIEW_REQUIRED"
    assert receipt["qualification_workitem_id"] == task["task_id"]
    assert receipt["original_attempt_id"] == scope["original_attempt_id"]
    assert receipt["worker_id"] == "N9-INDEPENDENT-WORKER"
    assert receipt["candidate"] == _candidate()
    assert "defect_confirmed" not in receipt
    assert "field_verified" not in receipt and "bank_final" not in receipt


@pytest.mark.parametrize("mutation", [
    "dict_scope", "foreign_scope", "reused_n7_worker",
    "bad_lease_owner", "other_attempt", "unapproved_tool",
    "unobserved_evidence", "replayed_dsh_session",
])
def test_n9_real_handoff_rejects_wrong_identity_unobserved_tool_and_oracle_bypass(mutation):
    service, scope, task, returned = _handoff()
    if mutation == "dict_scope":
        returned["scope"] = scope
    elif mutation == "foreign_scope":
        returned["scope"] = "task:N9QUAL-FOREIGN"
    elif mutation == "reused_n7_worker":
        returned["worker_instance_id"] = "ORIGINAL-N7-WORKER"
    elif mutation == "bad_lease_owner":
        task["lease_owner"] = "WRONG-OWNER"
    elif mutation == "other_attempt":
        returned["attempt_id"] = "OLD-REPLAY"
    elif mutation == "unapproved_tool":
        returned["tool_calls"][0]["tool_name"] = "api_mutating_delete"
    elif mutation == "unobserved_evidence":
        service._raw = lambda ref, mission_id, assignment_id: (
            "a" * 64, dict(_candidate(), tool_evidence_refs=["dsh-event://tool-call/999"]))
    elif mutation == "replayed_dsh_session":
        returned["dsh_session_id"] = None
    with pytest.raises(ContractError):
        service._expected(scope, task, returned)


def test_n9_raw_dsh_evidence_must_be_exact_private_launcher_file_on_windows_and_linux(tmp_path):
    service = object.__new__(NativeN9ProfessionalDshAnalysisService)
    service.launcher = SimpleNamespace(state_root=tmp_path)
    out = tmp_path / "worker-evidence" / "M-REAL" / "ASSIGN-N9.jsonl"
    out.parent.mkdir(parents=True)
    out.write_text(
        json.dumps({"type": "tool_call", "tool_name": "api_read_only"}) + "\n"
        + json.dumps({"type": "text", "text": json.dumps(_candidate())}) + "\n",
        encoding="utf-8",
    )
    digest, candidate = service._raw(out.resolve().as_uri(), "M-REAL", "ASSIGN-N9")
    assert digest == hashlib.sha256(out.read_bytes()).hexdigest()
    assert candidate == _candidate()
    for foreign in ("file://remote.invalid" + out.resolve().as_posix(),
                    (tmp_path / "foreign.jsonl").resolve().as_uri(),
                    "file:///C:/untrusted/foreign.jsonl"):
        with pytest.raises(ContractError, match="N9_DSH_NATIVE_RAW_PATH_CHANGED"):
            service._raw(foreign, "M-REAL", "ASSIGN-N9")
