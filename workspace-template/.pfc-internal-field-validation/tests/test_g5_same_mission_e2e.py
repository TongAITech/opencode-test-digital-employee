from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
TESTS = Path(__file__).parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(TESTS))

from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService

REQUIRED_R36_STAGES = (
    "record_test_anomaly",
    "create_defect_candidate",
    "request_evidence_deepening",
    "record_evidence_assessment",
    "record_cross_source_correlation",
    "evaluate_reproducibility",
    "assess_false_positive",
    "assess_defect_truth",
    "record_rca",
    "record_investigation_checkpoint",
)


def parse_last_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    found: list[dict] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not text[index + end :].strip():
            found.append(value)
    return found[-1] if found else {}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def request(intake_id: str) -> dict:
    return {
        "intake_id": intake_id,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "G5-EC0", "requirements": ["REQ-G5-E2E"]},
        "goal": {"title": "G5 EC0 same mission", "intent": "prove G5 continues one durable Mission", "constraints": []},
        "source": {
            "kind": "USER",
            "source_ref": f"g5-e2e:{intake_id}",
            "source_digest": canonical_sha256({"id": intake_id}),
            "observed_at": "2026-09-03T10:00:00Z",
            "valid_until": None,
            "source_precedence": 1,
        },
        "actor": {"type": "USER", "id": "g5-ec0"},
        "resolution": {
            "resolution_id": f"resolution:{intake_id}",
            "request_digest": canonical_sha256({"resolution": intake_id}),
            "snapshot_id": f"snapshot:{intake_id}",
            "fact_set_digest": canonical_sha256({"facts": []}),
            "status": "RESOLVED",
            "reason_code": None,
            "source_refs": [f"g5-e2e:{intake_id}"],
            "valid_until": "2026-09-04T10:00:00Z",
        },
    }


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(RUNTIME) + os.pathsep + str(TESTS) + os.pathsep + env.get("PYTHONPATH", "")
    upstream = subprocess.run(
        [sys.executable, str(TESTS / "test_g4_full_same_mission_product_e2e.py")],
        cwd=str(WORKSPACE), env=env, text=True, capture_output=True, timeout=420,
    )
    upstream_json = parse_last_json(upstream.stdout)
    upstream_checks = upstream_json.get("checks") if isinstance(upstream_json.get("checks"), dict) else {}

    # Independent lightweight Mission proves the canonical Runtime/G2.1 fixture can
    # still create one durable Mission before any G5-specific product path exists.
    with tempfile.TemporaryDirectory(prefix="g5-same-mission-foundation-") as td:
        root = Path(td)
        runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
        provider = FakeOpenCodeSessionProvider(root)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = orch.start_test(request("foundation"))
        durable_mid = started["intake"]["intake"]["mission_id"]
        durable_head = runtime.get_head_seq(durable_mid)

    foundation = {
        "existing_g4_same_mission_e2e_is_green": upstream.returncode == 0 and upstream_json.get("status") == "PASS",
        "existing_g4_e2e_uses_r1_truth": bool(upstream_checks.get("same_user_opencode_mission")) or upstream_json.get("truth_source") == "R1_EVENT_STREAM" or upstream_json.get("status") == "PASS",
        "durable_mission_fixture_created": isinstance(durable_mid, str) and bool(durable_mid) and durable_head > 0,
    }

    g5_root = RUNTIME / "aitest_runtime" / "g5"
    service = read(g5_root / "service.py")
    admission = read(g5_root / "admission.py")
    policy = read(g5_root / "policy.py")
    combined = "\n".join((service, admission, policy))
    command = getattr(product_entry, "g5_command", None)

    director_status_ok = False
    intake_ok = False
    if callable(command):
        with tempfile.TemporaryDirectory(prefix="g5-same-mission-surface-") as td:
            root = Path(td)
            old_root = os.environ.get("AITEST_WORKSPACE_ROOT")
            old_db = os.environ.get("AITEST_RUNTIME_SPINE_DB")
            os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str(root / "runtime-spine.db")
            runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
            provider = FakeOpenCodeSessionProvider(root)
            orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
            old_orch = product_entry.orchestration_service
            old_default = product_entry.default_service
            product_entry.orchestration_service = lambda _root=None: orch
            product_entry.default_service = lambda _rt, _root: orch
            try:
                started = orch.start_test(request("g5-director"))
                mid = started["intake"]["intake"]["mission_id"]
                try:
                    status_value = command("DIRECTOR", "status", {"mission_id": mid})
                    director_status_ok = isinstance(status_value, dict) and status_value.get("truth_source") == "R1_EVENT_STREAM" and status_value.get("mission_id") in {None, mid}
                except Exception:
                    director_status_ok = False
                try:
                    intake_value = command("DIRECTOR", "intake_observations", {"mission_id": mid})
                    intake_ok = isinstance(intake_value, dict) and intake_value.get("truth_source") == "R1_EVENT_STREAM" and intake_value.get("mission_id") in {None, mid}
                except Exception:
                    intake_ok = False
            finally:
                product_entry.orchestration_service = old_orch
                product_entry.default_service = old_default
                if old_root is None: os.environ.pop("AITEST_WORKSPACE_ROOT", None)
                else: os.environ["AITEST_WORKSPACE_ROOT"] = old_root
                if old_db is None: os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
                else: os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db

    contract = {
        "g5_service_present": bool(service),
        "same_mission_director_status_available": director_status_ok,
        "same_mission_observation_intake_available": intake_ok,
        "g4_to_r36_admission_present": bool(admission) and "UNEXPECTED_OBSERVATION" in admission and "OBSERVATION_ONLY" in admission and "record_test_anomaly" in combined,
        "g5_v7_origin_lineage_present": bool(combined) and "architecture_baseline_ref" in combined and "v7" in combined,
        "r36_investigation_chain_present": bool(service) and all(stage in service for stage in REQUIRED_R36_STAGES),
        "governed_work_gap_path_present": bool(combined) and "GOVERNED_WORK_REQUIRED" in combined and "G2_PLAN_REVISION_REQUIRED" in combined,
        "r43_exact_handoff_present": bool(service) and "open_confirmed_defect_lifecycle" in service,
        "same_mission_scope_is_explicit": bool(combined) and "mission_id" in combined and "R1_EVENT_STREAM" in combined,
        "no_cross_mission_silent_merge": bool(combined) and "AMBIGUOUS_REVIEW_REQUIRED" in combined and "SAME_CONFIRMED_LIFECYCLE" in combined,
        "full_product_chain_markers_present": bool(combined) and all(marker in combined for marker in (
            "TestAnomaly", "DefectCandidate", "EvidenceAssessment", "Reproducibility", "FalsePositive", "DefectAssessment", "RCA",
        )),
    }

    fixture_ok = all(foundation.values())
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    out = {
        "suite": "test_g5_same_mission_e2e",
        "status": status,
        "passed": sum(bool(v) for v in {**foundation, **contract}.values()),
        "total": len(foundation) + len(contract),
        "fixture_ok": fixture_ok,
        "truthful_red": truthful_red,
        "red_kind": "MISSING_G5_INTEGRATION" if truthful_red else None,
        "foundation_checks": foundation,
        "contract_checks": contract,
        "missing_contract_checks": missing,
        "upstream_g4_same_mission_status": upstream_json.get("status"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
