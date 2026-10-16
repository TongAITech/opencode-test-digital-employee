"""Clean Windows package qualification for RC7 Field Hardening.

This is deliberately narrower than Bank Final qualification. It proves that a
freshly built and freshly extracted Windows transport package can boot its own
bundled Python, create/resume a graph-v2 Bank Mission, execute the Runtime-owned
Reality Recon stage against R1, pass Mission Conformance, and hand off only the
next Producer stage. It never sets real_mission_pass or bank_field_pass.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Optional, Sequence

from rc6_runtime.truth import TruthRuntime

from rc7_release.package import PACKAGE_LOCAL_PYTHON, verify_package
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_conformance import MissionConformanceChecker
from rc7_runtime.mission_stage_dispatch import MissionStageDispatcher
from rc7_runtime.reality_recon import RuntimeRealityReconService


class WindowsCleanQualificationError(RuntimeError):
    pass


REQUIRED_FIELD_HARDENED_FILES = (
    "rc7_runtime/bank_mission.py",
    "rc7_runtime/mission_graph.py",
    "rc7_runtime/reality_recon.py",
    "rc7_runtime/mission_conformance.py",
    "rc7_runtime/mission_stage_dispatch.py",
    "rc7_release/windows_clean_qualification.py",
)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _require_productized_files(root: Path) -> None:
    missing = [rel for rel in REQUIRED_FIELD_HARDENED_FILES if not (root / rel).is_file()]
    if missing:
        raise WindowsCleanQualificationError(
            "FIELD_HARDENED_PRODUCT_FILE_MISSING:%s" % ",".join(sorted(missing))
        )


def qualify(package_root: Path) -> Dict[str, object]:
    if os.name != "nt":
        raise WindowsCleanQualificationError("WINDOWS_CLEAN_QUALIFICATION_REQUIRES_WINDOWS")

    root = Path(package_root).expanduser().resolve()
    if not root.is_dir():
        raise WindowsCleanQualificationError("PACKAGE_ROOT_NOT_FOUND")
    _require_productized_files(root)

    initial_integrity = verify_package(root)
    if initial_integrity.get("package_local_python_bundled") is not True:
        raise WindowsCleanQualificationError("PACKAGE_LOCAL_PYTHON_REQUIRED")

    expected_python = root / PACKAGE_LOCAL_PYTHON
    if not expected_python.is_file():
        raise WindowsCleanQualificationError("PACKAGE_LOCAL_PYTHON_NOT_FOUND")
    if not _same_path(Path(sys.executable), expected_python):
        raise WindowsCleanQualificationError("QUALIFICATION_MUST_RUN_WITH_PACKAGE_LOCAL_PYTHON")

    source_commit = (root / "SOURCE_COMMIT").read_text(encoding="utf-8").strip().lower()
    if len(source_commit) != 40:
        raise WindowsCleanQualificationError("PACKAGE_SOURCE_COMMIT_INVALID")

    run_token = uuid.uuid4().hex[:12]
    mission_id = "RC7-WINDOWS-CLEAN-%s-%s" % (source_commit[:12], run_token)
    release_id = "RC7-FIELD-HARDENED-%s" % source_commit[:12]
    goal = "Qualify freshly extracted RC7 Windows package Mission Graph v2 runtime handoff"
    state_root = root / "runtime-state" / "windows-clean-qualification"
    r1 = state_root / "r1" / "event-stream.jsonl"

    started = start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id=release_id,
        goal=goal,
    )
    if started.get("status") != "STARTED" or started.get("graph_version") != "v2":
        raise WindowsCleanQualificationError("CLEAN_BANK_MISSION_V2_START_REQUIRED")

    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, release_id, mission_id)
    initial_conformance = MissionConformanceChecker(truth).check(mission_id)
    if initial_conformance.status != "PASS":
        raise WindowsCleanQualificationError(
            "INITIAL_MISSION_CONFORMANCE_FAILED:%s" % ",".join(initial_conformance.violations)
        )

    dispatcher = MissionStageDispatcher(control)
    initial_route = dispatcher.next_route()
    if initial_route is None or initial_route.node != "REALITY_RECON":
        raise WindowsCleanQualificationError("INITIAL_RUNTIME_REALITY_ROUTE_REQUIRED")
    if initial_route.owner != "RUNTIME" or initial_route.action != "RUNTIME_HANDLER":
        raise WindowsCleanQualificationError("REALITY_RECON_RUNTIME_OWNER_REQUIRED")

    reality = RuntimeRealityReconService(evidence_root=str(state_root / "evidence"))
    snapshot = reality.reconcile(
        control,
        initial_route.task_id,
        facts={
            "release_id": release_id,
            "source_revision": "git:%s" % source_commit,
            "repository_ref": "repo://TongAITech/opencode-test-digital-employee",
            "runtime_profile": "BANK_PROTECTED",
        },
        evidence_refs=(
            "git://%s" % source_commit,
            "package://PACKAGE_MANIFEST.json",
        ),
    )
    if snapshot.task_state != "PASS":
        raise WindowsCleanQualificationError("RUNTIME_REALITY_RECON_DID_NOT_PASS")

    # Recreate Truth/Control objects to prove the transition is durable rather
    # than an in-memory side effect of the first process objects.
    replay_truth = TruthRuntime(r1)
    replay_control = ClosedLoopControlPlane(replay_truth, release_id, mission_id)
    after_reality = MissionConformanceChecker(replay_truth).check(mission_id)
    if after_reality.status != "PASS":
        raise WindowsCleanQualificationError(
            "POST_REALITY_MISSION_CONFORMANCE_FAILED:%s" % ",".join(after_reality.violations)
        )

    next_route = MissionStageDispatcher(replay_control).next_route()
    if next_route is None or next_route.node != "REQUIREMENT_ANALYSIS":
        raise WindowsCleanQualificationError("REQUIREMENT_PRODUCER_HANDOFF_REQUIRED")
    if next_route.owner != "PRODUCER_WORKER" or next_route.action != "PRODUCER_WORKER":
        raise WindowsCleanQualificationError("REQUIREMENT_MUST_ROUTE_TO_PRODUCER_WORKER")

    resumed = start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id=release_id,
        goal=goal,
    )
    if resumed.get("status") != "RESUMED" or resumed.get("graph_version") != "v2":
        raise WindowsCleanQualificationError("CLEAN_BANK_MISSION_RESUME_REQUIRED")

    identities = [
        row for row in replay_truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == "RC7_RUNTIME_IDENTITY"
    ]
    if len(identities) != 1 or identities[0].get("content_ref") != "git://%s" % source_commit:
        raise WindowsCleanQualificationError("PACKAGE_RUNTIME_IDENTITY_EVIDENCE_REQUIRED")

    # Runtime-generated truth is intentionally excluded from package checksums;
    # integrity must still pass after the Mission has written its durable R1.
    final_integrity = verify_package(root)
    if final_integrity.get("status") != "PASS":
        raise WindowsCleanQualificationError("POST_RUNTIME_PACKAGE_INTEGRITY_FAILED")

    return {
        "status": "PASS",
        "qualification": "WINDOWS_CLEAN_PACKAGE",
        "scope": "PACKAGE_BOOTSTRAP_R1_GRAPH_V2_RUNTIME_HANDOFF",
        "source_commit": source_commit,
        "package_root": str(root),
        "package_local_python": str(expected_python),
        "mission_id": mission_id,
        "graph_version": "v2",
        "r1_path": str(r1),
        "initial_route": {
            "node": initial_route.node,
            "owner": initial_route.owner,
            "action": initial_route.action,
        },
        "next_route": {
            "node": next_route.node,
            "owner": next_route.owner,
            "action": next_route.action,
        },
        "reality_snapshot_hash": snapshot.content_hash,
        "runtime_identity_evidence_id": identities[0].get("evidence_id"),
        "real_mission_pass": False,
        "bank_field_pass": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qualify a freshly extracted RC7 Windows transport package")
    parser.add_argument("--package-root", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = qualify(Path(args.package_root))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
