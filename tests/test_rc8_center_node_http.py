from __future__ import annotations

import threading
from pathlib import Path

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_node import HttpCenterClient, NodeAgent, NodeIdentityStore
from rc8_runtime import (
    CapabilityQualification,
    CapabilityState,
    CentralR1RuntimeLedger,
    RuntimeProducerKind,
    runtime_event,
)


def _server(tmp_path: Path):
    repo = MemoryCenterRepository()
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    control = CenterControlPlane(repo, ledger)
    server = create_server(CenterHttpApplication(control), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://127.0.0.1:%s" % server.server_address[1]
    return server, thread, control, repo, ledger, HttpCenterClient(base_url)


def test_node_identity_is_stable_across_node_agent_restart(tmp_path: Path) -> None:
    store = NodeIdentityStore(str(tmp_path / "node" / "node-identity.json"))
    first = store.load_or_create(
        node_id="NODE-1",
        operator_ref="tester-a",
        os_family="windows",
        architecture="x86_64",
        shell="git-bash",
        now=100,
    )
    second = NodeIdentityStore(str(tmp_path / "node" / "node-identity.json")).load_or_create(
        node_id="NODE-1",
        operator_ref="tester-a",
        os_family="windows",
        architecture="x86_64",
        shell="git-bash",
        now=999,
    )
    assert first == second
    assert second.registered_at == 100


def test_node_agent_http_roundtrip_register_qualify_lease_and_runtime_event(tmp_path: Path) -> None:
    server, thread, control, repo, ledger, client = _server(tmp_path)
    try:
        identity = NodeIdentityStore(str(tmp_path / "node-id.json")).load_or_create(
            node_id="NODE-HTTP-1",
            operator_ref="tester-a",
            os_family="windows",
            architecture="x86_64",
            shell="git-bash",
            now=100,
        )
        agent = NodeAgent(identity, client)
        registered = agent.register()
        assert registered["node"]["identity"]["node_id"] == "NODE-HTTP-1"
        assert agent.heartbeat()["node"]["status"] == "IDLE"

        client.post(
            "/api/v1/work-items/register",
            {
                "work_item_id": "WI-HTTP-1",
                "test_run_id": "RUN-HTTP-1",
                "stage": "EXECUTION",
                "scope_refs": ["SCOPE-1"],
                "required_capabilities": ["CAN_CODEGRAPH"],
            },
        )
        agent.report_capability(
            CapabilityQualification(
                node_id="NODE-HTTP-1",
                capability_id="CAN_CODEGRAPH",
                state=CapabilityState.VERIFIED,
                probe_ref="probe://codegraph/real-query",
                evidence_refs=["ART-CODEGRAPH-PROBE"],
                verified_at=100,
            )
        )
        leased = agent.lease("WI-HTTP-1", ttl_seconds=60)
        assert leased["work_item"]["lease_owner_node_id"] == "NODE-HTTP-1"
        assert agent.start("WI-HTTP-1")["work_item"]["state"] == "RUNNING"

        event = runtime_event(
            event_id="EV-HTTP-1",
            test_run_id="RUN-HTTP-1",
            work_item_id="WI-HTTP-1",
            node_id="NODE-HTTP-1",
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="codegraph",
            event_type="TOOL_EXECUTED",
            sequence=1,
            data={"query": "impact"},
        )
        receipt = agent.append_runtime_event(event)
        assert receipt["receipt"]["status"] == "PERSISTENCE_VERIFIED"
        assert len(ledger.runtime_events(test_run_id="RUN-HTTP-1")) == 1
        assert agent.complete("WI-HTTP-1")["work_item"]["state"] == "COMPLETED"

        nodes = client.get("/api/v1/nodes")["items"]
        assert nodes[0]["status"] == "IDLE"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
