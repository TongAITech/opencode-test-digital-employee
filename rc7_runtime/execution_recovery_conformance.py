"""Fail-closed execution/recovery contract for new RC7 Bank graph-v2 Missions.

The contract is additive and independently versioned so existing graph-v2
Missions carrying the earlier node/tool contract can resume without hash drift.
For an EXECUTION task to PASS, durable R1 truth must prove the real attempt path:
prepared attempt -> runner result -> diagnosis/decision/recovery when needed ->
execution convergence. Agent prose or a forged pass_observed flag is never
sufficient.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .attempt_cat import ATTEMPT_CAT_QUERY_KIND
from .case_runtime import PREPARED_ATTEMPT_KIND
from .execution_chain_evidence import observed_chain_tools
from .models import Evidence, Task
from .node_tool_conformance import NODE_TOOL_CALL_KIND
from .truth_overlay import append_entity


CONTRACT_KIND = "EXECUTION_RECOVERY_CONTRACT"
CONTRACT_VERSION = "v1"
CONTRACT_SOURCE_REF = "runtime://execution-recovery-contract/%s" % CONTRACT_VERSION
PASS_READY_TERMINAL_STATUSES = {"PASS", "PRODUCT_DEFECT_CONFIRMED"}


class ExecutionRecoveryConformanceError(RuntimeError):
    pass


def _contract_payload() -> Dict[str, object]:
    # Keep this frozen. Runtime hardening may add stronger validation of these
    # truth categories, but changing this payload would hash-drift persisted v1
    # contracts and break durable Mission resume.
    return {
        "schema_version": "pfc.aitest.rc7.execution-recovery-contract.v1",
        "contract_version": CONTRACT_VERSION,
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "execution_node": "EXECUTION",
        "required_truth": [
            PREPARED_ATTEMPT_KIND,
            "execution_attempt",
            "failure_diagnosis_if_fail",
            "recovery_decision_if_fail",
            "recovery_action_if_nonterminal",
            "execution_convergence",
            NODE_TOOL_CALL_KIND,
        ],
        "pass_ready_terminal_statuses": sorted(PASS_READY_TERMINAL_STATUSES),
    }


def contract_sha256() -> str:
    body = json.dumps(_contract_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _contract_evidence_id(mission_id: str) -> str:
    raw = (mission_id + "\x1f" + CONTRACT_VERSION + "\x1f" + contract_sha256()).encode("utf-8")
    return "EVD-EXEC-RECOVERY-" + hashlib.sha256(raw).hexdigest()[:20]


def persist_contract(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    execution_task_id: str,
) -> Evidence:
    existing = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == CONTRACT_KIND
    ]
    if existing:
        if len(existing) != 1:
            raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_NOT_UNIQUE")
        if str(existing[0].get("source_ref") or "") != CONTRACT_SOURCE_REF:
            raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_VERSION_MISMATCH")
        if str(existing[0].get("content_hash") or "") != contract_sha256():
            raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_HASH_MISMATCH")
        if execution_task_id not in list(existing[0].get("subject_refs") or []):
            raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_TASK_MISMATCH")
        row = existing[0]
        return Evidence(
            evidence_id=str(row["evidence_id"]),
            mission_id=mission_id,
            kind=CONTRACT_KIND,
            source_ref=str(row["source_ref"]),
            content_ref=str(row["content_ref"]),
            subject_refs=list(row.get("subject_refs") or []),
            content_hash=str(row.get("content_hash") or ""),
            created_at=int(row.get("created_at", 0)),
        )
    evidence = Evidence(
        evidence_id=_contract_evidence_id(mission_id),
        mission_id=mission_id,
        kind=CONTRACT_KIND,
        source_ref=CONTRACT_SOURCE_REF,
        content_ref="execution-recovery-contract://%s/%s" % (CONTRACT_VERSION, contract_sha256()),
        subject_refs=[execution_task_id],
        content_hash=contract_sha256(),
    )
    append_entity(truth, evidence, release_id=release_id, artifact_version=1)
    return evidence


def contract_row(truth: TruthRuntime, mission_id: str) -> Optional[Mapping[str, object]]:
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == CONTRACT_KIND
    ]
    if not rows:
        return None
    if len(rows) != 1:
        raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_NOT_UNIQUE")
    row = rows[0]
    if str(row.get("source_ref") or "") != CONTRACT_SOURCE_REF:
        raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_VERSION_MISMATCH")
    if str(row.get("content_hash") or "") != contract_sha256():
        raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_HASH_MISMATCH")
    return row


def contract_enabled(truth: TruthRuntime, mission_id: str) -> bool:
    return contract_row(truth, mission_id) is not None


def _node_tool_names(truth: TruthRuntime, mission_id: str, task_id: str) -> Tuple[str, ...]:
    names = []
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != NODE_TOOL_CALL_KIND or task_id not in list(row.get("subject_refs") or []):
            continue
        source = str(row.get("source_ref") or "")
        if source.startswith("mcp://pfc-aitest-rc7/"):
            name = source.rsplit("/", 1)[-1]
            if name:
                names.append(name)
    return tuple(sorted(set(names)))


def _prepared_attempt_ids(truth: TruthRuntime, mission_id: str, task_id: str) -> Tuple[str, ...]:
    attempt_ids: List[str] = []
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != PREPARED_ATTEMPT_KIND or task_id not in list(row.get("subject_refs") or []):
            continue
        refs = [str(x) for x in list(row.get("subject_refs") or [])]
        candidates = [ref for ref in refs if ref != task_id and ref.startswith("ATTEMPT-")]
        if not candidates:
            # Field attempt IDs are not required to use a fixed prefix. The
            # prepared evidence layout is [task, worker, attempt, tc, target].
            if len(refs) >= 3:
                candidates = [refs[2]]
        attempt_ids.extend(candidates[:1])
    return tuple(sorted(set(x for x in attempt_ids if x)))


def _exact_one(rows: Sequence[Mapping[str, object]], code: str, violations: List[str]) -> Optional[Mapping[str, object]]:
    if len(rows) != 1:
        violations.append("%s:%d" % (code, len(rows)))
        return None
    return rows[0]


def _check_cat_truth(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    attempt_id: str,
    diagnosis: Mapping[str, object],
    violations: List[str],
) -> None:
    if "cat_required" not in diagnosis or "cat_queried" not in diagnosis:
        violations.append("FAILURE_DIAGNOSIS_CAT_POLICY_NOT_RECORDED:%s" % attempt_id)
        return
    required = bool(diagnosis.get("cat_required"))
    queried = bool(diagnosis.get("cat_queried"))
    evidence_id = str(diagnosis.get("cat_query_evidence_id") or "").strip()
    if not required:
        if queried or evidence_id:
            violations.append("CAT_QUERY_RECORDED_WHEN_NOT_REQUIRED:%s" % attempt_id)
        return
    if not queried or not evidence_id:
        violations.append("CAT_REQUIRED_BUT_NOT_QUERIED:%s" % attempt_id)
        return
    rows = truth.query("rc7_evidence", evidence_id=evidence_id)
    if len(rows) != 1:
        violations.append("ATTEMPT_CAT_QUERY_EVIDENCE_NOT_UNIQUE:%s" % attempt_id)
        return
    row = rows[0]
    refs = list(row.get("subject_refs") or [])
    if row.get("kind") != ATTEMPT_CAT_QUERY_KIND or task_id not in refs or attempt_id not in refs:
        violations.append("ATTEMPT_CAT_QUERY_EVIDENCE_IDENTITY_MISMATCH:%s" % attempt_id)


@dataclass(frozen=True)
class ExecutionRecoveryConformanceResult:
    mission_id: str
    task_id: str
    status: str
    violations: Tuple[str, ...]
    attempt_ids: Tuple[str, ...]
    observed_tools: Tuple[str, ...]
    terminal_statuses: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        return {
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "status": self.status,
            "violations": list(self.violations),
            "attempt_ids": list(self.attempt_ids),
            "observed_tools": list(self.observed_tools),
            "terminal_statuses": list(self.terminal_statuses),
        }


class ExecutionRecoveryConformanceChecker:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check_task(self, mission_id: str, task_id: str) -> ExecutionRecoveryConformanceResult:
        contract = contract_row(self.truth, mission_id)
        if contract is None:
            return ExecutionRecoveryConformanceResult(
                mission_id=mission_id,
                task_id=task_id,
                status="NOT_ENFORCED",
                violations=(),
                attempt_ids=(),
                observed_tools=(),
                terminal_statuses=(),
            )
        if task_id not in list(contract.get("subject_refs") or []):
            raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_TASK_MISMATCH")
        task_rows = self.truth.query("rc7_task", task_id=task_id)
        if len(task_rows) != 1 or str(task_rows[0].get("mission_id") or "") != mission_id:
            raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_TASK_NOT_UNIQUE")
        if str(task_rows[0].get("node") or "") != "EXECUTION":
            raise ExecutionRecoveryConformanceError("EXECUTION_RECOVERY_CONTRACT_REQUIRES_EXECUTION_TASK")

        violations: List[str] = []
        attempt_ids = _prepared_attempt_ids(self.truth, mission_id, task_id)
        node_tools = _node_tool_names(self.truth, mission_id, task_id)
        node_tool_set = set(node_tools)
        all_tools = set(node_tools)
        terminal_statuses: List[str] = []
        successor_targets = set()

        if not attempt_ids:
            violations.append("CASE_PREPARED_ATTEMPT_REQUIRED")
        if "runner_execute" not in node_tool_set:
            violations.append("RUNNER_EXECUTE_TOOL_CALL_REQUIRED")
        if "execution_convergence" not in node_tool_set:
            violations.append("EXECUTION_CONVERGENCE_TOOL_CALL_REQUIRED")

        for attempt_id in attempt_ids:
            execution = _exact_one(
                self.truth.query("execution_attempt", attempt_id=attempt_id),
                "EXECUTION_ATTEMPT_NOT_UNIQUE:%s" % attempt_id,
                violations,
            )
            if execution is None:
                continue
            exec_status = str(execution.get("status") or "").upper()
            convergence = _exact_one(
                self.truth.query("execution_convergence", attempt_id=attempt_id),
                "EXECUTION_CONVERGENCE_NOT_UNIQUE:%s" % attempt_id,
                violations,
            )
            convergence_status = str(convergence.get("status") or "").upper() if convergence else ""

            if exec_status == "PASS":
                if convergence_status != "PASS":
                    violations.append("PASS_ATTEMPT_REQUIRES_PASS_CONVERGENCE:%s:%s" % (attempt_id, convergence_status or "MISSING"))
                else:
                    terminal_statuses.append("PASS")
                continue

            if exec_status != "FAIL":
                violations.append("EXECUTION_TASK_PASS_FORBIDS_NONEXECUTED_ATTEMPT:%s:%s" % (attempt_id, exec_status or "UNKNOWN"))
                continue

            chain_tools = set(observed_chain_tools(self.truth, mission_id=mission_id, task_id=task_id, attempt_id=attempt_id))
            all_tools.update(chain_tools)
            if "failure_diagnose" not in chain_tools:
                violations.append("FAILURE_DIAGNOSE_CHAIN_CALL_REQUIRED:%s" % attempt_id)
            if "recovery_decide" not in chain_tools:
                violations.append("RECOVERY_DECIDE_CHAIN_CALL_REQUIRED:%s" % attempt_id)

            diagnosis = _exact_one(
                self.truth.query("failure_diagnosis", attempt_id=attempt_id),
                "FAILURE_DIAGNOSIS_NOT_UNIQUE:%s" % attempt_id,
                violations,
            )
            decision = _exact_one(
                self.truth.query("recovery_decision", attempt_id=attempt_id),
                "RECOVERY_DECISION_NOT_UNIQUE:%s" % attempt_id,
                violations,
            )
            if diagnosis is not None:
                _check_cat_truth(
                    self.truth,
                    mission_id=mission_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    diagnosis=diagnosis,
                    violations=violations,
                )
            if diagnosis is not None and decision is not None:
                if str(decision.get("diagnosis_id") or "") != str(diagnosis.get("diagnosis_id") or ""):
                    violations.append("RECOVERY_DECISION_DIAGNOSIS_MISMATCH:%s" % attempt_id)

            if decision is None:
                continue
            terminal = bool(decision.get("terminal"))
            next_attempt = str(decision.get("next_attempt_id") or "").strip()
            if terminal:
                if convergence_status == "RECOVERY_ALLOWED":
                    violations.append("TERMINAL_DECISION_CANNOT_REMAIN_RECOVERY_ALLOWED:%s" % attempt_id)
                if convergence_status not in PASS_READY_TERMINAL_STATUSES:
                    violations.append("EXECUTION_CHAIN_NOT_PASS_READY:%s:%s" % (attempt_id, convergence_status or "MISSING"))
                elif convergence_status:
                    terminal_statuses.append(convergence_status)
            else:
                if "recovery_execute" not in chain_tools:
                    violations.append("RECOVERY_EXECUTE_CHAIN_CALL_REQUIRED:%s" % attempt_id)
                actions = [
                    row for row in self.truth.query("recovery_action")
                    if str(row.get("prior_attempt_id") or "") == attempt_id
                ]
                action = _exact_one(
                    actions,
                    "RECOVERY_ACTION_NOT_UNIQUE:%s" % attempt_id,
                    violations,
                )
                if action is not None:
                    action_next = str(action.get("next_attempt_id") or "").strip()
                    if not bool(action.get("verified")):
                        violations.append("RECOVERY_ACTION_NOT_VERIFIED:%s" % attempt_id)
                    if not next_attempt or action_next != next_attempt:
                        violations.append("RECOVERY_SUCCESSOR_MISMATCH:%s" % attempt_id)
                    elif next_attempt not in attempt_ids:
                        violations.append("RECOVERY_SUCCESSOR_NOT_PREPARED:%s:%s" % (attempt_id, next_attempt))
                    else:
                        successor_targets.add(next_attempt)
                if convergence_status != "RECOVERY_ALLOWED":
                    violations.append("NONTERMINAL_DECISION_REQUIRES_RECOVERY_ALLOWED:%s:%s" % (attempt_id, convergence_status or "MISSING"))

        _ = successor_targets
        return ExecutionRecoveryConformanceResult(
            mission_id=mission_id,
            task_id=task_id,
            status="PASS" if not violations else "FAIL",
            violations=tuple(sorted(dict.fromkeys(violations))),
            attempt_ids=attempt_ids,
            observed_tools=tuple(sorted(all_tools)),
            terminal_statuses=tuple(sorted(terminal_statuses)),
        )

    def require_task_pass_ready(self, task: Task) -> ExecutionRecoveryConformanceResult:
        result = self.check_task(task.mission_id, task.task_id)
        if result.status == "FAIL":
            raise ExecutionRecoveryConformanceError(
                "EXECUTION_RECOVERY_CONFORMANCE_FAILED:%s" % ",".join(result.violations)
            )
        return result
