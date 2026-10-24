"""Autonomous N1 adoption for runtime-owned Reality Recon.

The legacy RuntimeRealityReconService remains the producer of immutable reality
truth.  This adapter adds the RC-AUTONOMOUS-TEST-LOOP node contract: a legacy
REALITY_RECON PASS is not sufficient by itself.  N1 may publish a delivery only
when the snapshot proves the current environment/target and every mandatory
runtime capability is backed by durable R1 evidence from the same Mission.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from .autonomous_node_adoption import AutonomousNodeAdoptionControl
from .autonomous_node_control import NodeDeliveryReceipt
from .closed_loop_control import ClosedLoopControlPlane
from .reality_recon import RuntimeRealitySnapshot


class AutonomousRealityNodeError(RuntimeError):
    pass


class AutonomousRealityNodeService:
    """Bind real Runtime Reality Recon truth into the durable N1 node gate."""

    REQUIRED_CAPABILITIES = (
        "dsh_headless",
        "agent_teams_bootstrap",
        "fresh_auth",
        "browser_network_route_discovery",
        "runtime_execution",
    )

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = str(Path(evidence_root).expanduser().resolve())

    def publish_ready(
        self,
        control: ClosedLoopControlPlane,
        snapshot: RuntimeRealitySnapshot,
        *,
        run_id: str,
    ) -> NodeDeliveryReceipt:
        task = control.scheduler.task(snapshot.task_id)
        if task.node != "REALITY_RECON" or task.task_type != "RUNTIME":
            raise AutonomousRealityNodeError("N1_RUNTIME_REALITY_TASK_REQUIRED")
        if task.state.value != "PASS":
            raise AutonomousRealityNodeError("N1_REALITY_PASS_REQUIRED")

        artifact = self._one(
            control,
            "rc7_artifact",
            "artifact_id",
            snapshot.artifact_id,
            "N1_REALITY_ARTIFACT_NOT_UNIQUE",
        )
        if artifact.get("mission_id") != control.mission_id:
            raise AutonomousRealityNodeError("N1_REALITY_ARTIFACT_MISSION_MISMATCH")
        if artifact.get("producer_task_id") != snapshot.task_id:
            raise AutonomousRealityNodeError("N1_REALITY_ARTIFACT_OWNER_MISMATCH")
        if artifact.get("content_hash") != snapshot.content_hash:
            raise AutonomousRealityNodeError("N1_REALITY_ARTIFACT_HASH_MISMATCH")

        payload = self._load_snapshot(artifact)
        if payload.get("mission_id") != control.mission_id or payload.get("release_id") != control.release_id:
            raise AutonomousRealityNodeError("N1_REALITY_SNAPSHOT_IDENTITY_MISMATCH")
        facts = payload.get("facts")
        if not isinstance(facts, dict):
            raise AutonomousRealityNodeError("N1_REALITY_FACTS_REQUIRED")

        environment_id = self._required_text(facts.get("environment_id"), "N1_ENVIRONMENT_ID_REQUIRED")
        target_version = self._required_text(facts.get("target_version"), "N1_TARGET_VERSION_REQUIRED")
        source_revision = self._required_text(facts.get("source_revision"), "N1_SOURCE_REVISION_REQUIRED")

        source_refs = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in payload.get("evidence_refs") or []
                if isinstance(value, str) and value.strip()
            )
        )
        durable_evidence = self._durable_evidence(control, snapshot.evidence_ids)
        by_content_ref = {
            str(row.get("content_ref")): row
            for row in durable_evidence
            if isinstance(row.get("content_ref"), str)
        }

        capabilities = facts.get("capabilities")
        if not isinstance(capabilities, dict):
            raise AutonomousRealityNodeError("N1_CAPABILITY_MATRIX_REQUIRED")
        capability_evidence = []
        for capability in self.REQUIRED_CAPABILITIES:
            capability_evidence.append(
                self._verify_probe(
                    capability,
                    capabilities.get(capability),
                    source_refs=source_refs,
                    by_content_ref=by_content_ref,
                    task_id=snapshot.task_id,
                    artifact_id=snapshot.artifact_id,
                    error_prefix="N1_CAPABILITY",
                )
            )

        services = facts.get("required_services")
        if not isinstance(services, dict) or not services:
            raise AutonomousRealityNodeError("N1_REQUIRED_SERVICES_REQUIRED")
        service_evidence = []
        for service_name in sorted(str(key) for key in services):
            service_evidence.append(
                self._verify_probe(
                    service_name,
                    services.get(service_name),
                    source_refs=source_refs,
                    by_content_ref=by_content_ref,
                    task_id=snapshot.task_id,
                    artifact_id=snapshot.artifact_id,
                    error_prefix="N1_SERVICE",
                )
            )

        task_row = self._one(
            control,
            "rc7_task",
            "task_id",
            snapshot.task_id,
            "N1_REALITY_TASK_NOT_UNIQUE",
        )
        evaluation_id = self._required_text(
            task_row.get("evaluation_id"),
            "N1_REALITY_EVALUATION_REQUIRED",
        )
        evaluation = self._one(
            control,
            "rc7_evaluation",
            "evaluation_id",
            evaluation_id,
            "N1_REALITY_EVALUATION_NOT_UNIQUE",
        )
        if evaluation.get("mission_id") != control.mission_id:
            raise AutonomousRealityNodeError("N1_REALITY_EVALUATION_MISSION_MISMATCH")
        if evaluation.get("node") != "REALITY_RECON" or evaluation.get("result") != "PASS":
            raise AutonomousRealityNodeError("N1_REALITY_RUNTIME_VERIFICATION_PASS_REQUIRED")

        adoption = AutonomousNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=self.evidence_root,
        )
        input_version = "%s|%s|%s" % (target_version, source_revision, snapshot.content_hash)
        delta_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                {
                    "snapshot": snapshot.content_hash,
                    "capabilities": sorted(capability_evidence),
                    "services": sorted(service_evidence),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        iteration = adoption.node_control.start_iteration(
            mission_id=control.mission_id,
            run_id=self._required_text(run_id, "N1_RUN_ID_REQUIRED"),
            node_id="N1",
            input_version=input_version,
            delta_hash=delta_hash,
        )
        return adoption.publish_ready_from_evaluated_task(
            iteration=iteration,
            source_task_id=snapshot.task_id,
            source_evaluation_id=evaluation_id,
            artifact_refs=(snapshot.artifact_id,),
            evidence_refs=tuple(snapshot.evidence_ids),
            reviewer_result={
                "result": "PASS",
                "runtime_owned": True,
                "source_evaluator_ref": evaluation.get("evaluator_ref"),
                "source_evaluation_id": evaluation_id,
            },
            sufficiency_result={
                "result": "PASS",
                "environment_id": environment_id,
                "target_version": target_version,
                "source_revision": source_revision,
                "verified_capabilities": list(self.REQUIRED_CAPABILITIES),
                "verified_services": sorted(str(key) for key in services),
                "bank_field_certification_authority": False,
            },
        )

    @staticmethod
    def _load_snapshot(artifact: Mapping[str, Any]) -> Dict[str, Any]:
        content_ref = str(artifact.get("content_ref") or "")
        if not content_ref.startswith("file://"):
            raise AutonomousRealityNodeError("N1_REALITY_FILE_REF_REQUIRED")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise AutonomousRealityNodeError("N1_REALITY_FILE_MISSING")
        raw = path.read_bytes()
        expected_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        if artifact.get("content_hash") != expected_hash:
            raise AutonomousRealityNodeError("N1_REALITY_FILE_HASH_MISMATCH")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise AutonomousRealityNodeError("N1_REALITY_PAYLOAD_INVALID") from exc
        if not isinstance(payload, dict):
            raise AutonomousRealityNodeError("N1_REALITY_PAYLOAD_INVALID")
        return payload

    @staticmethod
    def _durable_evidence(
        control: ClosedLoopControlPlane,
        evidence_ids: Sequence[str],
    ) -> Tuple[Mapping[str, Any], ...]:
        if not evidence_ids:
            raise AutonomousRealityNodeError("N1_DURABLE_EVIDENCE_REQUIRED")
        rows = []
        for evidence_id in evidence_ids:
            found = control.truth.query("rc7_evidence", evidence_id=str(evidence_id))
            if len(found) != 1:
                raise AutonomousRealityNodeError("N1_EVIDENCE_NOT_UNIQUE:%s" % evidence_id)
            row = found[0]
            if row.get("mission_id") != control.mission_id:
                raise AutonomousRealityNodeError("N1_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id)
            rows.append(row)
        return tuple(rows)

    @staticmethod
    def _verify_probe(
        name: str,
        value: Any,
        *,
        source_refs: Sequence[str],
        by_content_ref: Mapping[str, Mapping[str, Any]],
        task_id: str,
        artifact_id: str,
        error_prefix: str,
    ) -> str:
        if not isinstance(value, dict):
            raise AutonomousRealityNodeError("%s_PROOF_REQUIRED:%s" % (error_prefix, name))
        if str(value.get("status") or "").upper() != "VERIFIED":
            raise AutonomousRealityNodeError("%s_NOT_VERIFIED:%s" % (error_prefix, name))
        evidence_ref = str(value.get("evidence_ref") or "").strip()
        if not evidence_ref:
            raise AutonomousRealityNodeError("%s_EVIDENCE_REQUIRED:%s" % (error_prefix, name))
        if evidence_ref not in source_refs:
            raise AutonomousRealityNodeError("%s_EVIDENCE_NOT_IN_SNAPSHOT:%s" % (error_prefix, name))
        row = by_content_ref.get(evidence_ref)
        if row is None:
            raise AutonomousRealityNodeError("%s_DURABLE_EVIDENCE_REQUIRED:%s" % (error_prefix, name))
        subjects = set(str(item) for item in row.get("subject_refs") or [])
        if task_id not in subjects or artifact_id not in subjects:
            raise AutonomousRealityNodeError("%s_EVIDENCE_BINDING_MISMATCH:%s" % (error_prefix, name))
        return str(row.get("evidence_id"))

    @staticmethod
    def _one(
        control: ClosedLoopControlPlane,
        entity_type: str,
        field: str,
        value: str,
        code: str,
    ) -> Mapping[str, Any]:
        rows = control.truth.query(entity_type, **{field: value})
        if len(rows) != 1:
            raise AutonomousRealityNodeError(code)
        return rows[0]

    @staticmethod
    def _required_text(value: Any, code: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise AutonomousRealityNodeError(code)
        return text
