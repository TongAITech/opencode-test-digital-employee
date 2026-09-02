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
from test_g3_testing_intelligence_product_path import binding, intake_request
from test_g4_background_auto_resume_wave2 import seed_g3, task


def main() -> int:
    checks: dict[str, bool] = {}
    secrets = [
        "Bearer AUTH-SECRET-777",
        "JSESSIONID=COOKIE-SECRET-888",
        "SETCOOKIE-SECRET-999",
        "ACCESS-TOKEN-AAA",
        "REFRESH-TOKEN-BBB",
        "SESSION-CCC",
        "JSESSION-DDD",
        "BANK-PASSWORD-EEE",
        "654321",
        "CAPTCHA-FFF",
    ]
    with tempfile.TemporaryDirectory(prefix="g4-wave2-taint-") as td:
        root = Path(td)
        db = root / "runtime-spine.db"
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
        runtime = create_canonical_runtime(root, db_path=db)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
        mission_id = orch.start_test(intake_request())["intake"]["intake"]["mission_id"]
        case_fact, strategy_id = seed_g3(runtime, mission_id)
        attempt = binding(orch.propose_plan(mission_id, {"objective": "taint ingress", "tasks": [task()], "dependencies": []})["next"])
        g4 = G4RealExecutionService(runtime, orchestration=orch)
        g4.create_goal(mission_id, {
            "goal_id": "goal-taint",
            "project_id": "PFC",
            "release_id": "R2",
            "affected_applications": ["cfg-data"],
            "affected_application_target_versions": {"cfg-data": "V2"},
            "coverage_policy": {"target_pct": 95},
        })
        g4.create_batch(mission_id, {
            "batch_id": "batch-taint",
            "goal_id": "goal-taint",
            "case_refs": [case_fact["fact_id"]],
            "strategy_version_id": strategy_id,
            "target_application": "cfg-data",
            "status": "RUNNING",
        })
        common = {
            "task_id": attempt["task_id"],
            "attempt_id": attempt["attempt_id"],
            "case_id": "TC-AUTO",
            "case_version": "TC-AUTO:v1",
            "case_spec_fact_id": case_fact["fact_id"],
            "execution_batch_id": "batch-taint",
            "executor_capability": "API",
            "expected": "response is accepted",
            "oracle_result": "PASS",
            "oracle_reason": "fixture",
            "evidence_refs": ["artifact:safe-response"],
            "source_identity": "sut:test",
        }
        api = g4.record_step_result(mission_id, {
            **common,
            "step_id": "api-sensitive",
            "actual": {
                "headers": {
                    "Authorization": secrets[0],
                    "Cookie": secrets[1],
                    "Set-Cookie": secrets[2],
                },
                "body": {
                    "access_token": secrets[3],
                    "refresh_token": secrets[4],
                    "session_id": secrets[5],
                    "JSESSIONID": secrets[6],
                    "nested": {"password": secrets[7], "otp": secrets[8], "captcha": secrets[9]},
                },
            },
            "auth_context_ref": secrets[0],
            "evidence_metadata": {"transport": {"Authorization": secrets[0]}, "nested": {"Cookie": secrets[1]}},
        })
        payload = api["result"]["payload"]
        classes = set(payload["evidence_taint"]["classifications"])
        checks["typed_channels_classified"] = {"AUTHORIZATION", "COOKIE", "TOKEN", "SESSION", "PASSWORD", "OTP", "CAPTCHA"}.issubset(classes)
        checks["typed_channels_redacted_before_fact"] = all(value == "[REDACTED:SENSITIVE]" for value in [
            payload["actual"]["headers"]["Authorization"], payload["actual"]["headers"]["Cookie"], payload["actual"]["headers"]["Set-Cookie"],
            payload["actual"]["body"]["access_token"], payload["actual"]["body"]["refresh_token"], payload["actual"]["body"]["session_id"], payload["actual"]["body"]["JSESSIONID"],
            payload["actual"]["body"]["nested"]["password"], payload["actual"]["body"]["nested"]["otp"], payload["actual"]["body"]["nested"]["captcha"], payload["auth_context_ref"],
        ])
        browser = g4.record_step_result(mission_id, {
            **common,
            "step_id": "browser-sensitive-entry",
            "executor_capability": "BROWSER_UI",
            "sensitive_entry_mode": True,
            "actual": {"value": "654321", "label": "one-time code"},
            "evidence_metadata": {"screen_text": "654321", "field": "generic"},
        })
        bp = browser["result"]["payload"]
        checks["sensitive_entry_mode_taints_generic_actual"] = bp["actual"]["value"] == "[REDACTED:SENSITIVE]" and bp["actual"]["label"] == "[REDACTED:SENSITIVE]" and "SENSITIVE_ENTRY" in bp["evidence_taint"]["classifications"]
        serialized = json.dumps([fact.to_dict() for fact in g4.state(mission_id).facts], sort_keys=True)
        checks["no_raw_secret_in_g4_projection"] = all(secret not in serialized for secret in secrets)
        raw_files = b"".join(path.read_bytes() for path in root.glob("runtime-spine.db*") if path.is_file())
        checks["no_raw_secret_in_r1_storage_files"] = all(secret.encode("utf-8") not in raw_files for secret in secrets)
        checks["redaction_policy_is_durable_without_secret"] = payload["evidence_taint"]["policy"] == "TYPED_INGRESS_REDACTION_V1" and payload["evidence_taint"]["raw_sensitive_value_persisted"] is False and payload["evidence_taint"]["redaction_count"] >= 10
        checks["projection_verifies"] = runtime.verify_projection(mission_id).get("ok") is True
    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
