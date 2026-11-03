"""C09 signed N7 ToolDispatch adapter for approved, immutable L4/L5 Journey assets.

A group attaches this callable to the existing signed dispatch adapter map
under the explicit tool name 'journey_playwright'. Do not call it outside
N6/N7 admission. SignedToolDispatchService persists IN_FLIGHT before invoking
this adapter, so cold resume cannot repeat unknown business side effects.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from .models import ContractError
from .rc72_browser_resources import BrowserAccessMode
from .rc72_journey_drift import JourneyDriftService
from .rc72_official_journey_execution import OfficialJourneyExecutionService


class SignedN7OfficialJourneyAdapter:
    tool_name = "journey_playwright"

    def __init__(self, execution: OfficialJourneyExecutionService) -> None:
        if not isinstance(execution, OfficialJourneyExecutionService):
            raise ContractError("JOURNEY_N7_EXECUTION_SERVICE_REQUIRED")
        self.execution = execution

    def _scope(self, contract: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, str]:
        if not isinstance(contract, Mapping) or not isinstance(context, Mapping):
            raise ContractError("JOURNEY_N7_FROZEN_CONTRACT_REQUIRED")
        route = contract.get("tool_route")
        if not isinstance(route, Mapping) or route.get("tool") != self.tool_name:
            raise ContractError("JOURNEY_N7_TOOL_ROUTE_MISMATCH")
        request = contract.get("request")
        if not isinstance(request, Mapping):
            raise ContractError("JOURNEY_N7_FROZEN_REQUEST_REQUIRED")
        asset_id = request.get("official_asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ContractError("JOURNEY_N7_OFFICIAL_ASSET_ID_REQUIRED")
        if request.get("source_ref") != "official-journey://" + asset_id:
            raise ContractError("JOURNEY_N7_SOURCE_PROVENANCE_INVALID")
        assets = self.execution.truth.query(
            "rc72_official_journey_asset", official_asset_id=asset_id)
        if len(assets) != 1:
            raise ContractError("JOURNEY_N7_APPROVED_ASSET_NOT_FOUND")
        asset = assets[0]
        if asset.get("status") != "OFFICIAL" or asset.get("official") is not True or asset.get("executable") is not True:
            raise ContractError("JOURNEY_N7_ASSET_NOT_APPROVED")
        if asset.get("field_benchmark_verified") is not True or asset.get("human_field_verified") is not True:
            raise ContractError("JOURNEY_N7_FIELD_APPROVAL_REQUIRED")
        if request.get("approval_scope_digest") != asset.get("approval_scope_digest"):
            raise ContractError("JOURNEY_N7_APPROVAL_DIGEST_MISMATCH")
        expected = {
            "mission_id": asset["mission_id"],
            "release_batch_id": asset["release_batch_id"],
            "requirement_id": asset["requirement_id"],
            "sst_id": asset["sst_id"],
            "obligation_id": asset["obligation_id"],
        }
        for field, value in expected.items():
            if contract.get(field) != value:
                raise ContractError("JOURNEY_N7_%s_MISMATCH" % field.upper())
        workitem_id = context.get("workitem_id")
        attempt_id = context.get("attempt_id")
        worker_id = context.get("worker_id")
        session_id = context.get("session_id")
        leases = context.get("browser_lease_ids")
        if not all(isinstance(value, str) and value.strip()
                   for value in (workitem_id, attempt_id, worker_id, session_id)):
            raise ContractError("JOURNEY_N7_ATTEMPT_SCOPE_REQUIRED")
        if not isinstance(leases, list) or len(leases) != 1:
            raise ContractError("JOURNEY_N7_ONE_BROWSER_LEASE_REQUIRED")
        bindings = self.execution.truth.query(
            "rc72_workitem_attempt_binding", workitem_id=workitem_id)
        bound = [row for row in bindings if
                 row.get("mission_id") == asset["mission_id"]
                 and row.get("attempt_id") == attempt_id
                 and row.get("worker_id") == worker_id
                 and row.get("session_id") == session_id
                 and row.get("case_id") == contract.get("case_id")]
        if len(bound) != 1:
            raise ContractError("JOURNEY_N7_CASE_ATTEMPT_BINDING_MISMATCH")
        return {
            "asset_id": asset_id, "workitem_id": workitem_id,
            "attempt_id": attempt_id, "worker_id": worker_id,
            "session_id": session_id, "browser_lease_id": leases[0],
            "case_id": contract["case_id"],
        }

    def preflight(self, *, contract: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        scope = self._scope(contract, context)
        asset = self.execution.truth.query(
            "rc72_official_journey_asset", official_asset_id=scope["asset_id"])[0]
        JourneyDriftService(self.execution.truth, release_id=self.execution.release_id).assert_eligible(scope["asset_id"])
        self.execution._binding(
            mission_id=asset["mission_id"], workitem_id=scope["workitem_id"],
            attempt_id=scope["attempt_id"], worker_id=scope["worker_id"],
            session_id=scope["session_id"])
        # Reuse B's authoritative resource fence; no client-owned lease boolean.
        self.execution.browser_pool.assert_usable(
            browser_lease_id=scope["browser_lease_id"], mission_id=asset["mission_id"],
            workitem_id=scope["workitem_id"], attempt_id=scope["attempt_id"],
            worker_id=scope["worker_id"], access_mode=BrowserAccessMode.WRITE)

    def __call__(self, *, contract: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        self.preflight(contract=contract, context=context)
        scope = self._scope(contract, context)
        # Deterministic id for same signed Attempt. A new Attempt has a new id.
        payload = json.dumps(
            [scope["asset_id"], scope["workitem_id"], scope["attempt_id"], contract["case_id"]],
            ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        execution_id = "N7J-" + hashlib.sha256(payload).hexdigest()[:24]
        result = self.execution.execute(
            execution_id=execution_id, official_asset_id=scope["asset_id"],
            workitem_id=scope["workitem_id"], attempt_id=scope["attempt_id"],
            worker_id=scope["worker_id"], session_id=scope["session_id"],
            browser_lease_id=scope["browser_lease_id"])
        events = sorted(self.execution.truth.query(
            "rc72_official_journey_execution_step", execution_id=execution_id),
            key=lambda row: row["sequence"])
        execution = self.execution.truth.query(
            "rc72_official_journey_execution", execution_id=execution_id)[0]
        if not events:
            raise ContractError("JOURNEY_N7_EXECUTION_RECEIPTS_MISSING")
        return {
            "journey": {
                "official_asset_id": scope["asset_id"],
                "execution_id": execution_id,
                "case_id": scope["case_id"],
                "state": result.state.value,
                "failure_code": execution.get("failure_code"),
                "actual_refs": [ref for row in events for ref in row["actual_refs"]],
                "evidence_refs": [ref for row in events for ref in row["evidence_refs"]],
                "step_count": len(events),
            }
        }
