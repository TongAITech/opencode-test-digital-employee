from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from rc7_runtime.bank_n8_upstream_successor import BankN8UpstreamSuccessorCoordinator, BankN8UpstreamSuccessorError
from rc7_runtime.execution_recovery import RecoveryWorkPlan
from rc7_runtime.models import Artifact
from rc7_runtime.truth_overlay import append_entity


_HELPER_PATH = Path(__file__).with_name("test_rc7_1_bank_n8_reprepare_successor.py")
_SPEC = importlib.util.spec_from_file_location("rc7_1_n8_reprepare_helper", _HELPER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_HELPER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_HELPER)


def _plan() -> RecoveryWorkPlan:
    return RecoveryWorkPlan(
        diagnosis_id="DIAG-AUTH-REPREPARE",
        source_attempt_id="ATT-1",
        action="REAUTH_AND_REPREPARE",
        mode="REPREPARE_THEN_RETRY",
        target_node="RUNTIME",
        retry_allowed=True,
        reprepare_required=True,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="fresh auth and test data are required before retry",
    )


def _coordinator(tmp_path: Path) -> BankN8UpstreamSuccessorCoordinator:
    return BankN8UpstreamSuccessorCoordinator(
        state_root=str(tmp_path / "state"),
        evidence_root=str(tmp_path / "n8"),
    )


def test_reprepare_is_forbidden_after_source_business_execution_started(tmp_path: Path) -> None:
    truth, control, _state_root, _source_path, _source_bytes, _order = _HELPER._setup(tmp_path)
    leased = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == _HELPER.SOURCE
    control.start(_HELPER.SOURCE, worker_ref="retry-worker")

    with pytest.raises(
        BankN8UpstreamSuccessorError,
        match="BANK_N8_REPREPARE_SOURCE_LEASE_REQUIRED",
    ):
        _coordinator(tmp_path).materialize_if_authorized(
            control,
            source_task_id=_HELPER.SOURCE,
            worker_id="retry-worker",
            tc_id=_HELPER.TC_ID,
            target_id=_HELPER.TARGET,
        )

    assert not [
        row for row in truth.query("rc7_evidence", mission_id=_HELPER.MISSION)
        if row.get("kind") == "N8_REPAIR_RECEIPT"
    ]


def test_reprepare_missing_canonical_prepared_artifact_cannot_emit_receipt(tmp_path: Path) -> None:
    truth, control, _state_root, _source_path, _source_bytes, order = _HELPER._setup(tmp_path)
    leased = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == _HELPER.SOURCE
    coordinator = _coordinator(tmp_path)

    with pytest.raises(
        BankN8UpstreamSuccessorError,
        match="N8_SUCCESSOR_PREPARED_ARTIFACT_NOT_UNIQUE",
    ):
        coordinator._accept_reprepare_receipt_leased(
            control,
            work_order=order,
            plan=_plan(),
            prepared_before=_HELPER._prepared("ATT-1"),
            successor_prepared=_HELPER._prepared("ATT-2"),
            worker_id="retry-worker",
        )

    assert not [
        row for row in truth.query("rc7_evidence", mission_id=_HELPER.MISSION)
        if row.get("kind") == "N8_REPAIR_RECEIPT"
    ]


def test_reprepare_tampered_canonical_prepared_artifact_cannot_emit_receipt(tmp_path: Path) -> None:
    truth, control, _state_root, _source_path, _source_bytes, order = _HELPER._setup(tmp_path)
    leased = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == _HELPER.SOURCE

    successor = _HELPER._prepared("ATT-2")
    raw = (json.dumps({"prepared": asdict(successor)}, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path = tmp_path / "tampered-prepared.json"
    path.write_bytes(raw)
    artifact_id = "ART-PREPARED-" + hashlib.sha256(
        (_HELPER.MISSION + "\x1f" + _HELPER.SOURCE + "\x1f" + "ATT-2").encode("utf-8")
    ).hexdigest()[:20]
    append_entity(
        truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=_HELPER.MISSION,
            artifact_type="PREPARED_ATTEMPT",
            producer_task_id=_HELPER.SOURCE,
            content_ref="file://" + str(path),
            evidence_refs=["EVD-PREPARED-ATT-1"],
            content_hash="sha256:" + ("0" * 64),
        ),
        release_id=_HELPER.RELEASE,
    )

    with pytest.raises(
        BankN8UpstreamSuccessorError,
        match="N8_SUCCESSOR_PREPARED_CONTENT_HASH_MISMATCH",
    ):
        _coordinator(tmp_path)._accept_reprepare_receipt_leased(
            control,
            work_order=order,
            plan=_plan(),
            prepared_before=_HELPER._prepared("ATT-1"),
            successor_prepared=successor,
            worker_id="retry-worker",
        )

    assert not [
        row for row in truth.query("rc7_evidence", mission_id=_HELPER.MISSION)
        if row.get("kind") == "N8_REPAIR_RECEIPT"
    ]
