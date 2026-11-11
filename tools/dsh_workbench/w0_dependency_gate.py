"""W0–W4 design, implementation and release prerequisite DAG validator.

Static correctness only. This does NOT approve actual release or QA evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Any


class GateViolation(ValueError):
    pass


PHASES = {"W0": 0, "W1": 1, "W2": 2, "W3": 3, "W4": 4}
KINDS = {"design", "implementation", "integration", "field", "license"}


def validate_gate_graph(data: Mapping[str, Any]) -> list[str]:
    """Reject circular design gates and missing transitive W2/W3/W4 release prerequisites."""
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

    # FG16: the release must be guarded by real W2/W3/W4 QA, not only
    # W1 success and a license entry. Design CI never substitutes QA evidence.
    required_gates = {
        "WB-F02_FUNCTIONAL_QA_PASS": "W2",
        "WB-F03_AUTONOMOUS_QA_PASS": "W3",
        "WB-D04_OFFLINE_QUALIFICATION_PASS": "W4",
        "WB-A04_FINAL_INTEGRATION_ACCEPTED": "W4",
        "WB-F04_FIELD_QA_PASS": "W4",
    }
    if any(gid not in indexed or indexed[gid]["phase"] != phase
           for gid, phase in required_gates.items()):
        raise GateViolation("REQUIRED_RELEASE_GATE_MISSING")
    direct_requirements = {
        "WB-F02_FUNCTIONAL_QA_PASS": {
            "WB-C05_IMPLEMENTATION_QA_PASS",
            "WB-B08_IMPLEMENTATION_QA_PASS",
            "WB-D03_IMPLEMENTATION_QA_PASS",
        },
        "WB-F03_AUTONOMOUS_QA_PASS": {
            "WB-E05_IMPLEMENTATION_QA_PASS",
            "WB-E06_IMPLEMENTATION_QA_PASS",
            "WB-C06_IMPLEMENTATION_QA_PASS",
        },
        "WB-D04_OFFLINE_QUALIFICATION_PASS": {
            "WB-D03_IMPLEMENTATION_QA_PASS",
        },
        "WB-F04_FIELD_QA_PASS": {
            "WB-F03_AUTONOMOUS_QA_PASS",
            "WB-D04_OFFLINE_QUALIFICATION_PASS",
        },
        "WB-A04_FINAL_INTEGRATION_ACCEPTED": {
            "WB-F04_FIELD_QA_PASS",
            "WB-F02_FUNCTIONAL_QA_PASS",
        },
    }
    for gid, dependencies in direct_requirements.items():
        if not dependencies.issubset(set(indexed[gid]["depends_on"])):
            raise GateViolation("RELEASE_PREDECESSOR_MISSING")

    def ancestors(gid: str) -> set[str]:
        found: set[str] = set()
        frontier = list(indexed[gid]["depends_on"])
        while frontier:
            dep = frontier.pop()
            if dep in found:
                continue
            found.add(dep)
            frontier.extend(indexed[dep]["depends_on"])
        return found

    # Mandatory cross-wave gates must all appear in the *transitive* release
    # predecessor closure. E07 Replay is optional, so never a release blocker.
    mandatory_release = {
        "WB-F01_INTEGRATION_QA_PASS",
        "WB-F02_FUNCTIONAL_QA_PASS",
        "WB-F03_AUTONOMOUS_QA_PASS",
        "WB-D04_OFFLINE_QUALIFICATION_PASS",
        "WB-F04_FIELD_QA_PASS",
        "WB-A04_FINAL_INTEGRATION_ACCEPTED",
        "WB-A02_LICENSE_RELEASE_APPROVED",
    }
    mandatory_release.update(gid for gid in indexed
                             if indexed[gid]["phase"] in ("W2", "W3") and
                             gid != "WB-E07_OPTIONAL_REPLAY_QA_PASS")
    if not mandatory_release.issubset(ancestors("WB-W4_BANK_RELEASE_APPROVED")):
        raise GateViolation("RELEASE_PREDECESSOR_CLOSURE_INCOMPLETE")
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
