from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError

from .service_r2_2 import *  # noqa: F401,F403
from .service_r2_2 import G4RealExecutionService as _R2_2_G4RealExecutionService, _dict, _g3_state, _text


class G4RealExecutionService(_R2_2_G4RealExecutionService):
    """R2-3: bind every bank coverage measurement to exact goal/app target identity."""

    def create_goal(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        goal_id = _text(data.get("goal_id"), "goal_id")
        affected = [str(value) for value in (data.get("affected_applications") or []) if str(value)]
        if not affected:
            raise RuntimeError("G4_AFFECTED_APPLICATIONS_REQUIRED", goal_id)
        policy = _dict(data.get("coverage_policy") or {}, "coverage_policy")
        target = require_percentage(policy.get("target_pct"))
        source = str(policy.get("source") or "BANK_INCREMENTAL_COVERAGE_PLATFORM")
        if source != "BANK_INCREMENTAL_COVERAGE_PLATFORM":
            raise RuntimeError("G4_ACTUAL_COVERAGE_SOURCE_INVALID", source)
        aggregation = str(policy.get("aggregation_policy") or "PER_AFFECTED_APPLICATION").upper()
        if aggregation != "PER_AFFECTED_APPLICATION" and not bool(policy.get("explicit_override")):
            raise RuntimeError("G4_COVERAGE_AGGREGATION_OVERRIDE_REQUIRED", aggregation)
        target_versions_raw = data.get("affected_application_target_versions")
        if not isinstance(target_versions_raw, Mapping):
            raise RuntimeError("G4_AFFECTED_APPLICATION_TARGET_VERSIONS_REQUIRED", goal_id)
        target_versions = {
            str(app): _text(version, f"affected_application_target_versions.{app}")
            for app, version in target_versions_raw.items()
        }
        if set(target_versions) != set(affected):
            raise RuntimeError("G4_AFFECTED_APPLICATION_TARGET_VERSION_BINDING_MISMATCH", goal_id)
        payload = {
            "goal_id": goal_id,
            "mission_id": mission_id,
            "project_id": _text(data.get("project_id"), "project_id"),
            "release_id": _text(data.get("release_id"), "release_id"),
            "requirement_scope": list(data.get("requirement_scope") or []),
            "affected_applications": affected,
            "affected_application_target_versions": target_versions,
            "goal_type": str(data.get("goal_type") or "COVERAGE_CONVERGENCE").upper(),
            "coverage_policy": {
                "source": source,
                "target_pct": target,
                "aggregation_policy": aggregation,
                "critical_gap_policy": str(policy.get("critical_gap_policy") or "ZERO_UNRESOLVED_CRITICAL"),
            },
            "execution_policy": dict(data.get("execution_policy") or {}),
            "defect_discovery_objective": dict(data.get("defect_discovery_objective") or {"enabled": True, "high_value_hypothesis_refs": []}),
            "status": str(data.get("status") or "ACTIVE").upper(),
        }
        if payload["status"] not in GOAL_STATUSES:
            raise RuntimeError("G4_GOAL_STATUS_INVALID", payload["status"])
        fact = self._record(
            mission_id,
            "TESTING_GOAL",
            payload,
            provenance_refs=("user:testing-goal",),
            fact_id=f"g4:testing-goal:{goal_id}",
        )
        status_fact = self._set_goal_status(
            mission_id,
            goal_id,
            payload["status"],
            reason="GOAL_CREATED",
            provenance_refs=(fact["fact_id"],),
        )
        return {"schema_version": G4_SCHEMA, "status": payload["status"], "truth_source": "R1_EVENT_STREAM", "goal": fact, "goal_status": status_fact}

    def record_coverage_from_g3(self, mission_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _dict(request, "request")
        state = str(data.get("state") or "AVAILABLE").upper()
        if state not in COVERAGE_STATES:
            raise RuntimeError("G4_COVERAGE_STATE_INVALID", state)
        goal_id = _text(data.get("goal_id"), "goal_id")
        goal = self.goal(mission_id, goal_id)["payload"]
        target_versions = dict(goal.get("affected_application_target_versions") or {})
        payload: dict[str, Any] = {
            "measurement_id": _text(data.get("measurement_id"), "measurement_id"),
            "goal_id": goal_id,
            "goal_revision_ref": self._goal_revision_ref(mission_id, goal_id),
            "batch_id": data.get("batch_id"),
            "state": state,
            "source": "BANK_INCREMENTAL_COVERAGE_PLATFORM",
        }
        provenance: list[str] = []
        snapshot_ref = data.get("g3_snapshot_fact_id")
        if state == "AVAILABLE":
            if not snapshot_ref:
                raise RuntimeError("G4_BANK_COVERAGE_SNAPSHOT_REQUIRED", state)
            g3 = _g3_state(self.runtime, mission_id)
            snap = g3.by_id(str(snapshot_ref)) if g3 is not None and hasattr(g3, "by_id") else None
            if snap is None or snap.fact_kind != "INCREMENTAL_COVERAGE_SNAPSHOT":
                raise RuntimeError("G4_G3_BANK_COVERAGE_FACT_REQUIRED", str(snapshot_ref))
            snapshot = dict(snap.payload)
            if snapshot.get("coverage_semantics") != "BANK_EFFECTIVE_INCREMENTAL":
                raise RuntimeError("G4_ACTUAL_COVERAGE_SEMANTICS_INVALID", str(snapshot.get("coverage_semantics")))
            application_id = str(snapshot.get("application_id") or "")
            observed_target = str(snapshot.get("target_version") or "")
            expected_target = str(target_versions.get(application_id) or "")
            identity_ok = (
                application_id in set(str(value) for value in goal.get("affected_applications") or [])
                and bool(expected_target)
                and observed_target == expected_target
                and bool(snapshot.get("source_identity"))
                and snapshot.get("baseline_identity_status") in {"COMMIT_PINNED", "MASTER_ALIAS_ONLY"}
            )
            state = "AVAILABLE" if identity_ok else "SOURCE_IDENTITY_MISMATCH"
            payload.update({
                "state": state,
                "g3_snapshot_fact_id": snap.fact_id,
                "application_id": application_id,
                "target_version": observed_target,
                "expected_target_version": expected_target or None,
                "baseline_identity_status": snapshot.get("baseline_identity_status"),
                "baseline_label": snapshot.get("baseline_label"),
                "source_identity": snapshot.get("source_identity"),
                "observed_at": snapshot.get("observed_at"),
                "provider_profile_ref": next((str(ref) for ref in snap.provenance_refs if str(ref).startswith("g3:coverage_platform_profile:")), None),
                "effective_incremental_coverage_pct": snapshot.get("effective_incremental_coverage_pct") if identity_ok else None,
                "details": list(snapshot.get("details") or []) if identity_ok else [],
                "identity_mismatch_reason": None if identity_ok else "GOAL_APPLICATION_TARGET_VERSION_OR_SOURCE_IDENTITY_MISMATCH",
            })
            provenance.append(snap.fact_id)
        else:
            payload.update({
                "application_id": data.get("application_id"),
                "source_identity": data.get("source_identity"),
                "reason": data.get("reason"),
                "observed_at": str(data.get("observed_at") or now_iso()),
            })
        fact = self._record(
            mission_id,
            "COVERAGE_MEASUREMENT",
            payload,
            provenance_refs=provenance or ("bank-coverage-provider",),
        )
        if state in {"WAITING_REFRESH", "STALE", "SOURCE_IDENTITY_MISMATCH", "SOURCE_UNAVAILABLE", "AUTH_REQUIRED"}:
            self._set_goal_status(mission_id, goal_id, "WAITING_COVERAGE_REFRESH", reason=f"COVERAGE_{state}", provenance_refs=(fact["fact_id"],))
        else:
            self._set_goal_status(mission_id, goal_id, "MEASURING", reason=f"COVERAGE_{state}", provenance_refs=(fact["fact_id"],))
        return {"status": state, "truth_source": "R1_EVENT_STREAM", "measurement": fact, "actual_coverage": payload.get("effective_incremental_coverage_pct") if state == "AVAILABLE" else None}
