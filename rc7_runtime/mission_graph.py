"""Canonical RC7 mission task graph compiler.

The runtime, not the chat coordinator, owns the Mission graph.  Graph v2 makes
bank-runtime prerequisites, execution preparation and reporting explicit while
keeping repair/diagnosis/defect work event-driven.  Independent sufficiency
stages are part of the durable graph contract but are not ordinary producer
Tasks: acceptance authority remains in Evaluation truth, never in the worker
that produced the candidate.

Graph versions are deterministic.  Existing v1 Missions can therefore resume
without graph drift while new v2 Missions can opt in to the expanded contract.
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
        matches = [task for task in self.tasks if task.node == node]
        if len(matches) != 1:
            raise KeyError("MISSION_GRAPH_NODE_NOT_UNIQUE:%s" % node)
        return matches[0]


class MissionTaskGraphCompiler:
    """Compile/install deterministic RC7 Mission DAGs.

    v1 is the field baseline shipped in the original RC7 package.
    v2 is the hardened contract:

      Reality -> Requirement -> Code -> Test Design -> Script Readiness
      -> Precondition/Data -> Execution -> Report -> Mission Convergence

    Requirement/Code/Test-Design sufficiency remain independent Evaluation
    authority and are represented explicitly in ``logical_stages``.  Failure
    diagnosis/recovery and defect review are conditional stages spawned by
    trusted execution gaps rather than unconditional happy-path tasks.
    """

    GRAPH_V1 = "v1"
    GRAPH_V2 = "v2"
    SUPPORTED_GRAPH_VERSIONS = (GRAPH_V1, GRAPH_V2)
    DEFAULT_GRAPH_VERSION = GRAPH_V2

    # Legacy public constants are retained for callers that import the class
    # attributes directly.  Instance attributes are version-specific.
    NODE_ORDER = (
        "REQUIREMENT_ANALYSIS",
        "CODE_ANALYSIS",
        "TEST_DESIGN",
        "SCRIPT_READINESS",
        "EXECUTION",
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
        "REQUIREMENT_ANALYSIS": 10,
        "CODE_ANALYSIS": 20,
        "TEST_DESIGN": 30,
        "SCRIPT_READINESS": 40,
        "EXECUTION": 50,
    }

    _V1_DEPENDENCIES = {
        "REQUIREMENT_ANALYSIS": (),
        "CODE_ANALYSIS": ("REQUIREMENT_ANALYSIS",),
        "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
        "SCRIPT_READINESS": ("TEST_DESIGN",),
        "EXECUTION": ("SCRIPT_READINESS",),
    }
    _V1_INPUTS = dict(_V1_DEPENDENCIES)
    _V1_LOGICAL_STAGES = (
        "REQUIREMENT_ANALYSIS",
        "REQUIREMENT_SUFFICIENCY",
        "CODE_ANALYSIS",
        "CODE_SUFFICIENCY",
        "TEST_DESIGN",
        "TEST_DESIGN_SUFFICIENCY",
        "SCRIPT_READINESS",
        "EXECUTION",
        "MISSION_CONVERGENCE",
    )

    _V2_NODE_ORDER = (
        "REALITY_RECON",
        "REQUIREMENT_ANALYSIS",
        "CODE_ANALYSIS",
        "TEST_DESIGN",
        "SCRIPT_READINESS",
        "PRECONDITION_DATA",
        "EXECUTION",
        "REPORT",
    )
    _V2_REQUIRED_CAPABILITIES = {
        "REALITY_RECON": ("bank_reality", "code_reality"),
        "REQUIREMENT_ANALYSIS": ("requirement_reasoning",),
        "CODE_ANALYSIS": ("code_reasoning", "code_reality"),
        "TEST_DESIGN": ("test_design",),
        "SCRIPT_READINESS": ("test_automation",),
        "PRECONDITION_DATA": ("execution_preparation", "test_data"),
        "EXECUTION": ("test_execution",),
        "REPORT": ("test_reporting",),
    }
    _V2_OUTPUT_TYPES = {
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
        "REALITY_RECON": 5,
        "REQUIREMENT_ANALYSIS": 10,
        "CODE_ANALYSIS": 20,
        "TEST_DESIGN": 30,
        "SCRIPT_READINESS": 40,
        "PRECONDITION_DATA": 45,
        "EXECUTION": 50,
        "REPORT": 80,
    }
    _V2_DEPENDENCIES = {
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
    _V2_LOGICAL_STAGES = (
        "REALITY_RECON",
        "REQUIREMENT_ANALYSIS",
        "REQUIREMENT_SUFFICIENCY",
        "CODE_ANALYSIS",
        "CODE_SUFFICIENCY",
        "TEST_DESIGN",
        "TEST_DESIGN_SUFFICIENCY",
        "SCRIPT_READINESS",
        "PRECONDITION_DATA",
        "EXECUTION",
        "FAILURE_DIAGNOSIS",
        "RECOVERY_RETRY",
        "DEFECT_REVIEW",
        "REPORT",
        "MISSION_CONVERGENCE",
    )
    _V2_CONDITIONAL_STAGES = (
        "FAILURE_DIAGNOSIS",
        "RECOVERY_RETRY",
        "DEFECT_REVIEW",
    )

    def __init__(self, graph_version: str = DEFAULT_GRAPH_VERSION) -> None:
        version = str(graph_version or "").strip().lower()
        if version not in self.SUPPORTED_GRAPH_VERSIONS:
            raise ValueError("MISSION_GRAPH_VERSION_UNSUPPORTED:%s" % graph_version)
        self.graph_version = version
        if version == self.GRAPH_V1:
            self.NODE_ORDER = tuple(type(self).NODE_ORDER)
            self.REQUIRED_CAPABILITIES = dict(type(self).REQUIRED_CAPABILITIES)
            self.OUTPUT_TYPES = dict(type(self).OUTPUT_TYPES)
            self.PRIORITY = dict(type(self).PRIORITY)
            self._dependency_nodes = dict(self._V1_DEPENDENCIES)
            self._input_nodes = dict(self._V1_INPUTS)
            self.logical_stages = tuple(self._V1_LOGICAL_STAGES)
            self.conditional_stages = ()
        else:
            self.NODE_ORDER = tuple(self._V2_NODE_ORDER)
            self.REQUIRED_CAPABILITIES = dict(self._V2_REQUIRED_CAPABILITIES)
            self.OUTPUT_TYPES = dict(self._V2_OUTPUT_TYPES)
            self.PRIORITY = dict(self._V2_PRIORITY)
            self._dependency_nodes = dict(self._V2_DEPENDENCIES)
            self._input_nodes = dict(self._V2_INPUTS)
            self.logical_stages = tuple(self._V2_LOGICAL_STAGES)
            self.conditional_stages = tuple(self._V2_CONDITIONAL_STAGES)

    def contract(self) -> Dict[str, Any]:
        payload = {
            "graph_version": self.graph_version,
            "task_nodes": list(self.NODE_ORDER),
            "logical_stages": list(self.logical_stages),
            "conditional_stages": list(self.conditional_stages),
            "dependencies": {key: list(value) for key, value in self._dependency_nodes.items()},
            "output_types": dict(self.OUTPUT_TYPES),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["contract_sha256"] = hashlib.sha256(encoded).hexdigest()
        return payload

    def compile(
        self,
        mission_id: str,
        *,
        external_inputs: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> MissionTaskGraph:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("MISSION_ID_REQUIRED")
        mission_id = mission_id.strip()
        external_inputs = dict(external_inputs or {})
        unknown_nodes = sorted(set(external_inputs).difference(self.NODE_ORDER))
        if unknown_nodes:
            raise ValueError("MISSION_GRAPH_EXTERNAL_INPUT_NODE_UNKNOWN:%s" % ",".join(unknown_nodes))
        normalized_external: Dict[str, Tuple[str, ...]] = {}
        for node, refs in external_inputs.items():
            if isinstance(refs, (str, bytes)):
                raise ValueError("MISSION_GRAPH_EXTERNAL_INPUTS_MUST_BE_SEQUENCE:%s" % node)
            refs_tuple = tuple(refs)
            values = tuple(ref.strip() for ref in refs_tuple if isinstance(ref, str) and ref.strip())
            if len(values) != len(refs_tuple):
                raise ValueError("MISSION_GRAPH_EXTERNAL_INPUT_REF_INVALID:%s" % node)
            normalized_external[node] = tuple(dict.fromkeys(values))

        task_ids: Dict[str, str] = {
            node: _stable_id("TASK", mission_id, node) for node in self.NODE_ORDER
        }
        artifact_ids: Dict[str, str] = {
            node: _stable_id("ART", mission_id, self.OUTPUT_TYPES[node])
            for node in self.NODE_ORDER
        }

        tasks = []
        for node in self.NODE_ORDER:
            inherited_inputs = [artifact_ids[name] for name in self._input_nodes[node]]
            node_inputs = list(normalized_external.get(node, ()))
            criteria = [
                "independent evaluator accepts %s output" % node,
                "output and acceptance evidence are durable in R1",
            ]
            if node in {"REQUIREMENT_ANALYSIS", "CODE_ANALYSIS", "TEST_DESIGN"}:
                criteria.append("independent sufficiency gate passes; producer self-acceptance is forbidden")
            if node == "PRECONDITION_DATA":
                criteria.append("preconditions and test data are verified before execution; writes require governed authorization")
            if node == "REPORT":
                criteria.append("report is derived from durable Mission evidence and cannot declare TEST_SUFFICIENT")
            tasks.append(
                Task(
                    task_id=task_ids[node],
                    mission_id=mission_id,
                    node=node,
                    task_type="PRODUCE",
                    objective="Produce evaluator-ready %s output" % self.OUTPUT_TYPES[node],
                    required_capabilities=list(self.REQUIRED_CAPABILITIES[node]),
                    dependency_task_ids=[task_ids[name] for name in self._dependency_nodes[node]],
                    input_artifact_refs=list(dict.fromkeys(inherited_inputs + node_inputs)),
                    acceptance_criteria=criteria,
                    priority=self.PRIORITY[node],
                )
            )

        return MissionTaskGraph(
            mission_id=mission_id,
            graph_version=self.graph_version,
            tasks=tuple(tasks),
            artifact_ids=dict(artifact_ids),
            logical_stages=tuple(self.logical_stages),
            conditional_stages=tuple(self.conditional_stages),
        )

    def install(
        self,
        control_plane: Any,
        mission_id: str,
        *,
        external_inputs: Optional[Mapping[str, Sequence[str]]] = None,
    ) -> MissionTaskGraph:
        """Persist the compiled Task graph through the canonical control plane."""
        graph = self.compile(mission_id, external_inputs=external_inputs)
        for task in graph.tasks:
            control_plane.register_task(task)
        return graph
