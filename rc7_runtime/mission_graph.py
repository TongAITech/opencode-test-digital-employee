"""Versioned deterministic RC7 Mission graph compiler.

The generic compiler preserves the original v1 default for source/API
compatibility.  Bank Mission bootstrap explicitly opts new Missions into v2.
Persisted graph identity prevents an existing Mission from silently changing
shape after a runtime upgrade.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .models import Task


def _stable_id(prefix: str, mission_id: str, semantic_name: str) -> str:
    raw = (mission_id + "\x1f" + semantic_name).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class MissionTaskGraph:
    mission_id: str
    graph_version: str
    tasks: Tuple[Task, ...]
    artifact_ids: Mapping[str, str]
    logical_stages: Tuple[str, ...]
    conditional_stages: Tuple[str, ...]

    def task(self, node: str) -> Task:
        rows = [task for task in self.tasks if task.node == node]
        if len(rows) != 1:
            raise KeyError("MISSION_GRAPH_NODE_NOT_UNIQUE:%s" % node)
        return rows[0]


class MissionTaskGraphCompiler:
    GRAPH_V1 = "v1"
    GRAPH_V2 = "v2"
    SUPPORTED_GRAPH_VERSIONS = (GRAPH_V1, GRAPH_V2)
    # Generic/internal callers keep field-baseline semantics.  The bank entry
    # point explicitly selects GRAPH_V2 for new Missions.
    DEFAULT_GRAPH_VERSION = GRAPH_V1
    BANK_DEFAULT_GRAPH_VERSION = GRAPH_V2

    NODE_ORDER = (
        "REQUIREMENT_ANALYSIS", "CODE_ANALYSIS", "TEST_DESIGN",
        "SCRIPT_READINESS", "EXECUTION",
    )
    REQUIRED_CAPABILITIES = {
        "REQUIREMENT_ANALYSIS": ("requirement_reasoning",),
        "CODE_ANALYSIS": ("code_reasoning", "code_reality"),
        "TEST_DESIGN": ("test_design",),
        "SCRIPT_READINESS": ("test_automation",),
        "EXECUTION": ("test_execution",),
    }
    OUTPUT_TYPES = {
        "REQUIREMENT_ANALYSIS": "REQUIREMENT_MODEL",
        "CODE_ANALYSIS": "CODE_IMPACT_MODEL",
        "TEST_DESIGN": "TEST_DESIGN_MODEL",
        "SCRIPT_READINESS": "EXECUTABLE_SCRIPT",
        "EXECUTION": "EXECUTION_CONCLUSION",
    }
    PRIORITY = {
        "REQUIREMENT_ANALYSIS": 10, "CODE_ANALYSIS": 20,
        "TEST_DESIGN": 30, "SCRIPT_READINESS": 40, "EXECUTION": 50,
    }
    _V1_DEPS = {
        "REQUIREMENT_ANALYSIS": (),
        "CODE_ANALYSIS": ("REQUIREMENT_ANALYSIS",),
        "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
        "SCRIPT_READINESS": ("TEST_DESIGN",),
        "EXECUTION": ("SCRIPT_READINESS",),
    }
    _V1_LOGICAL = (
        "REQUIREMENT_ANALYSIS", "REQUIREMENT_SUFFICIENCY",
        "CODE_ANALYSIS", "CODE_SUFFICIENCY", "TEST_DESIGN",
        "TEST_DESIGN_SUFFICIENCY", "SCRIPT_READINESS", "EXECUTION",
        "MISSION_CONVERGENCE",
    )

    _V2_NODES = (
        "REALITY_RECON", "REQUIREMENT_ANALYSIS", "CODE_ANALYSIS",
        "TEST_DESIGN", "SCRIPT_READINESS", "PRECONDITION_DATA",
        "EXECUTION", "REPORT",
    )
    _V2_CAPS = {
        "REALITY_RECON": ("bank_reality", "code_reality"),
        "REQUIREMENT_ANALYSIS": ("requirement_reasoning",),
        "CODE_ANALYSIS": ("code_reasoning", "code_reality"),
        "TEST_DESIGN": ("test_design",),
        "SCRIPT_READINESS": ("test_automation",),
        "PRECONDITION_DATA": ("execution_preparation", "test_data"),
        "EXECUTION": ("test_execution",),
        "REPORT": ("test_reporting",),
    }
    _V2_OUTPUTS = {
        "REALITY_RECON": "BANK_REALITY_SNAPSHOT",
        "REQUIREMENT_ANALYSIS": "REQUIREMENT_MODEL",
        "CODE_ANALYSIS": "CODE_IMPACT_MODEL",
        "TEST_DESIGN": "TEST_DESIGN_MODEL",
        "SCRIPT_READINESS": "EXECUTABLE_SCRIPT",
        "PRECONDITION_DATA": "PREPARED_EXECUTION_CONTEXT",
        "EXECUTION": "EXECUTION_CONCLUSION",
        "REPORT": "MISSION_REPORT_CANDIDATE",
    }
    _V2_PRIORITY = {
        "REALITY_RECON": 5, "REQUIREMENT_ANALYSIS": 10,
        "CODE_ANALYSIS": 20, "TEST_DESIGN": 30,
        "SCRIPT_READINESS": 40, "PRECONDITION_DATA": 45,
        "EXECUTION": 50, "REPORT": 80,
    }
    _V2_DEPS = {
        "REALITY_RECON": (),
        "REQUIREMENT_ANALYSIS": ("REALITY_RECON",),
        "CODE_ANALYSIS": ("REALITY_RECON", "REQUIREMENT_ANALYSIS"),
        "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
        "SCRIPT_READINESS": ("TEST_DESIGN",),
        "PRECONDITION_DATA": ("SCRIPT_READINESS",),
        "EXECUTION": ("PRECONDITION_DATA",),
        "REPORT": ("EXECUTION",),
    }
    _V2_INPUTS = {
        "REALITY_RECON": (),
        "REQUIREMENT_ANALYSIS": ("REALITY_RECON",),
        "CODE_ANALYSIS": ("REALITY_RECON", "REQUIREMENT_ANALYSIS"),
        "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
        "SCRIPT_READINESS": ("TEST_DESIGN",),
        "PRECONDITION_DATA": ("SCRIPT_READINESS",),
        "EXECUTION": ("PRECONDITION_DATA",),
        "REPORT": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS", "TEST_DESIGN", "EXECUTION"),
    }
    _V2_LOGICAL = (
        "REALITY_RECON", "REQUIREMENT_ANALYSIS", "REQUIREMENT_SUFFICIENCY",
        "CODE_ANALYSIS", "CODE_SUFFICIENCY", "TEST_DESIGN",
        "TEST_DESIGN_SUFFICIENCY", "SCRIPT_READINESS", "PRECONDITION_DATA",
        "EXECUTION", "FAILURE_DIAGNOSIS", "RECOVERY_RETRY", "DEFECT_REVIEW",
        "REPORT", "MISSION_CONVERGENCE",
    )
    _V2_CONDITIONAL = ("FAILURE_DIAGNOSIS", "RECOVERY_RETRY", "DEFECT_REVIEW")

    def __init__(self, graph_version: str = GRAPH_V1) -> None:
        version = str(graph_version or "").strip().lower()
        if version not in self.SUPPORTED_GRAPH_VERSIONS:
            raise ValueError("MISSION_GRAPH_VERSION_UNSUPPORTED:%s" % graph_version)
        self.graph_version = version
        if version == self.GRAPH_V1:
            self.NODE_ORDER = tuple(type(self).NODE_ORDER)
            self.REQUIRED_CAPABILITIES = dict(type(self).REQUIRED_CAPABILITIES)
            self.OUTPUT_TYPES = dict(type(self).OUTPUT_TYPES)
            self.PRIORITY = dict(type(self).PRIORITY)
            self._deps = dict(self._V1_DEPS)
            self._inputs = dict(self._V1_DEPS)
            self.logical_stages = tuple(self._V1_LOGICAL)
            self.conditional_stages = ()
        else:
            self.NODE_ORDER = tuple(self._V2_NODES)
            self.REQUIRED_CAPABILITIES = dict(self._V2_CAPS)
            self.OUTPUT_TYPES = dict(self._V2_OUTPUTS)
            self.PRIORITY = dict(self._V2_PRIORITY)
            self._deps = dict(self._V2_DEPS)
            self._inputs = dict(self._V2_INPUTS)
            self.logical_stages = tuple(self._V2_LOGICAL)
            self.conditional_stages = tuple(self._V2_CONDITIONAL)

    def contract(self) -> Dict[str, Any]:
        payload = {
            "graph_version": self.graph_version,
            "task_nodes": list(self.NODE_ORDER),
            "logical_stages": list(self.logical_stages),
            "conditional_stages": list(self.conditional_stages),
            "dependencies": {k: list(v) for k, v in self._deps.items()},
            "output_types": dict(self.OUTPUT_TYPES),
        }
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["contract_sha256"] = hashlib.sha256(body).hexdigest()
        return payload

    def compile(self, mission_id: str, *, external_inputs: Optional[Mapping[str, Sequence[str]]] = None) -> MissionTaskGraph:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("MISSION_ID_REQUIRED")
        mission_id = mission_id.strip()
        external_inputs = dict(external_inputs or {})
        unknown = sorted(set(external_inputs).difference(self.NODE_ORDER))
        if unknown:
            raise ValueError("MISSION_GRAPH_EXTERNAL_INPUT_NODE_UNKNOWN:%s" % ",".join(unknown))
        normalized: Dict[str, Tuple[str, ...]] = {}
        for node, refs in external_inputs.items():
            if isinstance(refs, (str, bytes)):
                raise ValueError("MISSION_GRAPH_EXTERNAL_INPUTS_MUST_BE_SEQUENCE:%s" % node)
            items = tuple(refs)
            values = tuple(ref.strip() for ref in items if isinstance(ref, str) and ref.strip())
            if len(values) != len(items):
                raise ValueError("MISSION_GRAPH_EXTERNAL_INPUT_REF_INVALID:%s" % node)
            normalized[node] = tuple(dict.fromkeys(values))

        task_ids = {node: _stable_id("TASK", mission_id, node) for node in self.NODE_ORDER}
        artifact_ids = {node: _stable_id("ART", mission_id, self.OUTPUT_TYPES[node]) for node in self.NODE_ORDER}
        tasks = []
        for node in self.NODE_ORDER:
            inherited = [artifact_ids[name] for name in self._inputs[node]]
            criteria = [
                "independent evaluator accepts %s output" % node,
                "output and acceptance evidence are durable in R1",
            ]
            if node in {"REQUIREMENT_ANALYSIS", "CODE_ANALYSIS", "TEST_DESIGN"}:
                criteria.append("independent sufficiency gate passes; producer self-acceptance is forbidden")
            if node == "PRECONDITION_DATA":
                criteria.append("preconditions and test data are verified before execution; writes require governed authorization")
            if node == "REPORT":
                criteria.append("report is evidence-derived and cannot declare TEST_SUFFICIENT")
            tasks.append(Task(
                task_id=task_ids[node], mission_id=mission_id, node=node, task_type="PRODUCE",
                objective="Produce evaluator-ready %s output" % self.OUTPUT_TYPES[node],
                required_capabilities=list(self.REQUIRED_CAPABILITIES[node]),
                dependency_task_ids=[task_ids[name] for name in self._deps[node]],
                input_artifact_refs=list(dict.fromkeys(inherited + list(normalized.get(node, ())))),
                acceptance_criteria=criteria, priority=self.PRIORITY[node],
            ))
        return MissionTaskGraph(
            mission_id=mission_id, graph_version=self.graph_version, tasks=tuple(tasks),
            artifact_ids=dict(artifact_ids), logical_stages=tuple(self.logical_stages),
            conditional_stages=tuple(self.conditional_stages),
        )

    def install(self, control_plane: Any, mission_id: str, *, external_inputs: Optional[Mapping[str, Sequence[str]]] = None) -> MissionTaskGraph:
        graph = self.compile(mission_id, external_inputs=external_inputs)
        for task in graph.tasks:
            control_plane.register_task(task)
        return graph
