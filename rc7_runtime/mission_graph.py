"""Canonical RC7 mission task graph compiler.

The runtime, not the chat coordinator, owns the initial dependency graph. The
compiler emits stable Task ids and stable expected Artifact ids for the core
happy-path nodes. Defect work remains event-driven and is created only after a
trusted PRODUCT_DEFECT Gap; it is deliberately absent from the initial graph.

External source/runtime inputs are explicit durable references bound into Task
contracts at graph construction time. They are never smuggled through chat
history or coordinator context.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

from .models import Task


def _stable_id(prefix: str, mission_id: str, semantic_name: str) -> str:
    raw = (mission_id + "\x1f" + semantic_name).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class MissionTaskGraph:
    mission_id: str
    tasks: Tuple[Task, ...]
    artifact_ids: Mapping[str, str]

    def task(self, node: str) -> Task:
        matches = [task for task in self.tasks if task.node == node]
        if len(matches) != 1:
            raise KeyError("MISSION_GRAPH_NODE_NOT_UNIQUE:%s" % node)
        return matches[0]


class MissionTaskGraphCompiler:
    """Compile and install the deterministic core Mission DAG.

    Requirement -> Code -> Test Design -> Script Readiness -> Execution.
    Test Design keeps an explicit Requirement dependency as well as Code so a
    future graph change cannot accidentally lose requirement traceability.
    Mission sufficiency is an evaluator-owned final gate, not ordinary worker
    work, and Defect tasks are spawned only from trusted runtime evidence.
    """

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

    def compile(
        self,
        mission_id: str,
        *,
        external_inputs: Mapping[str, Sequence[str]] | None = None,
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
            values = tuple(ref.strip() for ref in refs if isinstance(ref, str) and ref.strip())
            if len(values) != len(tuple(refs)):
                raise ValueError("MISSION_GRAPH_EXTERNAL_INPUT_REF_INVALID:%s" % node)
            normalized_external[node] = tuple(dict.fromkeys(values))

        task_ids: Dict[str, str] = {
            node: _stable_id("TASK", mission_id, node) for node in self.NODE_ORDER
        }
        artifact_ids: Dict[str, str] = {
            node: _stable_id("ART", mission_id, self.OUTPUT_TYPES[node])
            for node in self.NODE_ORDER
        }

        dependency_nodes = {
            "REQUIREMENT_ANALYSIS": (),
            "CODE_ANALYSIS": ("REQUIREMENT_ANALYSIS",),
            "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
            "SCRIPT_READINESS": ("TEST_DESIGN",),
            "EXECUTION": ("SCRIPT_READINESS",),
        }
        input_nodes = {
            "REQUIREMENT_ANALYSIS": (),
            "CODE_ANALYSIS": ("REQUIREMENT_ANALYSIS",),
            "TEST_DESIGN": ("REQUIREMENT_ANALYSIS", "CODE_ANALYSIS"),
            "SCRIPT_READINESS": ("TEST_DESIGN",),
            "EXECUTION": ("SCRIPT_READINESS",),
        }

        tasks = []
        for node in self.NODE_ORDER:
            inherited_inputs = [artifact_ids[name] for name in input_nodes[node]]
            node_inputs = list(normalized_external.get(node, ()))
            tasks.append(
                Task(
                    task_id=task_ids[node],
                    mission_id=mission_id,
                    node=node,
                    task_type="PRODUCE",
                    objective="Produce evaluator-ready %s output" % self.OUTPUT_TYPES[node],
                    required_capabilities=list(self.REQUIRED_CAPABILITIES[node]),
                    dependency_task_ids=[task_ids[name] for name in dependency_nodes[node]],
                    input_artifact_refs=list(dict.fromkeys(inherited_inputs + node_inputs)),
                    acceptance_criteria=[
                        "independent evaluator accepts %s output" % node,
                        "output and acceptance evidence are durable in R1",
                    ],
                    priority=self.PRIORITY[node],
                )
            )

        return MissionTaskGraph(
            mission_id=mission_id,
            tasks=tuple(tasks),
            artifact_ids=dict(artifact_ids),
        )

    def install(
        self,
        control_plane: Any,
        mission_id: str,
        *,
        external_inputs: Mapping[str, Sequence[str]] | None = None,
    ) -> MissionTaskGraph:
        """Persist the compiled graph through the canonical control-plane API.

        The duck-typed boundary deliberately avoids a reverse import from this
        pure graph compiler into the control-plane module. Registration order is
        topological, so dependency contracts are checked by TaskScheduler.
        """
        graph = self.compile(mission_id, external_inputs=external_inputs)
        for task in graph.tasks:
            control_plane.register_task(task)
        return graph
