from __future__ import annotations

import json
from pathlib import Path

from rc8_center import NodeRecord, NodeStatus
from rc8_center.__main__ import build_application, main
from rc8_runtime import NodeIdentity


def test_center_check_initializes_durable_state_and_r1(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "center"
    assert main(["--state-dir", str(state_dir), "--check"]) == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "RC8_CENTER_READY"
    assert payload["mode"] == "CHECK"
    assert payload["r1_runtime_only"] is True
    assert payload["artifact_store"] == "READY"
    assert (state_dir / "center-state.json").is_file()
    assert (state_dir / "artifact-metadata.json").is_file()
    assert (state_dir / "runtime-state" / "r1" / "event-stream.jsonl").is_file()


def test_center_application_reopens_same_durable_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "center"
    first = build_application(str(state_dir))
    first.control.repository.upsert_node(
        NodeRecord(
            identity=NodeIdentity(
                node_id="NODE-1",
                operator_ref="tester",
                os_family="windows",
                architecture="x86_64",
                shell="git-bash",
                registered_at=1,
            ),
            status=NodeStatus.IDLE,
            first_registered_at=1,
            last_heartbeat_at=2,
        )
    )
    second = build_application(str(state_dir))
    restored = second.control.repository.get_node("NODE-1")
    assert restored is not None
    assert restored.identity.node_id == "NODE-1"
