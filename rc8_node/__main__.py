from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Optional

from .agent import HttpCenterClient, NodeIdentityStore, detect_platform
from .autonomous_claim_client import AutonomousClaimClient
from .autonomous_dispatcher import AutonomousWorkerDispatcher
from .dsh_json_runner import DshJsonRunner
from .formal_agent import FormalNodeAgent
from .n7_execution_worker import N7ExecutionDispatchWorker
from .requirement_analysis_worker import RequirementAnalysisWorker
from .requirement_sufficiency_worker import RequirementSufficiencyWorker
from .scope_intake_worker import ScopeIntakeWorker


# Only stages with a real node worker may be advertised as executable.  This is
# intentionally smaller than the N1-N10 mission chain today; the node must not
# call itself fully autonomous while CODE/DESIGN/N5/N6/N8/N9/N10 workers are
# still Center-only or not wired into the node runtime.
_AUTONOMOUS_STAGES = (
    "SCOPE_INTAKE",
    "REQUIREMENT_ANALYSIS",
    "REQUIREMENT_SUFFICIENCY",
    "APPLICABLE_LAYER_EXECUTION",
)

# Full single-node proof is fail-closed against this denominator.  Keep this in
# stage order so the readiness output is useful as a construction gap list.
_N1_N10_REQUIRED_STAGES = (
    "SCOPE_INTAKE",
    "REQUIREMENT_ANALYSIS",
    "REQUIREMENT_SUFFICIENCY",
    "CODE_ANALYSIS",
    "CODE_SUFFICIENCY",
    "RISK_TEST_MODEL",
    "TEST_DESIGN",
    "DESIGN_SUFFICIENCY",
    "PRECONDITION_DATA_PREP",
    "EXECUTABLE_SPEC",
    "APPLICABLE_LAYER_EXECUTION",
    "FAILURE_COVERAGE_EVALUATION",
    "MISSION_SUFFICIENCY",
    "REPORT_RELEASE",
)


