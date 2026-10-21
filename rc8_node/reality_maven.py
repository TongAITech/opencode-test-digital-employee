"""Bank-reality runner for the first RC8 Maven/JUnit vertical slice.

This command is intentionally stricter than CI contract tests. It requires an
actual Maven command, an actual Maven project with pom.xml, a reachable RC8
Center, and the complete Node -> Center qualification/execution/evidence/R1
chain. CI may exercise this runner with synthetic fixtures, but only a run in
the target bank environment may be labelled BANK_ENV_VERIFIED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rc8_runtime import CapabilityState

from .agent import HttpCenterClient, NodeAgent, NodeAgentError, NodeIdentityStore, detect_platform
from .capabilities import MavenJUnitCapabilityAdapter
from .execution import MavenJUnitExecutionAdapter
from .work_item_execution import execute_maven_junit_work_item


class MavenRealityError(RuntimeError):
    pass


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _resolve_command(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise MavenRealityError("MAVEN_COMMAND_REQUIRED")
    candidate = Path(raw)
    if candidate.is_file():
        return str(candidate.resolve())
    resolved = shutil.which(raw)
    if resolved:
        return resolved
    raise MavenRealityError("MAVEN_COMMAND_NOT_FOUND:%s" % raw)


def _write_summary(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(str(temp), str(path))


def _validate_run_id(run_id: str) -> str:
    value = (run_id or "").strip()
    if not value:
        raise MavenRealityError("REALITY_RUN_ID_REQUIRED")
    if not _SAFE_RUN_ID.match(value):
        raise MavenRealityError("REALITY_RUN_ID_UNSAFE:%s" % value)
    return value


def run_maven_reality(
    *,
    center_url: str,
    node_id: str,
    operator_ref: str,
    state_dir: str,
    project_dir: str,
    maven_command: str,
    run_id: str,
    goals: Optional[List[str]] = None,
    maven_repo: Optional[str] = None,
    allow_online: bool = False,
    require_pass: bool = False,
    strict_portability: bool = False,
) -> Tuple[int, Dict[str, object]]:
    run_id = _validate_run_id(run_id)
    if not node_id.strip():
        raise MavenRealityError("NODE_ID_REQUIRED")
    if not operator_ref.strip():
        raise MavenRealityError("NODE_OPERATOR_REQUIRED")

    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise MavenRealityError("MAVEN_PROJECT_DIR_NOT_FOUND:%s" % project)
    pom = project / "pom.xml"
    if not pom.is_file():
        raise MavenRealityError("MAVEN_POM_NOT_FOUND:%s" % pom)

    resolved_maven = _resolve_command(maven_command)
    local_repo: Optional[Path] = None
    if maven_repo:
        local_repo = Path(maven_repo).resolve()
        if not local_repo.is_dir():
            raise MavenRealityError("MAVEN_LOCAL_REPOSITORY_NOT_FOUND:%s" % local_repo)
    if strict_portability and not allow_online and local_repo is None:
        raise MavenRealityError("STRICT_PORTABILITY_REQUIRES_EXPLICIT_MAVEN_REPO")

    state_root = Path(state_dir).resolve()
    evidence_root = state_root / "reality" / run_id
    summary_path = evidence_root / "reality-result.json"
    preflight_path = evidence_root / "preflight.json"
    platform_info = detect_platform()

    client = HttpCenterClient(center_url)
    health = client.get("/health")
    if health.get("status") != "READY":
        raise MavenRealityError("CENTER_NOT_READY")

    preflight: Dict[str, object] = {
        "schema_version": 1,
        "status": "PREFLIGHT_PASS",
        "run_id": run_id,
        "node_id": node_id.strip(),
        "center": center_url,
        "center_health": dict(health),
        "platform": platform_info,
        "project_dir": str(project),
        "pom": str(pom),
        "pom_exists": True,
        "maven_command": resolved_maven,
        "maven_command_resolved": True,
        "offline": not allow_online,
        "strict_portability": strict_portability,
        "maven_local_repository": str(local_repo) if local_repo else None,
        "explicit_maven_repository": local_repo is not None,
        "generated_at": int(time.time()),
        "truth_note": "PREFLIGHT_PASS proves prerequisites were resolved, not that Maven/JUnit execution passed",
    }
    _write_summary(preflight_path, preflight)

    identity = NodeIdentityStore(str(state_root / "node-identity.json")).load_or_create(
        node_id=node_id.strip(),
        operator_ref=operator_ref.strip(),
        os_family=platform_info["os_family"],
        architecture=platform_info["architecture"],
        shell=platform_info["shell"],
    )
    agent = NodeAgent(identity, client)
    agent.register()
    agent.heartbeat()

    qualification_work_item = "%s-capability" % run_id
    execution_work_item = "%s-execution" % run_id
    qualification_run = "%s-capability" % run_id
    probe_artifact = "%s-maven-probe" % run_id

    client.post(
        "/api/v1/work-items/register",
        {
            "work_item_id": qualification_work_item,
            "test_run_id": qualification_run,
            "stage": "CAPABILITY_QUALIFICATION",
            "scope_refs": [identity.node_id, "maven-junit"],
            "required_capabilities": [],
        },
    )
    agent.lease(qualification_work_item, ttl_seconds=300)
    agent.start(qualification_work_item)
    capability_adapter = MavenJUnitCapabilityAdapter(
        str(evidence_root / "capability"),
        maven_command=resolved_maven,
        timeout_seconds=60,
    )
    qualification = capability_adapter.qualify_through_center(
        agent,
        test_run_id=qualification_run,
        work_item_id=qualification_work_item,
        artifact_id=probe_artifact,
    )
    agent.complete(qualification_work_item)

    base_summary: Dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "node_id": identity.node_id,
        "center": center_url,
        "platform": platform_info,
        "project_dir": str(project),
        "maven_command": resolved_maven,
        "offline": not allow_online,
        "strict_portability": strict_portability,
        "maven_local_repository": str(local_repo) if local_repo else None,
        "preflight_path": str(preflight_path),
        "capability_state": qualification.state.value,
        "capability_evidence_refs": list(qualification.evidence_refs),
        "generated_at": int(time.time()),
        "truth_note": "Only a target-bank run with real Maven/project/Center may be promoted to BANK_ENV_VERIFIED",
    }
    if qualification.state != CapabilityState.VERIFIED:
        base_summary["reality_status"] = "CAPABILITY_NOT_VERIFIED"
        _write_summary(summary_path, base_summary)
        return 20, base_summary

    client.post(
        "/api/v1/work-items/register",
        {
            "work_item_id": execution_work_item,
            "test_run_id": run_id,
            "stage": "EXECUTION",
            "scope_refs": [str(project)],
            "required_capabilities": ["maven-junit"],
        },
    )

    effective_goals: List[str] = []
    if not allow_online:
        effective_goals.append("-o")
    if local_repo is not None:
        effective_goals.append("-Dmaven.repo.local=%s" % local_repo)
    effective_goals.extend(list(goals or ["test"]))

    execution_adapter = MavenJUnitExecutionAdapter(
        str(evidence_root / "execution"),
        maven_command=resolved_maven,
        timeout_seconds=1800,
    )
    result = execute_maven_junit_work_item(
        agent,
        execution_adapter,
        test_run_id=run_id,
        work_item_id=execution_work_item,
        project_dir=str(project),
        event_id="%s-maven-actual" % run_id,
        sequence=1,
        goals=effective_goals,
        lease_ttl_seconds=1800,
    )

    published = result.get("published") if isinstance(result, dict) else None
    if not isinstance(published, dict):
        raise MavenRealityError("REALITY_PUBLISH_RESULT_INVALID")
    center_response = published.get("center")
    if not isinstance(center_response, dict):
        raise MavenRealityError("REALITY_R1_RESPONSE_INVALID")
    receipt = center_response.get("receipt") if isinstance(center_response.get("receipt"), dict) else center_response
    if str(receipt.get("status") or "") not in {"PERSISTENCE_VERIFIED", "IDEMPOTENT_REPLAY"}:
        raise MavenRealityError("REALITY_R1_NOT_PERSISTED")

    completed = result.get("completed")
    work_item = completed.get("work_item") if isinstance(completed, dict) and isinstance(completed.get("work_item"), dict) else completed
    if not isinstance(work_item, dict) or work_item.get("state") != "COMPLETED":
        raise MavenRealityError("REALITY_WORK_ITEM_NOT_COMPLETED")

    execution = result["execution"]
    actual = execution.actual
    base_summary.update(
        {
            "reality_status": "EXECUTION_CHAIN_VERIFIED",
            "work_item_id": execution_work_item,
            "work_item_state": "COMPLETED",
            "actual": {
                "tests": actual.tests,
                "failures": actual.failures,
                "errors": actual.errors,
                "skipped": actual.skipped,
                "passed": actual.passed,
                "xml_files": list(actual.xml_files),
            },
            "artifact_ids": list(published.get("artifact_ids") or []),
            "r1_receipt": dict(receipt),
            "goals": effective_goals,
        }
    )
    if require_pass and not actual.passed:
        base_summary["reality_status"] = "EXECUTION_CHAIN_VERIFIED_TEST_FAILED"
        _write_summary(summary_path, base_summary)
        return 30, base_summary

    _write_summary(summary_path, base_summary)
    return 0, base_summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 Maven/JUnit 行内真实链路验证")
    parser.add_argument("--center", default=os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:4098"))
    parser.add_argument("--node-id", default=os.environ.get("RC8_NODE_ID", ""))
    parser.add_argument("--operator", default=os.environ.get("RC8_NODE_OPERATOR", ""))
    parser.add_argument("--state-dir", default=os.environ.get("RC8_NODE_STATE_DIR", "runtime/rc8-node"))
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--maven", default=os.environ.get("RC8_MVN", "mvn"))
    parser.add_argument("--maven-repo", default=os.environ.get("RC8_MAVEN_REPO", ""))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--goal", action="append", dest="goals")
    parser.add_argument("--allow-online", action="store_true", help="允许 Maven 联网；默认使用 -o 离线模式")
    parser.add_argument("--require-pass", action="store_true", help="除链路验证外，还要求 JUnit Actual PASS")
    parser.add_argument(
        "--strict-portability",
        action="store_true",
        help="严格可搬运验证：离线模式必须显式指定 --maven-repo，禁止悄悄复用默认 ~/.m2",
    )
    args = parser.parse_args(argv)

    if not args.run_id:
        args.run_id = "REALITY-MVN-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), (args.node_id or "node").replace(" ", "-"))
    try:
        code, summary = run_maven_reality(
            center_url=args.center,
            node_id=args.node_id,
            operator_ref=args.operator,
            state_dir=args.state_dir,
            project_dir=args.project_dir,
            maven_command=args.maven,
            run_id=args.run_id,
            goals=args.goals,
            maven_repo=args.maven_repo or None,
            allow_online=args.allow_online,
            require_pass=args.require_pass,
            strict_portability=args.strict_portability,
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        return code
    except (MavenRealityError, NodeAgentError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "REALITY_VALIDATION_FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
