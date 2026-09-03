from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(HERE.parent))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from test_g4_full_same_mission_product_e2e import intake_request


SECRETS = {
    "authorization": "AUTHORIZATION-CLOSURE-SECRET",
    "cookie": "COOKIE-CLOSURE-SECRET",
    "session_id": "SESSION-CLOSURE-SECRET",
    "password": "PASSWORD-CLOSURE-SECRET",
    "otp": "731945",
    "captcha": "CAPTCHA-CLOSURE-SECRET",
}
EXPECTED_CLASSES = {"AUTHORIZATION", "COOKIE", "SESSION", "PASSWORD", "OTP", "CAPTCHA"}


def typed_payload(extra: dict | None = None) -> dict:
    return {**SECRETS, "safe_marker": "SAFE-CLOSURE-VALUE", **(extra or {})}


def classes_from_fact(fact, key: str) -> set[str]:
    value = fact.payload.get(key) or {}
    return set(value.get("classifications") or [])


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g4-closure-sensitive-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        g4 = G4RealExecutionService(runtime, orchestration=orch)
        g4.create_goal(mission_id, {
            "goal_id": "sensitive-closure",
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })

        g4.register_capability(
            mission_id,
            "API",
            "AVAILABLE",
            provider_ref="provider:safe",
            metadata=typed_payload({"provider_observation": "safe"}),
        )
        capability = g4.state(mission_id).latest("CAPABILITY_STATUS")
        capability_meta = dict(capability.payload["metadata"])
        checks["provider_metadata_typed_classes_cover_all_sensitive_channels"] = EXPECTED_CLASSES.issubset(classes_from_fact(capability, "metadata") if False else set(capability_meta["sensitive_ingress"]["classifications"]))
        checks["provider_metadata_drops_credential_keys_before_durable_write"] = not any(key in capability_meta for key in SECRETS) and capability_meta.get("safe_marker") == "SAFE-CLOSURE-VALUE"

        g4.record_blocker_gap(mission_id, {
            "goal_id": "sensitive-closure",
            "gap_id": "gap-sensitive-closure",
            "gap_kind": "AUTH_GAP",
            "severity": "HIGH",
            "reason": "Authorization=Bearer AUTHORIZATION-CLOSURE-SECRET",
            "source_refs": [typed_payload({"source": "manual-observation"})],
        })
        blocker = g4.state(mission_id).latest("BLOCKER_GAP")
        blocker_classes = classes_from_fact(blocker, "sensitive_ingress")
        checks["blocker_ingress_has_typed_and_defense_in_depth_classification"] = EXPECTED_CLASSES.issubset(blocker_classes) and "DEFENSE_IN_DEPTH_PATTERN" in blocker_classes
        checks["blocker_ingress_preserves_only_safe_observation_shape"] = blocker.payload["reason"] == "[REDACTED:SENSITIVE]" and blocker.payload["source_refs"][0].get("safe_marker") == "SAFE-CLOSURE-VALUE" and not any(key in blocker.payload["source_refs"][0] for key in SECRETS)

        g4.record_iteration(mission_id, {
            "goal_id": "sensitive-closure",
            "iteration_id": "iteration-sensitive-closure",
            "coverage_before": {"cfg-data": 10},
            "coverage_after": {"cfg-data": 20},
            "new_changed_lines_covered": ["src/Safe.java:L1"],
            "remaining_coverage_gaps": [],
            "cases_executed": ["TC-SAFE"],
            "new_execution_failures": [typed_payload({"failure": "safe-failure"})],
            "new_observations": [typed_payload({"observation": "safe-observation"})],
            "human_blockers": [typed_payload({"manual": "safe-manual"})],
            "strategy_revision_ref": "strategy-safe",
        })
        iteration = g4.state(mission_id).latest("TEST_LOOP_ITERATION")
        iteration_classes = classes_from_fact(iteration, "sensitive_ingress")
        checks["iteration_ingress_typed_classes_cover_all_sensitive_channels"] = EXPECTED_CLASSES.issubset(iteration_classes)
        checks["iteration_observation_failure_manual_payloads_drop_credentials"] = all(
            not any(key in item for key in SECRETS)
            for field in ("new_execution_failures", "new_observations", "human_blockers")
            for item in iteration.payload[field]
        )

        raw = db.read_bytes()
        absent = {name: value.encode("utf-8") not in raw for name, value in SECRETS.items()}
        checks["authorization_secret_absent_from_r1_storage_bytes"] = absent["authorization"]
        checks["cookie_secret_absent_from_r1_storage_bytes"] = absent["cookie"]
        checks["session_secret_absent_from_r1_storage_bytes"] = absent["session_id"]
        checks["password_secret_absent_from_r1_storage_bytes"] = absent["password"]
        checks["otp_secret_absent_from_r1_storage_bytes"] = absent["otp"]
        checks["captcha_secret_absent_from_r1_storage_bytes"] = absent["captcha"]
        checks["safe_non_sensitive_marker_remains_durable"] = b"SAFE-CLOSURE-VALUE" in raw
        checks["projection_verifies"] = runtime.verify_projection(mission_id).get("ok") is True

    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
