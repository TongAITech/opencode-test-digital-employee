"""Durable residual-risk registry for RC7.1 N10 convergence.

Residual risk is runtime truth, not prose in a report.  Records are immutable R1
Artifact/Evidence pairs.  A new disposition creates a successor revision; prior
revisions remain auditable.  N10 may consume only the current revision for each
risk and must fail closed while any risk remains PENDING.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .autonomous_events import AutonomousEvent
from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, EventRecord, Evidence
from .truth_overlay import append_entity


class ResidualRiskRegistryError(RuntimeError):
    pass


_ALLOWED_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
_ALLOWED_DISPOSITIONS = {"PENDING", "ACCEPTED", "DEFERRED", "MONITOR"}
_FINAL_DISPOSITIONS = {"ACCEPTED", "DEFERRED", "MONITOR"}


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ResidualRiskRegistryError(code)
    return text


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class ResidualRiskRecord:
    risk_id: str
    mission_id: str
    source: str
    severity: str
    description: str
    reason: str
    evidence_refs: Tuple[str, ...]
    owner: str
    disposition: str = "PENDING"
    acceptance_ref: str = ""
    revision: int = 1

    def __post_init__(self) -> None:
        for name in ("risk_id", "mission_id", "source", "description", "reason", "owner"):
            if not str(getattr(self, name) or "").strip():
                raise ResidualRiskRegistryError("RESIDUAL_RISK_%s_REQUIRED" % name.upper())
        severity = str(self.severity or "").upper()
        disposition = str(self.disposition or "").upper()
        if severity not in _ALLOWED_SEVERITIES:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_SEVERITY_INVALID")
        if disposition not in _ALLOWED_DISPOSITIONS:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_DISPOSITION_INVALID")
        if not self.evidence_refs:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_EVIDENCE_REQUIRED")
        if disposition in _FINAL_DISPOSITIONS and not str(self.acceptance_ref or "").strip():
            raise ResidualRiskRegistryError("RESIDUAL_RISK_DISPOSITION_REQUIRES_REFERENCE")
        if disposition == "PENDING" and str(self.acceptance_ref or "").strip():
            raise ResidualRiskRegistryError("PENDING_RESIDUAL_RISK_CANNOT_HAVE_ACCEPTANCE_REF")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_REVISION_INVALID")


@dataclass(frozen=True)
class ResidualRiskReceipt:
    record: ResidualRiskRecord
    artifact_id: str
    evidence_id: str
    record_sha256: str


class ResidualRiskRegistry:
    ARTIFACT_TYPE = "RESIDUAL_RISK_RECORD"
    EVIDENCE_KIND = "RESIDUAL_RISK_RECORD"

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def record(
        self,
        control: ClosedLoopControlPlane,
        *,
        risk_id: str,
        source: str,
        severity: str,
        description: str,
        reason: str,
        evidence_refs: Sequence[str],
        owner: str,
    ) -> ResidualRiskReceipt:
        risk_id = _required(risk_id, "RESIDUAL_RISK_ID_REQUIRED")
        if risk_id in self.current(control):
            raise ResidualRiskRegistryError("RESIDUAL_RISK_ALREADY_EXISTS:%s" % risk_id)
        evidence = tuple(dict.fromkeys(_required(x, "RESIDUAL_RISK_EVIDENCE_REQUIRED") for x in evidence_refs))
        self._require_current_evidence(control, evidence)
        record = ResidualRiskRecord(
            risk_id=risk_id,
            mission_id=control.mission_id,
            source=_required(source, "RESIDUAL_RISK_SOURCE_REQUIRED"),
            severity=str(severity or "").upper(),
            description=_required(description, "RESIDUAL_RISK_DESCRIPTION_REQUIRED"),
            reason=_required(reason, "RESIDUAL_RISK_REASON_REQUIRED"),
            evidence_refs=evidence,
            owner=_required(owner, "RESIDUAL_RISK_OWNER_REQUIRED"),
            disposition="PENDING",
            revision=1,
        )
        receipt = self._persist(control, record)
        self._event(
            control,
            event_name=AutonomousEvent.RESIDUAL_RISK_RECORDED.value,
            receipt=receipt,
        )
        return receipt

    def disposition(
        self,
        control: ClosedLoopControlPlane,
        *,
        risk_id: str,
        disposition: str,
        acceptance_ref: str,
        evidence_refs: Sequence[str],
        owner: Optional[str] = None,
    ) -> ResidualRiskReceipt:
        risk_id = _required(risk_id, "RESIDUAL_RISK_ID_REQUIRED")
        current = self.current(control).get(risk_id)
        if current is None:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_NOT_FOUND:%s" % risk_id)
        if current.record.disposition != "PENDING":
            raise ResidualRiskRegistryError("RESIDUAL_RISK_ALREADY_DISPOSITIONED:%s" % risk_id)
        disposition = str(disposition or "").upper()
        if disposition not in _FINAL_DISPOSITIONS:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_FINAL_DISPOSITION_REQUIRED")
        acceptance_ref = _required(acceptance_ref, "RESIDUAL_RISK_ACCEPTANCE_REF_REQUIRED")
        extra_evidence = tuple(dict.fromkeys(_required(x, "RESIDUAL_RISK_EVIDENCE_REQUIRED") for x in evidence_refs))
        self._require_current_evidence(control, extra_evidence)
        merged_evidence = tuple(dict.fromkeys(current.record.evidence_refs + extra_evidence))
        record = ResidualRiskRecord(
            risk_id=current.record.risk_id,
            mission_id=current.record.mission_id,
            source=current.record.source,
            severity=current.record.severity,
            description=current.record.description,
            reason=current.record.reason,
            evidence_refs=merged_evidence,
            owner=_required(owner or current.record.owner, "RESIDUAL_RISK_OWNER_REQUIRED"),
            disposition=disposition,
            acceptance_ref=acceptance_ref,
            revision=current.record.revision + 1,
        )
        receipt = self._persist(control, record, parent_artifact_id=current.artifact_id)
        self._event(
            control,
            event_name=AutonomousEvent.RESIDUAL_RISK_DISPOSITIONED.value,
            receipt=receipt,
        )
        return receipt

    def current(self, control: ClosedLoopControlPlane) -> Dict[str, ResidualRiskReceipt]:
        by_risk: Dict[str, Dict[int, ResidualRiskReceipt]] = {}
        for artifact in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if artifact.get("artifact_type_name") != self.ARTIFACT_TYPE or artifact.get("state") != "VALID":
                continue
            receipt = self._receipt_from_artifact(control, artifact)
            versions = by_risk.setdefault(receipt.record.risk_id, {})
            if receipt.record.revision in versions:
                raise ResidualRiskRegistryError(
                    "RESIDUAL_RISK_REVISION_NOT_UNIQUE:%s:%d"
                    % (receipt.record.risk_id, receipt.record.revision)
                )
            versions[receipt.record.revision] = receipt
        return {
            risk_id: versions[max(versions)]
            for risk_id, versions in sorted(by_risk.items())
        }

    def summary(self, control: ClosedLoopControlPlane) -> Mapping[str, object]:
        current = self.current(control)
        counts = {name: 0 for name in sorted(_ALLOWED_DISPOSITIONS)}
        risks = []
        for risk_id in sorted(current):
            receipt = current[risk_id]
            counts[receipt.record.disposition] += 1
            risks.append(
                dict(
                    asdict(receipt.record),
                    artifact_id=receipt.artifact_id,
                    evidence_id=receipt.evidence_id,
                    record_sha256=receipt.record_sha256,
                )
            )
        pending = tuple(item["risk_id"] for item in risks if item["disposition"] == "PENDING")
        return {
            "risk_count": len(risks),
            "counts_by_disposition": counts,
            "pending_risk_ids": list(pending),
            "all_dispositioned": not pending,
            "risks": risks,
        }

    def _persist(
        self,
        control: ClosedLoopControlPlane,
        record: ResidualRiskRecord,
        *,
        parent_artifact_id: str = "",
    ) -> ResidualRiskReceipt:
        payload = dict(asdict(record), schema_version="RC7_1_RESIDUAL_RISK_V1")
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "residual-risk" / control.mission_id / record.risk_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("v%04d-%s.json" % (record.revision, digest[:20]))
        if path.exists() and path.read_bytes() != encoded:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        evidence_id = _stable_id(
            "EVD-RESIDUAL-RISK",
            control.mission_id,
            record.risk_id,
            record.revision,
            digest,
        )
        artifact_id = _stable_id(
            "ART-RESIDUAL-RISK",
            control.mission_id,
            record.risk_id,
            record.revision,
            digest,
        )
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind=self.EVIDENCE_KIND,
            source_ref="runtime://residual-risk-registry",
            content_ref="file://" + str(path),
            subject_refs=[
                record.risk_id,
                "revision:%d" % record.revision,
                "disposition:%s" % record.disposition,
                record.owner,
            ],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type=self.ARTIFACT_TYPE,
            producer_task_id=_stable_id("TASK-RESIDUAL-RISK", control.mission_id, record.risk_id),
            content_ref="file://" + str(path),
            parent_refs=[parent_artifact_id] if parent_artifact_id else [],
            evidence_refs=[evidence_id] + list(record.evidence_refs),
            content_hash="sha256:" + digest,
        )
        if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(control.truth, evidence, release_id=control.release_id, artifact_version=record.revision)
        if not control.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(control.truth, artifact, release_id=control.release_id, artifact_version=record.revision)
        return ResidualRiskReceipt(record, artifact_id, evidence_id, digest)

    def _receipt_from_artifact(
        self,
        control: ClosedLoopControlPlane,
        artifact: Mapping[str, object],
    ) -> ResidualRiskReceipt:
        content_ref = str(artifact.get("content_ref") or "")
        if not content_ref.startswith("file://"):
            raise ResidualRiskRegistryError("RESIDUAL_RISK_FILE_REQUIRED")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise ResidualRiskRegistryError("RESIDUAL_RISK_FILE_MISSING")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if artifact.get("content_hash") != "sha256:" + digest:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_HASH_MISMATCH")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_JSON_INVALID") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "RC7_1_RESIDUAL_RISK_V1":
            raise ResidualRiskRegistryError("RESIDUAL_RISK_SCHEMA_INVALID")
        try:
            record = ResidualRiskRecord(
                risk_id=str(payload["risk_id"]),
                mission_id=str(payload["mission_id"]),
                source=str(payload["source"]),
                severity=str(payload["severity"]),
                description=str(payload["description"]),
                reason=str(payload["reason"]),
                evidence_refs=tuple(payload["evidence_refs"]),
                owner=str(payload["owner"]),
                disposition=str(payload["disposition"]),
                acceptance_ref=str(payload.get("acceptance_ref") or ""),
                revision=int(payload["revision"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_RECORD_INVALID") from exc
        if record.mission_id != control.mission_id:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_MISSION_MISMATCH")
        evidence_refs = list(artifact.get("evidence_refs") or [])
        registry_refs = [
            ref
            for ref in evidence_refs
            if control.truth.query("rc7_evidence", evidence_id=str(ref))
            and control.truth.query("rc7_evidence", evidence_id=str(ref))[0].get("kind") == self.EVIDENCE_KIND
        ]
        if len(registry_refs) != 1:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_REGISTRY_EVIDENCE_NOT_UNIQUE")
        self._require_current_evidence(control, record.evidence_refs)
        return ResidualRiskReceipt(
            record=record,
            artifact_id=str(artifact.get("artifact_id") or ""),
            evidence_id=str(registry_refs[0]),
            record_sha256=digest,
        )

    @staticmethod
    def _require_current_evidence(
        control: ClosedLoopControlPlane,
        evidence_refs: Sequence[str],
    ) -> None:
        if not evidence_refs:
            raise ResidualRiskRegistryError("RESIDUAL_RISK_EVIDENCE_REQUIRED")
        for evidence_id in evidence_refs:
            rows = control.truth.query("rc7_evidence", evidence_id=str(evidence_id))
            if len(rows) != 1:
                raise ResidualRiskRegistryError("RESIDUAL_RISK_EVIDENCE_NOT_UNIQUE:%s" % evidence_id)
            if rows[0].get("mission_id") != control.mission_id:
                raise ResidualRiskRegistryError("RESIDUAL_RISK_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id)

    @staticmethod
    def _event(
        control: ClosedLoopControlPlane,
        *,
        event_name: str,
        receipt: ResidualRiskReceipt,
    ) -> None:
        event_id = _stable_id(
            "EVT-RESIDUAL-RISK",
            control.mission_id,
            receipt.record.risk_id,
            receipt.record.revision,
            event_name,
            receipt.record_sha256,
        )
        if control.truth.query("rc7_control_event", event_id=event_id):
            return
        append_entity(
            control.truth,
            EventRecord(
                event_id=event_id,
                mission_id=control.mission_id,
                event_type=event_name,
                subject_type="RESIDUAL_RISK",
                subject_id=receipt.record.risk_id,
                refs=[receipt.artifact_id, receipt.evidence_id] + list(receipt.record.evidence_refs),
                data={
                    "revision": receipt.record.revision,
                    "severity": receipt.record.severity,
                    "disposition": receipt.record.disposition,
                    "owner": receipt.record.owner,
                    "acceptance_ref": receipt.record.acceptance_ref,
                    "record_sha256": receipt.record_sha256,
                },
            ),
            release_id=control.release_id,
            artifact_version=receipt.record.revision,
        )
