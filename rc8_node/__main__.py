from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Optional

from .agent import HttpCenterClient, NodeAgent, NodeIdentityStore, detect_platform


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 执行节点")
    parser.add_argument("--center", default=os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:4098"))
    parser.add_argument("--node-id", default=os.environ.get("RC8_NODE_ID", ""))
    parser.add_argument("--operator", default=os.environ.get("RC8_NODE_OPERATOR", ""))
    parser.add_argument("--state-dir", default=os.environ.get("RC8_NODE_STATE_DIR", "runtime/rc8-node"))
    parser.add_argument("--heartbeat-interval", type=int, default=int(os.environ.get("RC8_NODE_HEARTBEAT_SECONDS", "15")))
    parser.add_argument("--once", action="store_true", help="注册并发送一次心跳后退出")
    args = parser.parse_args(argv)

    if not args.node_id.strip():
        parser.error("--node-id / RC8_NODE_ID is required")
    if not args.operator.strip():
        parser.error("--operator / RC8_NODE_OPERATOR is required")
    if args.heartbeat_interval <= 0:
        parser.error("heartbeat interval must be > 0")

    platform_info = detect_platform()
    identity_path = Path(args.state_dir) / "node-identity.json"
    identity = NodeIdentityStore(str(identity_path)).load_or_create(
        node_id=args.node_id.strip(),
        operator_ref=args.operator.strip(),
        os_family=platform_info["os_family"],
        architecture=platform_info["architecture"],
        shell=platform_info["shell"],
    )
    agent = NodeAgent(identity, HttpCenterClient(args.center))
    registered = agent.register()
    heartbeat = agent.heartbeat()
    print(
        json.dumps(
            {
                "status": "RC8_NODE_READY",
                "node_id": identity.node_id,
                "center": args.center,
                "platform": platform_info,
                "registered": registered.get("node", {}).get("status"),
                "heartbeat": heartbeat.get("node", {}).get("status"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    if args.once:
        return 0

    try:
        while True:
            time.sleep(args.heartbeat_interval)
            agent.heartbeat()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
