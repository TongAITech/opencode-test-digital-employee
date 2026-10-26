"""BANK DSH bridge with an explicit N8 owner-repair handoff contract.

Normal producer prompts are unchanged.  For non-direct REPAIR tasks only, the
bridge resolves the unique durable N8 work order and appends the exact fields the
independent owner-repair evaluator will verify.  The worker still cannot PASS its
own task and Runtime still canonicalizes all returned evidence.
"""
from __future__ import annotations

import json

from .active_task_supervisor import RecoverableDshTaskWorkerBridge
from .bank_n8_owner_repair_evaluator import BankN8OwnerRepairEvaluator
from .models import Task


class BankN8AwareDshTaskWorkerBridge(RecoverableDshTaskWorkerBridge):
    """Add N8 repair context without changing ordinary DSH producer semantics."""

    def compile_prompt(self, task: Task, assignment) -> str:
        prompt = super().compile_prompt(task, assignment)
        if task.task_type != "REPAIR" or task.node == "EXECUTION":
            return prompt

        work_order_evidence, payload = BankN8OwnerRepairEvaluator._work_order(
            self.control,
            task,
        )
        plan = payload.get("plan") or {}
        contract = {
            "repair_work_order_id": payload.get("work_order_id"),
            "work_order_evidence_id": work_order_evidence.get("evidence_id"),
            "work_order_content_ref": work_order_evidence.get("content_ref"),
            "gap_id": payload.get("gap_id"),
            "source_task_id": payload.get("source_task_id"),
            "repair_task_id": payload.get("repair_task_id"),
            "source_attempt_id": plan.get("source_attempt_id"),
            "successor_attempt_id": plan.get("successor_attempt_id"),
            "mode": plan.get("mode"),
            "target_node": plan.get("target_node"),
            "required_semantic_payload": {
                "repair_work_order_id": "copy the exact repair_work_order_id above",
                "repair_before_fingerprint": (
                    "stable fingerprint/hash of the relevant state immediately before the real repair"
                ),
                "repair_after_fingerprint": (
                    "stable fingerprint/hash of the same relevant state after the real repair; must differ from before"
                ),
                "repair_delta_evidence_refs": (
                    "non-empty list using the exact content_ref or source_ref aliases from top-level evidence items"
                ),
            },
            "required_top_level_evidence": {
                "kind": "REPAIR_DELTA_EVIDENCE",
                "rule": (
                    "Return concrete evidence created by the real repair/probe. Its content_ref/source_ref must be the "
                    "same alias used in semantic_payload.repair_delta_evidence_refs. Do not invent EVD ids."
                ),
            },
            "forbidden": [
                "declaring PASS or returning an Evaluation",
                "before and after fingerprints that are identical",
                "inventing repair evidence without a real allowed tool call/result",
                "changing the work_order_id, source/successor attempt identity, or target owner",
            ],
        }
        return (
            prompt
            + "\nN8_OWNER_REPAIR_HANDOFF_CONTRACT="
            + json.dumps(contract, ensure_ascii=False, sort_keys=True)
            + "\nExecute only the owner repair described by this contract. Return candidate output only; "
            "an independent Runtime evaluator decides whether the repair is accepted."
        )
