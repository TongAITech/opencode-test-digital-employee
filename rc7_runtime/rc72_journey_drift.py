"""Evidence-backed Journey drift quarantine and mandatory fresh human approval.

An official Journey is immutable. A page/locator/network change evidenced by
a failed real execution blocks reuse of that asset; it cannot be silently
self-healed or re-promoted by an AI worker. A different, freshly benchmarked
and human-approved Official Journey is required to resume the L4/L5 Case.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Mapping

from rc6_runtime import contracts as registry
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_journey_promotion import install_rc72_journey_promotion_overlay

_DRIFT = "rc72_journey_asset_drift"
_EVENT = "RC72_JOURNEY_ASSET_DRIFT_UPSERTED"
_ALLOWED = {"PAGE_CHANGED", "LOCATOR_CHANGED", "NETWORK_BEHAVIOR_CHANGED"}


def _validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    for key in ("drift_id", "official_asset_id", "execution_id", "mission_id",
                "release_id", "release_batch_id", "obligation_id", "reason", "status"):
        out[key] = registry._require_str(out, key)
    if out["reason"] not in _ALLOWED or out["status"] != "BLOCKED_REAPPROVAL":
        raise registry.DomainValidationError("JOURNEY_DRIFT_REAPPROVAL_REQUIRED")
    evidence = out.get("failure_evidence_refs")
    if not isinstance(evidence, list) or not evidence or any(not isinstance(r, str) or not r.strip() for r in evidence):
        raise registry.DomainValidationError("JOURNEY_DRIFT_FAILURE_EVIDENCE_REQUIRED")
    if not isinstance(out.get("reported_at"), int) or out["reported_at"] < 0:
        raise registry.DomainValidationError("JOURNEY_DRIFT_TIMESTAMP_INVALID")
    out["artifact_type"] = _DRIFT
    out["artifact_version"] = registry._artifact_version(out)
    return out


def install_rc72_journey_drift_overlay() -> None:
    install_rc72_journey_promotion_overlay()
    registry.VALIDATORS[_DRIFT] = _validate
    _truth.BUCKETS[_DRIFT] = "rc72_journey_asset_drifts"
    _truth.EVENT_TYPES[_EVENT] = (_DRIFT, "drift_id")
    _truth.IDENTITY_FIELDS[_DRIFT] = "drift_id"


class JourneyDriftService:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_journey_drift_overlay()
        self.truth = truth
        self.release_id = release_id
        if not hasattr(truth.projection, "rc72_journey_asset_drifts"):
            setattr(truth.projection, "rc72_journey_asset_drifts", {})
        truth.projection._versions.setdefault(_DRIFT, {})

    def assert_eligible(self, official_asset_id: str) -> None:
        if self.truth.query(_DRIFT, official_asset_id=official_asset_id):
            raise ContractError("OFFICIAL_JOURNEY_DRIFT_REAPPROVAL_REQUIRED")

    def report(self, *, drift_id: str, execution_id: str, reason: str) -> Dict[str, Any]:
        if reason not in _ALLOWED:
            raise ContractError("JOURNEY_DRIFT_REASON_INVALID")
        existing = self.truth.query(_DRIFT, drift_id=drift_id)
        if existing:
            raise ContractError("JOURNEY_DRIFT_ALREADY_RECORDED")
        rows = self.truth.query("rc72_official_journey_execution", execution_id=execution_id)
        if len(rows) != 1 or rows[0].get("state") != "FAILED":
            raise ContractError("JOURNEY_DRIFT_REQUIRES_FAILED_EXECUTION")
        execution = rows[0]
        assets = self.truth.query(
            "rc72_official_journey_asset", official_asset_id=execution["official_asset_id"])
        if len(assets) != 1:
            raise ContractError("JOURNEY_DRIFT_OFFICIAL_ASSET_REQUIRED")
        asset = assets[0]
        if execution.get("mission_id") != asset.get("mission_id") or execution.get("obligation_id") != asset.get("obligation_id"):
            raise ContractError("JOURNEY_DRIFT_SCOPE_MISMATCH")
        steps = self.truth.query("rc72_official_journey_execution_step", execution_id=execution_id)
        failures = [step for step in steps if step.get("status") == "FAILED"]
        if len(failures) != 1:
            raise ContractError("JOURNEY_DRIFT_FAILURE_STEP_REQUIRED")
        refs = failures[0].get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise ContractError("JOURNEY_DRIFT_REAL_FAILURE_EVIDENCE_REQUIRED")
        for ref in refs:
            if not isinstance(ref, str) or not ref.startswith("file://"):
                raise ContractError("JOURNEY_DRIFT_REAL_FAILURE_EVIDENCE_REQUIRED")
            from urllib.parse import unquote, urlsplit
            if not Path(unquote(urlsplit(ref).path)).is_file():
                raise ContractError("JOURNEY_DRIFT_EVIDENCE_NOT_FOUND")
        payload = {
            "drift_id": drift_id, "official_asset_id": asset["official_asset_id"],
            "execution_id": execution_id, "mission_id": asset["mission_id"],
            "release_batch_id": asset["release_batch_id"],
            "obligation_id": asset["obligation_id"], "release_id": self.release_id,
            "reason": reason, "status": "BLOCKED_REAPPROVAL",
            "failure_evidence_refs": list(refs),
            "reported_at": int(time.time()), "artifact_version": 1}
        self.truth.append_atomic(_EVENT, payload)
        return payload


install_rc72_journey_drift_overlay()
