from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, RuntimeError
from aitest_runtime.work_graph import EXTENSION_ID, WorkGraphState

from .contracts import (
    BuildExecutionContextRequest,
    ContextTarget,
    ContextTargetType,
    ExecutionContext,
    ExecutionContextItem,
    ExecutionContextSection,
    OmissionSummary,
    canonical_bytes,
    canonical_sha256,
    thaw_json,
)
from .policy import ExecutionContextPolicy, SECTION_ORDER


OMISSION_REASONS = (
    "ITEM_BYTES_EXCEEDED",
    "SECTION_ITEM_LIMIT",
    "SECTION_BYTES_EXCEEDED",
    "TOTAL_ITEM_LIMIT",
    "TOTAL_BYTES_EXCEEDED",
    "KNOWLEDGE_STATUS_INELIGIBLE",
    "KNOWLEDGE_SCOPE_MISMATCH",
)


@dataclass(frozen=True)
class _Candidate:
    order: int
    section: str
    item_type: str
    item_id: str
    required: bool
    value: Any
    size_bytes: int
    pre_omission_reason: str | None = None

    def omission(self, reason: str) -> dict[str, Any]:
        return {
            "section": self.section,
            "item_type": self.item_type,
            "item_id": self.item_id,
            "reason": reason,
        }


def _candidate(
    order: int,
    section: str,
    item_type: str,
    item_id: str,
    required: bool,
    value: Any,
    pre_omission_reason: str | None = None,
) -> _Candidate:
    semantic = {
        "item_type": item_type,
        "item_id": item_id,
        "required": required,
        "value": value,
    }
    return _Candidate(
        order,
        section,
        item_type,
        item_id,
        required,
        value,
        len(canonical_bytes(semantic)),
        pre_omission_reason,
    )