def _autonomous_readiness() -> tuple[bool, tuple[str, ...]]:
    supported = set(_AUTONOMOUS_STAGES)
    missing = tuple(stage for stage in _N1_N10_REQUIRED_STAGES if stage not in supported)
    return (not missing, missing)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _build_dispatcher(args, identity, center: HttpCenterClient) -> AutonomousWorkerDispatcher:
    dsh_patch = str(args.dsh_patch or "").strip()
    if not dsh_patch:
        raise ValueError("--dsh-patch / RC8_DSH_PATCH is required in autonomous mode")
    formal_agent = FormalNodeAgent(identity, center)
    work_root = Path(args.work_dir or (Path(args.state_dir) / "work"))
    work_root.mkdir(parents=True, exist_ok=True)
    analysis_runner = DshJsonRunner(
        dsh_bin=args.dsh_bin,
        patch_path=dsh_patch,
        cwd=args.dsh_cwd or None,
        timeout_seconds=args.dsh_timeout,
    )
    workers = {
        "SCOPE_INTAKE": ScopeIntakeWorker(
            agent=formal_agent,
            work_dir=str(work_root / "scope-intake"),
        ),
        "REQUIREMENT_ANALYSIS": RequirementAnalysisWorker(
            agent=formal_agent,
            dsh_runner=analysis_runner,
            work_dir=str(work_root / "requirement-analysis"),
        ),
        "REQUIREMENT_SUFFICIENCY": RequirementSufficiencyWorker(
            agent=formal_agent,
            work_dir=str(work_root / "requirement-sufficiency"),
        ),
        "APPLICABLE_LAYER_EXECUTION": N7ExecutionDispatchWorker(
            agent=formal_agent,
            dsh_runner=analysis_runner,
            work_dir=str(work_root / "n7-execution"),
            center_url=args.center,
            http_timeout_seconds=args.http_timeout,
        ),
    }
    return AutonomousWorkerDispatcher(
        claimant=AutonomousClaimClient(args.center, identity.node_id, timeout_seconds=args.http_timeout),
        workers=workers,
        ttl_seconds=args.lease_ttl,
        idle_sleep_seconds=args.claim_interval,
    )


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 执行节点")
    parser.add_argument("--center", default=os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:4098"))
    parser.add_argument("--node-id", default=os.environ.get("RC8_NODE_ID", ""))
    parser.add_argument("--operator", default=os.environ.get("RC8_NODE_OPERATOR", ""))
    parser.add_argument("--state-dir", default=os.environ.get("RC8_NODE_STATE_DIR", "runtime/rc8-node"))
    parser.add_argument("--heartbeat-interval", type=int, default=int(os.environ.get("RC8_NODE_HEARTBEAT_SECONDS", "15")))
    parser.add_argument("--once", action="store_true", help="注册并发送一次心跳后退出")
    parser.add_argument(
        "--autonomous",
        action="store_true",
        default=_env_flag("RC8_NODE_AUTONOMOUS"),
        help="启用已验证 Stage 白名单的自主领取与执行",
    )
    parser.add_argument("--test-run-id", default=os.environ.get("RC8_NODE_TEST_RUN_ID", ""), help="可选：仅处理指定 TestRun")
    parser.add_argument("--claim-interval", type=float, default=float(os.environ.get("RC8_NODE_CLAIM_INTERVAL_SECONDS", "1")))
    parser.add_argument("--lease-ttl", type=int, default=int(os.environ.get("RC8_NODE_LEASE_TTL_SECONDS", "60")))
    parser.add_argument("--http-timeout", type=int, default=int(os.environ.get("RC8_NODE_HTTP_TIMEOUT_SECONDS", "30")))
    parser.add_argument("--work-dir", default=os.environ.get("RC8_NODE_WORK_DIR", ""))
    parser.add_argument("--dsh-bin", default=os.environ.get("RC8_DSH_BIN", "dsh"))
    parser.add_argument("--dsh-patch", default=os.environ.get("RC8_DSH_PATCH", ""))
    parser.add_argument("--dsh-cwd", default=os.environ.get("RC8_DSH_CWD", ""))
    parser.add_argument("--dsh-timeout", type=int, default=int(os.environ.get("RC8_DSH_TIMEOUT_SECONDS", "300")))
    args = parser.parse_args(argv)

    if not args.node_id.strip():
        parser.error("--node-id / RC8_NODE_ID is required")
    if not args.operator.strip():
        parser.error("--operator / RC8_NODE_OPERATOR is required")
    if args.heartbeat_interval <= 0:
        parser.error("heartbeat interval must be > 0")
    if args.claim_interval < 0:
        parser.error("claim interval must be >= 0")
    if args.lease_ttl <= 0:
        parser.error("lease ttl must be > 0")
    if args.http_timeout <= 0:
        parser.error("http timeout must be > 0")
    if args.dsh_timeout <= 0:
        parser.error("dsh timeout must be > 0")
    if args.autonomous and not str(args.dsh_patch or "").strip():
        parser.error("--dsh-patch / RC8_DSH_PATCH is required in autonomous mode")

    platform_info = detect_platform()
    identity_path = Path(args.state_dir) / "node-identity.json"
    identity = NodeIdentityStore(str(identity_path)).load_or_create(
        node_id=args.node_id.strip(),
        operator_ref=args.operator.strip(),
        os_family=platform_info["os_family"],
        architecture=platform_info["architecture"],
        shell=platform_info["shell"],
    )
    center = HttpCenterClient(args.center, timeout_seconds=args.http_timeout)
    agent = FormalNodeAgent(identity, center)
    registered = agent.register()
    heartbeat = agent.heartbeat()
    full_autonomous_ready, missing_stages = _autonomous_readiness()
    if args.autonomous:
        readiness_status = "RC8_NODE_AUTONOMOUS_READY" if full_autonomous_ready else "RC8_NODE_AUTONOMOUS_PARTIAL"
    else:
        readiness_status = "RC8_NODE_READY"
    ready = {
        "status": readiness_status,
        "node_id": identity.node_id,
        "center": args.center,
        "platform": platform_info,
        "registered": registered.get("node", {}).get("status"),
        "heartbeat": heartbeat.get("node", {}).get("status"),
        "autonomous": bool(args.autonomous),
        "n1_n10_autonomous_ready": bool(args.autonomous and full_autonomous_ready),
        "supported_stages": list(_AUTONOMOUS_STAGES) if args.autonomous else [],
        "missing_n1_n10_stages": list(missing_stages) if args.autonomous else [],
        "test_run_id": str(args.test_run_id or "").strip() or None,
    }
    print(json.dumps(ready, ensure_ascii=False, sort_keys=True), flush=True)
    if args.once:
        return 0

    if not args.autonomous:
        try:
            while True:
                time.sleep(args.heartbeat_interval)
                agent.heartbeat()
        except KeyboardInterrupt:
            return 0

    dispatcher = _build_dispatcher(args, identity, center)
    test_run_id = str(args.test_run_id or "").strip() or None
    last_heartbeat = time.monotonic()
    try:
        while True:
            outcome = dispatcher.run_once(test_run_id=test_run_id)
            now = time.monotonic()
            if now - last_heartbeat >= args.heartbeat_interval:
                agent.heartbeat()
                last_heartbeat = now
            if outcome.status == "IDLE" and args.claim_interval > 0:
                time.sleep(args.claim_interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
