"""Versioned deterministic RC7 Mission graph compiler.

The generic compiler preserves the original v1 default for source/API
compatibility. Bank Mission bootstrap explicitly opts new Missions into v2.
Persisted graph identity prevents an existing Mission from silently changing
shape after a runtime upgrade.

Mission Graph v2 is a responsibility graph, not a flat list of AI workers.
Top-level durable Tasks represent Mission work that must be sequenced in R1.
Runtime-owned per-case/per-attempt execution preparation remains inside the
Execution contract, independent sufficiency authorities are logical gates, and
Final Report is post-convergence only.
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
    stage_ownership: Mapping[str, str]
    runtime_substages: Tuple[str, ...]
    post_convergence_stages: Tuple[str, ...]

    def task(self, node: str) -> Task:
        rows = [task for task in self.tasks if task.node == node]
        if len(rows) != 1:
            raise KeyError("MISSION_GRAPH_NODE_NOT_UNIQUE:%s" % node)
        return rows[0]


class MissionTaskGraphCompiler:
    GRAPH_V1 = "v1"
    GRAPH_V2 = "v2"
    SUPPORTED_GRAPH_VERSIONS = (GRAPH_V1, GRAPH_V2)

    OWNER_PRODUCER = "PRODUCER_WORKER"
    OWNER_RUNTIME = "RUNTIME"
    OWNER_AUTHORITY = "INDEPENDENT_AUTHORITY"
    OWNER_CONDITIONAL_RUNTIME = "CONDITIONAL_RUNTIME"
    OWNER_POST_CONVERGENCE = "POST_CONVERGENCE"

    # Generic/internal callers keep the field-baseline v1 semantics. The Bank
    # Mission entrypoint explicitly selects v2 for new Missions.
    DEFAULT_GRAPH_VERSION = GRAPH_V1
    BANK_DEFAULT_GRAPH_VERSION = GRAPH_V2

    # Frozen legacy v1 task inventory.
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
    _V1_STAGE_OWNERS = {
        "REQUIREMENT_ANALYSIS": OWNER_PRODUCER,
        "REQUIREMENT_SUFFICIENCY": OWNER_AUTHORITY,
        "CODE_ANALYSIS": OWNER_PRODUCER,
        "CODE_SUFFICIENCY": OWNER_AUTHORITY,
        "TEST_DESIGN": OWNER_PRODUCER,
        "TEST_DESIGN_SUFFICIENCY": OWNER_AUTHORITY,
        "SCRIPT_READINESS": OWNER_PRODUCER,
        "EXECUTION": OWNER_PRODUCER,
        "MISSION_CONVERGENCE": OWNER_AUTHORITY,
    }

    # v2 top-level durable Task inventory. Runtime preparation and report are
    # deliberately not flattened into free AI-worker Tasks.
    _V2_NODES = (
        "REALITY_RECON", "REQUIREMENT_ANALYSIS", "CODE_ANALYSIS",
        "TEST_DESIGN", "SCRIPT_READINESS", "EXECUTION",
    )
    _V2_CAPS = {
        "REALITY_RECON": ("bank_reality", "code_reality"),
        "REQUIREMENT_ANALYSIS": ("requirement_reasoning",),
        "CODE_ANALYSIS": ("code_reasoning", "code_reality"),
        "TEST_DESIGN": ("test_design",),
        "SCRIPT_READINESS": ("test_automation",),
        "EXECUTION": ("test_execution",),
    }
    _V2_OUTPUTS = {
        "REALITY_RECON": "BANK_REALITY_SNAPSHOT",
        "REQUIREMENT_ANALYSIS": "REQUIREMENT_MODEL",
        "CODE_ANALYSIS": "CODE_IMPACT_MODEL",
        "TEST_DESIGN": "TEST_DESIGN_MODEL",
        "SCRIPT_READINESS": "EXECUTABLE_SCRIPT",
        "EXECUTION": "EXECUTION_CONCLUSION",
    }
    _V2_PRIORITY = {
        "REALITY_RECON": 5,
        "REQUIREMENT_ANALYSIS": 10,
        "CODE_ANALYSIS": 20,
        "TEST_DESIGN": 30,
        "SCRIPT_READINESS": 40,
        "EXECUTION": 50,
    }
    _V2_DEPS = {
        "REALITY_RECON": (),
        "REQUIREMENT_ANALYSIS": ("REALITY_RECON",),
        "CODE_ANALYSIS": ("REALITY_RECON", "REQUIREMENT_ANALYSIS"),
        "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
        "SCRIPT_READINESS": ("TEST_DESIGN",),
        "EXECUTION": ("SCRIPT_READINESS",),
    }
    _V2_INPUTS = {
        "REALITY_RECON": (),
        "REQUIREMENT_ANALYSIS": ("REALITY_RECON",),
        "CODE_ANALYSIS": ("REALITY_RECON", "REQUIREMENT_ANALYSIS"),
        "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
        "SCRIPT_READINESS": ("TEST_DESIGN",),
        "EXECUTION": ("SCRIPT_READINESS",),
    }
    _V2_LOGICAL = (
        "REALITY_RECON",
        "REQUIREMENT_ANALYSIS", "REQUIREMENT_SUFFICIENCY",
        "CODE_ANALYSIS", "CODE_SUFFICIENCY",
        "TEST_DESIGN", "TEST_DESIGN_SUFFICIENCY",
        "SCRIPT_BUILD",
        "PRECONDITIONS", "TEST_DATA_PREPARATION",
        "EXECUTION", "ACTUAL_RESULT", "ORACLE",
        "FAILURE_DIAGNOSIS", "RECOVERY_RETRY", "DEFECT_REVIEW",
        "MISSION_CONVERGENCE",
        "FINAL_REPORT",
    )
    _V2_STAGE_OWNERS = {
        "REALITY_RECON": OWNER_RUNTIME,
        "REQUIREMENT_ANALYSIS": OWNER_PRODUCER,
        "REQUIREMENT_SUFFICIENCY": OWNER_AUTHORITY,
        "CODE_ANALYSIS": OWNER_PRODUCER,
        "CODE_SUFFICIENCY": OWNER_AUTHORITY,
        "TEST_DESIGN": OWNER_PRODUCER,
        "TEST_DESIGN_SUFFICIENCY": OWNER_AUTHORITY,
        "SCRIPT_BUILD": OWNER_PRODUCER,
        "PRECONDITIONS": OWNER_RUNTIME,
        "TEST_DATA_PREPARATION": OWNER_RUNTIME,
        "EXECUTION": OWNER_PRODUCER,
        "ACTUAL_RESULT": OWNER_RUNTIME,
        "ORACLE": OWNER_RUNTIME,
        "FAILURE_DIAGNOSIS": OWNER_CONDITIONAL_RUNTIME,
        "RECOVERY_RETRY": OWNER_CONDITIONAL_RUNTIME,
        "DEFECT_REVIEW": OWNER_CONDITIONAL_RUNTIME,
        "MISSION_CONVERGENCE": OWNER_AUTHORITY,
        "FINAL_REPORT": OWNER_POST_CONVERGENCE,
    }
    _V2_TASK_OWNERS = {
        "REALITY_RECON": OWNER_RUNTIME,
        "REQUIREMENT_ANALYSIS": OWNER_PRODUCER,
        "CODE_ANALYSIS": OWNER_PRODUCER,
        "TEST_DESIGN": OWNER_PRODUCER,
        "SCRIPT_READINESS": OWNER_PRODUCER,
        "EXECUTION": OWNER_PRODUCER,
    }
    _V2_RUNTIME_SUBSTAGES = (
        "PRECONDITIONS", "TEST_DATA_PREPARATION", "ACTUAL_RESULT", "ORACLE",
    )
    _V2_CONDITIONAL = ("FAILURE_DIAGNOSIS", "RECOVERY_RETRY", "DEFECT_REVIEW")
    _V2_POST_CONVERGENCE = ("FINAL_REPORT",)

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
            self.stage_ownership = dict(self._V1_STAGE_OWNERS)
            self.task_ownership = {node: self.OWNER_PRODUCER for node in self.NODE_ORDER}
            self.runtime_substages = ()
            self.post_convergence_stages = ()
        else:
            self.NODE_ORDER = tuple(self._V2_NODES)
            self.REQUIRED_CAPABILITIES = dict(self._V2_CAPS)
            self.OUTPUT_TYPES = dict(self._V2_OUTPUTS)
            self.PRIORITY = dict(self._V2_PRIORITY)
            self._deps = dict(self._V2_DEPS)
            self._inputs = dict(self._V2_INPUTS)
            self.logical_stages = tuple(self._V2_LOGICAL)
            self.conditional_stages = tuple(self._V2_CONDITIONAL)
            self.stage_ownership = dict(self._V2_STAGE_OWNERS)
            self.task_ownership = dict(self._V2_TASK_OWNERS)
            self.runtime_substages = tuple(self._V2_RUNTIME_SUBSTAGES)
            self.post_convergence_stages = tuple(self._V2_POST_CONVERGENCE)

    def task_owner(self, node: str) -> str:
        try:
            return self.task_ownership[node]
        except KeyError as exc:
            raise KeyError("MISSION_GRAPH_TASK_OWNER_UNKNOWN:%s" % node) from exc

    def contract(self) -> Dict[str, Any]:
        payload = {
            "graph_version": self.graph_version,
            "task_nodes": list(self.NODE_ORDER),
            "task_ownership": dict(self.task_ownership),
            "logical_stages": list(self.logical_stages),
            "stage_ownership": dict(self.stage_ownership),
            "runtime_substages": list(self.runtime_substages),
            "conditional_stages": list(self.conditional_stages),
            "post_convergence_stages": list(self.post_convergence_stages),
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
            criteria = ["output and acceptance evidence are durable in R1"]
            if self.task_owner(node) == self.OWNER_PRODUCER:
                criteria.insert(0, "independent evaluator accepts %s output" % node)
            if node in {"REQUIREMENT_ANALYSIS", "CODE_ANALYSIS", "TEST_DESIGN"}:
                criteria.append("independent sufficiency gate passes; producer self-acceptance is forbidden")
            if self.graph_version == self.GRAPH_V2 and node == "REALITY_RECON":
                criteria.extend((
                    "runtime owns source/release/environment reality acquisition",
                    "reality snapshot is evidence-backed and durable before AI analysis starts",
                ))
            if self.graph_version == self.GRAPH_V2 and node == "EXECUTION":
                criteria.extend((
                    "per-case/per-attempt preconditions and test data are prepared by Runtime",
                    "database writes require Human Gate authorization",
                    "actual result capture and deterministic oracle are Runtime-owned",
                ))
            tasks.append(Task(
                task_id=task_ids[node], mission_id=mission_id, node=node,
                task_type="RUNTIME" if self.task_owner(node) == self.OWNER_RUNTIME else "PRODUCE",
                objective="Produce evaluator-ready %s output" % self.OUTPUT_TYPES[node],
                required_capabilities=list(self.REQUIRED_CAPABILITIES[node]),
                dependency_task_ids=[task_ids[name] for name in self._deps[node]],
                input_artifact_refs=list(dict.fromkeys(inherited + list(normalized.get(node, ())))),
                acceptance_criteria=criteria, priority=self.PRIORITY[node],
            ))
        return MissionTaskGraph(
            mission_id=mission_id,
            graph_version=self.graph_version,
            tasks=tuple(tasks), artifact_ids=dict(artifact_ids),
            logical_stages=tuple(self.logical_stages),
            conditional_stages=tuple(self.conditional_stages),
            stage_ownership=dict(self.stage_ownership),
            runtime_substages=tuple(self.runtime_substages),
            post_convergence_stages=tuple(self.post_convergence_stages),
        )

    def install(self, control_plane: Any, mission_id: str, *, external_inputs: Optional[Mapping[str, Sequence[str]]] = None) -> MissionTaskGraph:
        graph = self.compile(mission_id, external_inputs=external_inputs)
        for task in graph.tasks:
            control_plane.register_task(task)
        return graph
