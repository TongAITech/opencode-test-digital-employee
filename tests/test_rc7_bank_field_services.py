from __future__ import annotations

import json
import sys
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_field_services import (
    CAP_AUTH_4A,
    CAP_CAT,
    CAP_DB_READ,
    CAP_DB_WRITE,
    PROBE_KIND,
    approve_db_write_probe,
    probe_bank_services,
    qualify_bank_services,
)
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-BANK-SVC"
RELEASE = "REL-BANK-SVC"
TARGET = "PFC-FIELD-TARGET"


def _r1(tmp_path: Path) -> Path:
    install_rc7_truth_overlay()
    path = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(path)
    append_entity(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="qualify bank services"),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Task(
            task_id="TASK-EXEC",
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="execute bank cases",
            state=TaskStatus.RUNNING,
            lease_owner="WORKER-EXEC",
        ),
        release_id=RELEASE,
    )
    return path


def _provider(tmp_path: Path, *, include_write: bool = True, secret: bool = False) -> Path:
    script = tmp_path / "provider.py"
    script.write_text(
        """
import json, sys
req = json.load(sys.stdin)
cap = req["capability"]
base = {
    "success": True,
    "target_verified": True,
    "tool_call_ref": "field-tool://" + cap.lower(),
    "evidence_ref": "field-evidence://" + cap.lower(),
}
if cap == "BANK_AUTH_4A":
    base["auth_evidence_ref"] = "4a-evidence://login-success"
elif cap == "BANK_CAT_QUERY":
    base["cat_evidence_ref"] = "cat-evidence://query-success"
    base["correlation_ref"] = "cat-correlation://probe"
elif cap == "BANK_DB_READ":
    base["read_evidence_ref"] = "db-evidence://read-success"
elif cap == "BANK_DB_WRITE":
    base["write_evidence_ref"] = "db-evidence://write-success"
    base["verification_ref"] = "db-evidence://verify-success"
    base["rollback_ref"] = "db-evidence://rollback-success"
else:
    base = {"success": False, "target_verified": False, "reason": "unsupported"}
if %s:
    base["token"] = "must-not-persist"
json.dump(base, sys.stdout)
""" % ("True" if secret else "False"),
        encoding="utf-8",
    )
    providers = {}
    for cap in (CAP_AUTH_4A, CAP_CAT, CAP_DB_READ, CAP_DB_WRITE):
        if cap == CAP_DB_WRITE and not include_write:
            continue
        providers[cap] = {
            "provider_id": "fixture-%s" % cap.lower(),
            "command": [sys.executable, str(script)],
            "timeout_seconds": 30,
        }
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({"providers": providers}), encoding="utf-8")
    return config


def test_bank_services_are_real_probes_and_db_write_requires_human_gate(tmp_path: Path) -> None:
    r1 = _r1(tmp_path)
    state = tmp_path / "state"
    config = _provider(tmp_path)

    first = probe_bank_services(
        r1_path=str(r1),
        state_root=str(state),
        provider_config=str(config),
        mission_id=MISSION,
        target_id=TARGET,
    )
    assert first["status"] == "HUMAN_GATE_REQUIRED"
    assert first["capabilities"][CAP_AUTH_4A]["status"] == "PASS"
    assert first["capabilities"][CAP_CAT]["status"] == "PASS"
    assert first["capabilities"][CAP_DB_READ]["status"] == "PASS"
    assert first["capabilities"][CAP_DB_WRITE]["status"] == "HUMAN_GATE_REQUIRED"
    request_id = first["db_write_gate_request_id"]
    assert request_id.startswith("HGREQ-")

    before = qualify_bank_services(r1_path=str(r1), mission_id=MISSION, target_id=TARGET)
    assert before["status"] == "HOLD"
    assert before["platform_capabilities"][CAP_DB_WRITE]["status"] == "HOLD"

    approval = approve_db_write_probe(
        r1_path=str(r1),
        state_root=str(state),
        mission_id=MISSION,
        target_id=TARGET,
        request_id=request_id,
        actor_ref="BANK-TEST-OPERATOR",
        reason="Approved one reversible RC7 qualification write",
    )
    assert approval["status"] == "APPROVED"

    second = probe_bank_services(
        r1_path=str(r1),
        state_root=str(state),
        provider_config=str(config),
        mission_id=MISSION,
        target_id=TARGET,
    )
    assert second["status"] == "PASS"
    assert second["capabilities"][CAP_DB_WRITE]["status"] == "PASS"
    assert second["capabilities"][CAP_DB_WRITE]["human_gate_approval_evidence_id"] == approval["evidence_id"]

    qualified = qualify_bank_services(r1_path=str(r1), mission_id=MISSION, target_id=TARGET)
    assert qualified["status"] == "PASS"
    assert all(row["status"] == "PASS" for row in qualified["platform_capabilities"].values())

    truth = TruthRuntime(r1)
    probes = [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == PROBE_KIND]
    assert len(probes) == 4


def test_missing_bank_provider_is_field_required_not_fake_pass(tmp_path: Path) -> None:
    r1 = _r1(tmp_path)
    result = probe_bank_services(
        r1_path=str(r1),
        state_root=str(tmp_path / "state"),
        provider_config=str(_provider(tmp_path, include_write=False)),
        mission_id=MISSION,
        target_id=TARGET,
    )
    # DB write is Human-Gated before provider lookup. After approval it will be
    # FIELD_REQUIRED; importantly it is never promoted to PASS by CI.
    request_id = result["db_write_gate_request_id"]
    approve_db_write_probe(
        r1_path=str(r1),
        state_root=str(tmp_path / "state"),
        mission_id=MISSION,
        target_id=TARGET,
        request_id=request_id,
        actor_ref="OPERATOR",
        reason="exercise missing-provider fail closed path",
    )
    rerun = probe_bank_services(
        r1_path=str(r1),
        state_root=str(tmp_path / "state"),
        provider_config=str(_provider(tmp_path, include_write=False)),
        mission_id=MISSION,
        target_id=TARGET,
    )
    assert rerun["status"] == "FIELD_REQUIRED"
    assert rerun["capabilities"][CAP_DB_WRITE]["status"] == "FIELD_REQUIRED"


def test_provider_secret_fields_are_rejected_from_bank_qualification(tmp_path: Path) -> None:
    r1 = _r1(tmp_path)
    result = probe_bank_services(
        r1_path=str(r1),
        state_root=str(tmp_path / "state"),
        provider_config=str(_provider(tmp_path, secret=True)),
        mission_id=MISSION,
        target_id=TARGET,
    )
    assert result["status"] == "FAIL"
    assert result["capabilities"][CAP_AUTH_4A]["status"] == "FAIL"
    assert "SECRET_FIELD_FORBIDDEN" in result["capabilities"][CAP_AUTH_4A]["reason"]
