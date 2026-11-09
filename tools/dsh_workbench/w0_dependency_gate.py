"""W0/W1 design-vs-implementation dependency guard (not a live task scheduler)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Any


class GateViolation(ValueError):
    pass


PHASES = {"W0": 0, "W1": 1, "W2": 2, "W3": 3, "W4": 4}
KINDS = {"design", "implementation", "integration", "field", "license"}


def validate_gate_graph(data: Mapping[str, Any]) -> list[str]:
    """Validate a declared DAG; especially forbid W1 implementation to unlock W0 signoff."""
    if not isinstance(data, Mapping) or data.get("schema") != "dsh-workbench-gates/v1":
        raise GateViolation("UNKNOWN_GATE_SCHEMA")
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        raise GateViolation("NO_GATES")
    indexed = {}
    for gate in gates:
        if not isinstance(gate, Mapping) or not isinstance(gate.get("id"), str):
            raise GateViolation("INVALID_GATE")
        gid = gate["id"]
        if not gid.strip() or gid in indexed or gate.get("phase") not in PHASES or gate.get("kind") not in KINDS:
            raise GateViolation("INVALID_GATE")
        deps = gate.get("depends_on")
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise GateViolation("INVALID_DEPENDENCIES")
        if gate["phase"] == "W0" and gate["kind"] != "design":
            raise GateViolation("W0_NOT_DESIGN_GATE")
        indexed[gid] = gate

    for gid, gate in indexed.items():
        for dep in gate["depends_on"]:
            if dep not in indexed:
                raise GateViolation("UNKNOWN_DEPENDENCY")
            target = indexed[dep]
            if PHASES[target["phase"]] > PHASES[gate["phase"]]:
                raise GateViolation("PHASE_BACK_EDGE")
            if gate["phase"] == "W0" and target["kind"] != "design":
                raise GateViolation("DESIGN_REQUIRES_IMPLEMENTATION")

    expected = {
        "WB-A03_CONTRACT_SIGNED": "W0",
        "WB-F00_DESIGN_ACCEPTED": "W0",
        "WB-W0_DESIGN_FROZEN": "W0",
        "WB-B01_IMPLEMENTATION_QA_PASS": "W1",
        "WB-F01_INTEGRATION_QA_PASS": "W1",
        "WB-A02_LICENSE_RELEASE_APPROVED": "W4",
        "WB-W4_BANK_RELEASE_APPROVED": "W4",
    }
    if any(gid not in indexed or indexed[gid]["phase"] != phase for gid, phase in expected.items()):
        raise GateViolation("REQUIRED_GATE_MISSING")
    if not {"WB-A03_CONTRACT_SIGNED", "WB-W0_DESIGN_FROZEN"}.issubset(
        set(indexed["WB-B01_IMPLEMENTATION_QA_PASS"]["depends_on"])
    ):
        raise GateViolation("DESIGN_SIGNOFF_NOT_PREREQUISITE")
    if not {"WB-A02_LICENSE_RELEASE_APPROVED", "WB-F04_FIELD_QA_PASS"}.issubset(
        set(indexed["WB-W4_BANK_RELEASE_APPROVED"]["depends_on"])
    ):
        raise GateViolation("RELEASE_LICENSE_OR_FIELD_GATE_MISSING")
    visiting = set()
    complete = set()
    ordered = []

    def visit(gid: str) -> None:
        if gid in visiting:
            raise GateViolation("GATE_CYCLE")
        if gid in complete:
            return
        visiting.add(gid)
        for dep in indexed[gid]["depends_on"]:
            visit(dep)
        visiting.remove(gid)
        complete.add(gid)
        ordered.append(gid)

    for gid in indexed:
        visit(gid)
    return ordered


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        order = validate_gate_graph(json.loads(Path(args.manifest).read_text(encoding="utf-8")))
    except (GateViolation, ValueError, OSError) as exc:
        print("W0_W1_GATE_BLOCKED: " + str(exc))
        return 2
    print("W0_W1_GATE_DAG_PASS count=%d; DESIGN_SIGNOFF_NOT_PRODUCT_QA" % len(order))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