class _ExecutionContextBuilder:
    """Pure deterministic R1.3A materializer."""

    def build(
        self,
        request: BuildExecutionContextRequest,
        replayed: ComposedRuntimeState,
        policy: ExecutionContextPolicy,
    ) -> ExecutionContext:
        if not isinstance(request, BuildExecutionContextRequest):
            raise RuntimeError("EXECUTION_CONTEXT_SCHEMA_INVALID", "request has an invalid type")
        if not isinstance(replayed, ComposedRuntimeState):
            raise RuntimeError("EXECUTION_CONTEXT_STATE_INVALID", "replayed state has an invalid type")
        if not isinstance(policy, ExecutionContextPolicy):
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", "policy has an invalid type")
        if (request.policy_id, request.policy_version) != (policy.policy_id, policy.policy_version):
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_MISMATCH", "request and resolved policy do not match")
        if replayed.mission_id != request.mission_id or replayed.core_state.mission_id != request.mission_id:
            raise RuntimeError("EXECUTION_CONTEXT_MISSION_MISMATCH", "replayed state belongs to another Mission")
        if replayed.seq != request.cursor.seq or replayed.core_state.seq != request.cursor.seq:
            raise RuntimeError(
                "EVENT_CURSOR_MISMATCH",
                "Replayed composed state does not match the requested Event cursor",
                {"requested_seq": request.cursor.seq, "replayed_seq": replayed.seq},
            )
        mission = replayed.core_state.mission
        if mission is None:
            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found at cursor: {request.mission_id}")
        try:
            work_graph = replayed.extension_state(EXTENSION_ID)
        except RuntimeError as exc:
            raise RuntimeError(
                "EXECUTION_CONTEXT_WORK_GRAPH_REQUIRED",
                "R1.3A requires the R1.2 Work Graph extension",
            ) from exc
        if not isinstance(work_graph, WorkGraphState) or work_graph.mission_id != request.mission_id:
            raise RuntimeError("EXECUTION_CONTEXT_STATE_INVALID", "Work Graph state is invalid for the Mission")

        resolved_target = self._resolve_target(request.target, work_graph)
        candidates = self._candidates(request, replayed, work_graph, resolved_target)
        selected, omitted = self._apply_structural_budgets(candidates, policy)
        return self._materialize_with_final_budgets(
            request,
            policy,
            resolved_target,
            selected,
            omitted,
            replayed,
            work_graph,
        )

    def _resolve_target(self, target: ContextTarget, work_graph: WorkGraphState) -> ContextTarget:
        if target.target_type == ContextTargetType.MISSION:
            return target
        if target.target_type == ContextTargetType.PLAN:
            plan = work_graph.plan(target.plan_id or "")
            if plan is None:
                raise RuntimeError("PLAN_NOT_FOUND", f"Plan not found: {target.plan_id}")
            revision_id = target.plan_revision_id or plan.current_revision_id
            if revision_id is None:
                raise RuntimeError(
                    "PLAN_REVISION_NOT_FOUND",
                    f"Plan has no current revision at the requested cursor: {plan.plan_id}",
                )
            revision = work_graph.revision(revision_id)
            if revision is None:
                raise RuntimeError("PLAN_REVISION_NOT_FOUND", f"Plan Revision not found: {revision_id}")
            if revision.plan_id != plan.plan_id:
                raise RuntimeError("CONTEXT_TARGET_MISMATCH", "Plan Revision does not belong to target Plan")
            return ContextTarget(ContextTargetType.PLAN, plan.plan_id, revision.revision_id)

        task = work_graph.task(target.task_id or "")
        if task is None:
            raise RuntimeError("TASK_NOT_FOUND", f"Task not found: {target.task_id}")
        if target.plan_id is not None and target.plan_id != task.plan_id:
            raise RuntimeError("CONTEXT_TARGET_MISMATCH", "Explicit Plan conflicts with the target Task")
        if target.plan_revision_id is not None and target.plan_revision_id != task.plan_revision_id:
            raise RuntimeError("CONTEXT_TARGET_MISMATCH", "Explicit Plan Revision conflicts with the target Task")
        plan = work_graph.plan(task.plan_id)
        revision = work_graph.revision(task.plan_revision_id)
        if plan is None or revision is None or revision.plan_id != task.plan_id:
            raise RuntimeError("EXECUTION_CONTEXT_STATE_INVALID", "Target Task has an unresolved Plan or Revision")
        return ContextTarget(
            ContextTargetType.TASK,
            task.plan_id,
            task.plan_revision_id,
            task.task_id,
        )

    def _candidates(
        self,
        request: BuildExecutionContextRequest,
        replayed: ComposedRuntimeState,
        work_graph: WorkGraphState,
        target: ContextTarget,
    ) -> dict[str, list[_Candidate]]:
        result: dict[str, list[_Candidate]] = {name: [] for name in SECTION_ORDER}
        order = 0

        def add(
            section: str,
            item_type: str,
            item_id: str,
            required: bool,
            value: Any,
            pre_omission_reason: str | None = None,
        ) -> None:
            nonlocal order
            result[section].append(
                _candidate(order, section, item_type, item_id, required, value, pre_omission_reason)
            )
            order += 1

        add(
            "execution",
            "execution_anchor",
            request.execution_attempt_id,
            True,
            {
                "execution_attempt_id": request.execution_attempt_id,
                "mission_id": request.mission_id,
                "cursor": request.cursor.to_dict(),
                "resolved_target": target.to_dict(),
                "policy": {"policy_id": request.policy_id, "policy_version": request.policy_version},
                "knowledge_set_digest": request.knowledge_set.digest,
            },
        )
        mission = replayed.core_state.mission
        assert mission is not None
        add("runtime", "mission", mission.mission_id, True, mission.to_dict())
        if mission.active_goal_id is not None:
            goal = replayed.core_state.goal(mission.active_goal_id)
            if goal is None:
                raise RuntimeError("EXECUTION_CONTEXT_STATE_INVALID", "Mission active Goal is missing")
            add("runtime", "goal", goal.goal_id, True, goal.to_dict())

        plan = work_graph.plan(target.plan_id) if target.plan_id else None
        revision = work_graph.revision(target.plan_revision_id) if target.plan_revision_id else None
        task = work_graph.task(target.task_id) if target.task_id else None
        if plan is not None:
            add("work_graph", "plan", plan.plan_id, True, plan.to_dict())
        if revision is not None:
            add("work_graph", "plan_revision", revision.revision_id, True, revision.to_dict())
        if task is not None:
            add("work_graph", "target_task", task.task_id, True, task.to_dict())

        relevant_tasks: list[Any]
        relevant_dependencies: list[Any]
        predecessor_tasks: list[Any] = []
        if target.target_type == ContextTargetType.MISSION:
            # MISSION scope is deliberately runtime-only.  Plan/Task graph
            # materialization belongs to PLAN or TASK targets.
            relevant_tasks = []
            relevant_dependencies = []
        elif target.target_type == ContextTargetType.PLAN:
            relevant_tasks = [
                item for item in work_graph.tasks if item.plan_revision_id == target.plan_revision_id
            ]
            relevant_dependencies = [
                item for item in work_graph.dependencies if item.revision_id == target.plan_revision_id
            ]
        else:
            relevant_tasks = []
            relevant_dependencies = [
                item
                for item in work_graph.dependencies
                if item.revision_id == target.plan_revision_id and item.successor_task_id == target.task_id
            ]
            predecessor_ids = {item.predecessor_task_id for item in relevant_dependencies}
            predecessor_tasks = [item for item in work_graph.tasks if item.task_id in predecessor_ids]

        for item in sorted(
            relevant_tasks,
            key=lambda value: (value.plan_id, value.plan_revision_id, value.task_id),
        ):
            if task is None or item.task_id != task.task_id:
                add("work_graph", "task", item.task_id, False, item.to_dict())
        for item in sorted(
            relevant_dependencies,
            key=lambda value: (
                value.revision_id,
                value.predecessor_task_id,
                value.successor_task_id,
                value.dependency_kind,
            ),
        ):
            item_id = f"{item.revision_id}:{item.predecessor_task_id}->{item.successor_task_id}"
            add("work_graph", "incoming_dependency", item_id, False, item.to_dict())
        for item in sorted(predecessor_tasks, key=lambda value: value.task_id):
            add("work_graph", "predecessor_task_state", item.task_id, False, item.to_dict())

        effective_scope = {
            "target_type": target.target_type.value,
            "mission_id": request.mission_id,
            "plan_id": target.plan_id,
            "plan_revision_id": target.plan_revision_id,
            "task_id": target.task_id,
        }
        for key, value in request.knowledge_scope.items():
            current = effective_scope.get(key)
            if current is not None and value not in ("*", current):
                raise RuntimeError(
                    "KNOWLEDGE_SCOPE_MISMATCH",
                    f"Knowledge scope cannot override Event-derived {key}",
                    {"key": key, "requested": value, "resolved": current},
                )
            if current is None:
                effective_scope[key] = value
        for item in request.knowledge_set.records:
            identity = f"{item.knowledge_id}@{item.version}"
            if item.status != "VERIFIED":
                add(
                    "knowledge",
                    "knowledge",
                    identity,
                    False,
                    item.to_dict(),
                    "KNOWLEDGE_STATUS_INELIGIBLE",
                )
            elif not self._scope_matches(item.scope, effective_scope):
                add(
                    "knowledge",
                    "knowledge",
                    identity,
                    False,
                    item.to_dict(),
                    "KNOWLEDGE_SCOPE_MISMATCH",
                )
            else:
                add("knowledge", "knowledge", identity, False, item.to_dict())
        return result

    @staticmethod
    def _scope_matches(scope: Mapping[str, Any], effective_scope: Mapping[str, Any]) -> bool:
        return all(
            value == "*" or (key in effective_scope and effective_scope[key] is not None and effective_scope[key] == value)
            for key, value in scope.items()
        )

    def _apply_structural_budgets(
        self,
        candidates: Mapping[str, list[_Candidate]],
        policy: ExecutionContextPolicy,
    ) -> tuple[dict[str, list[_Candidate]], list[tuple[int, dict[str, Any]]]]:
        selected: dict[str, list[_Candidate]] = {name: [] for name in SECTION_ORDER}
        omitted: list[tuple[int, dict[str, Any]]] = []
        section_bytes = {name: 0 for name in SECTION_ORDER}
        total_items = 0
        selected_bytes = 0
        for section in SECTION_ORDER:
            section_policy = policy.section(section)
            for item in candidates[section]:
                if item.pre_omission_reason is not None:
                    omitted.append((item.order, item.omission(item.pre_omission_reason)))
                    continue
                reason = None
                if item.size_bytes > policy.max_item_bytes:
                    reason = "ITEM_BYTES_EXCEEDED"
                elif len(selected[section]) >= section_policy.max_items:
                    reason = "SECTION_ITEM_LIMIT"
                elif section_bytes[section] + item.size_bytes > section_policy.max_bytes:
                    reason = "SECTION_BYTES_EXCEEDED"
                elif total_items >= policy.max_items_total:
                    reason = "TOTAL_ITEM_LIMIT"
                elif selected_bytes + item.size_bytes > policy.max_total_bytes:
                    reason = "TOTAL_BYTES_EXCEEDED"
                if reason is not None:
                    if item.required:
                        self._required_budget_failure(item, reason, policy)
                    omitted.append((item.order, item.omission(reason)))
                    continue
                selected[section].append(item)
                section_bytes[section] += item.size_bytes
                selected_bytes += item.size_bytes
                total_items += 1
        return selected, omitted

    def _materialize_with_final_budgets(
        self,
        request: BuildExecutionContextRequest,
        policy: ExecutionContextPolicy,
        target: ContextTarget,
        selected: dict[str, list[_Candidate]],
        omitted: list[tuple[int, dict[str, Any]]],
        replayed: ComposedRuntimeState,
        work_graph: WorkGraphState,
    ) -> ExecutionContext:
        while True:
            context = self._materialize(
                request,
                target,
                selected,
                omitted,
                policy.max_omission_samples,
                replayed,
                work_graph,
            )
            if context.metadata_bytes > policy.max_metadata_bytes:
                reduced = None
                for sample_limit in range(policy.max_omission_samples - 1, -1, -1):
                    candidate_context = self._materialize(
                        request,
                        target,
                        selected,
                        omitted,
                        sample_limit,
                        replayed,
                        work_graph,
                    )
                    if candidate_context.metadata_bytes <= policy.max_metadata_bytes:
                        reduced = candidate_context
                        break
                if reduced is None:
                    raise RuntimeError(
                        "CONTEXT_BUDGET_TOO_SMALL",
                        "Required Execution Context metadata exceeds the policy budget",
                        {"reason": "METADATA_BYTES_EXCEEDED"},
                    )
                context = reduced
            if context.total_bytes <= policy.max_total_bytes:
                return context
            removable = self._last_optional(selected)
            if removable is None:
                raise RuntimeError(
                    "CONTEXT_BUDGET_TOO_SMALL",
                    "Required Execution Context exceeds the total byte budget",
                    {"reason": "TOTAL_BYTES_EXCEEDED"},
                )
            selected[removable.section].remove(removable)
            omitted.append((removable.order, removable.omission("TOTAL_BYTES_EXCEEDED")))

    @staticmethod
    def _last_optional(selected: Mapping[str, list[_Candidate]]) -> _Candidate | None:
        values = [item for section in SECTION_ORDER for item in selected[section] if not item.required]
        return max(values, key=lambda item: item.order) if values else None

    @staticmethod
    def _required_budget_failure(
        item: _Candidate,
        reason: str,
        policy: ExecutionContextPolicy,
    ) -> None:
        raise RuntimeError(
            "CONTEXT_BUDGET_TOO_SMALL",
            "A required Execution Context item does not fit the frozen policy",
            {
                "reason": reason,
                "section": item.section,
                "item_type": item.item_type,
                "item_id": item.item_id,
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
            },
        )

    def _materialize(
        self,
        request: BuildExecutionContextRequest,
        target: ContextTarget,
        selected: Mapping[str, list[_Candidate]],
        omitted: list[tuple[int, dict[str, Any]]],
        sample_limit: int,
        replayed: ComposedRuntimeState,
        work_graph: WorkGraphState,
    ) -> ExecutionContext:
        ordered_omissions = [item for _, item in sorted(omitted, key=lambda pair: pair[0])]
        counts = {
            reason: sum(1 for item in ordered_omissions if item["reason"] == reason)
            for reason in OMISSION_REASONS
            if any(item["reason"] == reason for item in ordered_omissions)
        }
        counts_by_section = {
            section: sum(1 for item in ordered_omissions if item["section"] == section)
            for section in SECTION_ORDER
            if any(item["section"] == section for item in ordered_omissions)
        }
        omissions = OmissionSummary(
            total_count=len(ordered_omissions),
            counts_by_reason=counts,
            samples=tuple(ordered_omissions[:sample_limit]),
            digest=canonical_sha256(ordered_omissions),
            counts_by_section=counts_by_section,
        )
        sections = tuple(
            ExecutionContextSection(
                name=name,
                items=tuple(
                    ExecutionContextItem(
                        item_type=item.item_type,
                        item_id=item.item_id,
                        required=item.required,
                        value=item.value,
                        size_bytes=item.size_bytes,
                    )
                    for item in selected[name]
                ),
                size_bytes=sum(item.size_bytes for item in selected[name]),
            )
            for name in SECTION_ORDER
        )
        core_state_digest = canonical_sha256(replayed.core_state.to_dict())
        work_graph_semantic_state = work_graph.to_dict()
        # Snapshot indexes are derived acceleration artifacts, not Runtime
        # Truth, so they must not participate in semantic provenance.
        work_graph_semantic_state.pop("snapshots", None)
        work_graph_state_digest = canonical_sha256(work_graph_semantic_state)
        semantic_provenance = (
            {
                "source": "BUILD_REQUEST",
                "execution_attempt_id": request.execution_attempt_id,
                "policy_id": request.policy_id,
                "policy_version": request.policy_version,
            },
            {
                "source": "MISSION_EVENT_STREAM",
                "mission_id": request.mission_id,
                "through_seq": request.cursor.seq,
                "stream_schema_version": request.cursor.stream_schema_version,
                "core_state_digest": core_state_digest,
                "work_graph_state_digest": work_graph_state_digest,
            },
            {
                "source": "FROZEN_KNOWLEDGE_SET",
                "knowledge_set_digest": request.knowledge_set.digest,
            },
        )
        semantic = {
            "execution_context_schema_version": 1,
            "builder_version": 1,
            "canonicalization_version": 1,
            "execution_attempt_id": request.execution_attempt_id,
            "mission_id": request.mission_id,
            "cursor": request.cursor.to_dict(),
            "resolved_target": target.to_dict(),
            "policy": {"policy_id": request.policy_id, "policy_version": request.policy_version},
            "knowledge_set_digest": request.knowledge_set.digest,
            "knowledge_scope": thaw_json(request.knowledge_scope),
            "sections": [section.semantic_dict() for section in sections],
            "semantic_provenance": list(semantic_provenance),
            "omissions": omissions.to_dict(),
        }
        digest = canonical_sha256(semantic)
        materialization = {"source": "EVENT_REPLAY", "through_seq": request.cursor.seq}
        metadata = dict(semantic)
        metadata.pop("sections")
        metadata["materialization_provenance"] = materialization
        metadata["semantic_digest"] = digest
        metadata_bytes = len(canonical_bytes(metadata))
        total_bytes = metadata_bytes + sum(section.size_bytes for section in sections)
        return ExecutionContext(
            execution_attempt_id=request.execution_attempt_id,
            mission_id=request.mission_id,
            cursor=request.cursor,
            resolved_target=target,
            policy_id=request.policy_id,
            policy_version=request.policy_version,
            knowledge_set_digest=request.knowledge_set.digest,
            sections=sections,
            omissions=omissions,
            semantic_provenance=semantic_provenance,
            materialization_provenance=materialization,
            semantic_digest=digest,
            metadata_bytes=metadata_bytes,
            total_bytes=total_bytes,
            knowledge_scope=request.knowledge_scope,
        )
