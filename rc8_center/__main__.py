from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional

from rc8_runtime import CentralR1RuntimeLedger

from .artifacts import FileArtifactStore
from .control_plane import CenterControlPlane
from .coverage_repository import JsonFileCoverageRepository
from .governance_projection import GovernanceProjectionService
from .governance_repository import JsonFileGovernanceRepository
from .http_server import CenterHttpApplication, create_server
from .json_repository import JsonFileArtifactRepository, JsonFileCenterRepository
from .product_api import CenterProductApplication


def build_application(state_dir: str) -> CenterProductApplication:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    center_repo = JsonFileCenterRepository(str(root / "center-state.json"))
    artifact_repo = JsonFileArtifactRepository(str(root / "artifact-metadata.json"))
    governance_repo = JsonFileGovernanceRepository(str(root / "governance-state.json"))
    coverage_repo = JsonFileCoverageRepository(str(root / "coverage-state.json"))
    ledger = CentralR1RuntimeLedger(str(root / "runtime-state" / "r1" / "event-stream.jsonl"))
    artifact_store = FileArtifactStore(str(root / "artifacts"), artifact_repo)
    control = CenterControlPlane(center_repo, ledger)
    base = CenterHttpApplication(control, artifact_store)
    projection = GovernanceProjectionService(governance_repo, coverage_repo)
    return CenterProductApplication(base, projection)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 中央测试平台启动入口")
    parser.add_argument("--host", default=os.environ.get("RC8_CENTER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RC8_CENTER_PORT", "4098")))
    parser.add_argument("--state-dir", default=os.environ.get("RC8_CENTER_STATE_DIR", "runtime/rc8-center"))
    parser.add_argument("--check", action="store_true", help="初始化并检查持久化目录后退出")
    args = parser.parse_args(argv)

    if args.port < 0 or args.port > 65535:
        parser.error("port must be between 0 and 65535")

    application = build_application(args.state_dir)
    if args.check:
        root = Path(args.state_dir)
        print(
            json.dumps(
                {
                    "status": "RC8_CENTER_READY",
                    "mode": "CHECK",
                    "state_dir": str(root.resolve()),
                    "r1_runtime_only": True,
                    "artifact_store": "READY" if application.artifact_store is not None else "UNAVAILABLE",
                    "governance_projection": "READY",
                    "product_api": "READY",
                    "governance_state": "READY" if (root / "governance-state.json").is_file() else "UNAVAILABLE",
                    "coverage_state": "READY" if (root / "coverage-state.json").is_file() else "UNAVAILABLE",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    server = create_server(application, args.host, args.port)
    actual_host, actual_port = server.server_address[:2]
    print(
        json.dumps(
            {
                "status": "RC8_CENTER_READY",
                "host": actual_host,
                "port": actual_port,
                "state_dir": str(Path(args.state_dir).resolve()),
                "governance_projection": "READY",
                "product_api": "READY",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
