"""Runtime-owned Preparation -> immutable R1 PreparedAttempt truth.

This adapter reuses the proven RC6 PreparationRuntime instead of inventing a
second data-construction engine.  A frozen Test Case is resolved and verified
before Execution.  Every raw precondition/data/tool/human-gate evidence ref is
canonicalized into RC7 Evidence and the final PreparedAttempt is persisted as a
content-addressed Artifact in the same R1 Event Stream.

The attempt id is the immutability boundary.  Repeating the same attempt after a
session/process restart rehydrates the existing R1 artifact and does not run
preparation providers again.  Reusing the same attempt id with a different case
or target is rejected fail-closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.preparation import PreparedAttempt, PreparationRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, Evidence, TaskStatus
from .truth_overlay import append_entity


class RuntimePreparationError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")


@dataclass(frozen=True)
class RuntimePreparedAttempt:
    prepared: PreparedAttempt
    artifact_id: str
    evidence_ids: Tuple[str, ...]
    content_ref: str
    content_hash: str
    case_sha256: str


class RuntimePreparationService:
    """Execute governed preparation and persist/replay one immutable attempt."""

    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def prepare(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        case: Dict[str, Any],
        attempt_id: str,
        target_id: str,
        precondition_resolvers: Mapping[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_strategies: Mapping[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_verifier: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        human_gate: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    ) -> RuntimePreparedAttempt:
        task = control.scheduler.task(task_id)
        if task.node != "EXECUTION":
            raise RuntimePreparationError("PREPARATION_REQUIRES_EXECUTION_TASK")
        if task.state != TaskStatus.READY:
            raise RuntimePreparationError("PREPARATION_REQUIRES_READY_EXECUTION_TASK")
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise RuntimePreparationError("PREPARATION_ATTEMPT_ID_REQUIRED")
        if not isinstance(target_id, str) or not target_id.strip():
            raise RuntimePreparationError("PREPARATION_TARGET_ID_REQUIRED")
        if not isinstance(case, dict):
            raise RuntimePreparationError("PREPARATION_CASE_REQUIRED")

        attempt_id = attempt_id.strip()
        target_id = target_id.strip()
        case_bytes = _canonical_json(case)
        case_sha256 = hashlib.sha256(case_bytes).hexdigest()
        artifact_id = _stable_id("ART-PREPARED", control.mission_id, task_id, attempt_id)

        existing = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if existing:
            if len(existing) != 1:
                raise RuntimePreparationError("PREPARED_ATTEMPT_ARTIFACT_NOT_UNIQUE")
            return self._rehydrate_existing(
                control,
                task_id=task_id,
                row=existing[0],
                attempt_id=attempt_id,
                target_id=target_id,
                case_sha256=case_sha256,
            )

        runtime = PreparationRuntime(
            precondition_resolvers=dict(precondition_resolvers),
            data_strategies=dict(data_strategies),
            data_verifier=data_verifier,
            human_gate=human_gate,
        )
        prepared = runtime.prepare(
            case=case,
            attempt_id=attempt_id,
            target_id=target_id,
        )
        if prepared.status != "PREPARED":
            raise RuntimePreparationError("PREPARATION_DID_NOT_PRODUCE_PREPARED_ATTEMPT")

        folder = self.evidence_root / "prepared-attempts" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (attempt_id + ".json")
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "task_id": task_id,
            "case_sha256": case_sha256,
            "target_id": target_id,
            "prepared": asdict(prepared),
        }
        encoded = _canonical_json(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        if path.exists():
            current = path.read_bytes()
            if current != encoded:
                raise RuntimePreparationError("PREPARED_ATTEMPT_FILE_IMMUTABILITY_VIOLATION")
        else:
            path.write_bytes(encoded)

        evidence = []
        seen_raw = set()
        for kind, refs in (
            ("PRECONDITION_EVIDENCE", prepared.precondition_evidence),
            ("PREPARATION_BINDING_EVIDENCE", prepared.binding_evidence),
        ):
            for raw_ref in refs:
                if not isinstance(raw_ref, str) or not raw_ref.strip():
                    raise RuntimePreparationError("PREPARATION_RAW_EVIDENCE_REF_INVALID")
                raw_ref = raw_ref.strip()
                marker = (kind, raw_ref)
                if marker in seen_raw:
                    continue
                seen_raw.add(marker)
                evidence.append(
                    Evidence(
                        evidence_id=_stable_id(
                            "EVD-PREP-RAW",
                            control.mission_id,
                            attempt_id,
                            kind,
                            raw_ref,
                        ),
                        mission_id=control.mission_id,
                        kind=kind,
                        source_ref="runtime://preparation",
                        content_ref=raw_ref,
                        subject_refs=[task_id, attempt_id, prepared.tc_id],
                    )
                )

        record_evidence = Evidence(
            evidence_id=_stable_id("EVD-PREP-RECORD", control.mission_id, attempt_id, digest),
            mission_id=control.mission_id,
            kind="RUNTIME_PREPARATION_RECORD",
            source_ref="runtime://preparation",
            content_ref="file://" + str(path),
            subject_refs=[task_id, attempt_id, prepared.tc_id, target_id],
            content_hash="sha256:" + digest,
        )
        evidence.append(record_evidence)
        evidence_ids = tuple(item.evidence_id for item in evidence)

        for item in evidence:
            if not control.truth.query("rc7_evidence", evidence_id=item.evidence_id):
                append_entity(control.truth, item, release_id=control.release_id)

        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=control.mission_id,
            artifact_type="PREPARED_ATTEMPT",
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            parent_refs=[],
            evidence_refs=list(evidence_ids),
            content_hash="sha256:" + digest,
        )
        append_entity(control.truth, artifact, release_id=control.release_id, artifact_version=1)
        return RuntimePreparedAttempt(
            prepared=prepared,
            artifact_id=artifact_id,
            evidence_ids=evidence_ids,
            content_ref=artifact.content_ref,
            content_hash=artifact.content_hash or "",
            case_sha256=case_sha256,
        )

    def _rehydrate_existing(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        row: Dict[str, Any],
        attempt_id: str,
        target_id: str,
        case_sha256: str,
    ) -> RuntimePreparedAttempt:
        if row.get("mission_id") != control.mission_id:
            raise RuntimePreparationError("PREPARED_ATTEMPT_MISSION_MISMATCH")
        if row.get("producer_task_id") != task_id:
            raise RuntimePreparationError("PREPARED_ATTEMPT_TASK_MISMATCH")
        if row.get("artifact_type_name") != "PREPARED_ATTEMPT":
            raise RuntimePreparationError("PREPARED_ATTEMPT_ARTIFACT_TYPE_MISMATCH")
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise RuntimePreparationError("PREPARED_ATTEMPT_CONTENT_REF_INVALID")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise RuntimePreparationError("PREPARED_ATTEMPT_CONTENT_MISSING")
        encoded = path.read_bytes()
        digest = hashlib.sha256(encoded).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise RuntimePreparationError("PREPARED_ATTEMPT_CONTENT_HASH_MISMATCH")
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimePreparationError("PREPARED_ATTEMPT_CONTENT_INVALID") from exc
        if not isinstance(payload, dict):
            raise RuntimePreparationError("PREPARED_ATTEMPT_CONTENT_NOT_OBJECT")
        if payload.get("mission_id") != control.mission_id or payload.get("task_id") != task_id:
            raise RuntimePreparationError("PREPARED_ATTEMPT_CONTENT_OWNERSHIP_MISMATCH")
        if payload.get("case_sha256") != case_sha256:
            raise RuntimePreparationError("ATTEMPT_CASE_IMMUTABILITY_VIOLATION")
        if payload.get("target_id") != target_id:
            raise RuntimePreparationError("ATTEMPT_TARGET_IMMUTABILITY_VIOLATION")
        raw = payload.get("prepared")
        if not isinstance(raw, dict):
            raise RuntimePreparationError("PREPARED_ATTEMPT_PAYLOAD_REQUIRED")
        try:
            prepared = PreparedAttempt(
                status=str(raw["status"]),
                attempt_id=str(raw["attempt_id"]),
                tc_id=str(raw["tc_id"]),
                case_version=int(raw["case_version"]),
                target_id=str(raw["target_id"]),
                precondition_evidence=tuple(raw.get("precondition_evidence", [])),
                initial_state_bindings=dict(raw.get("initial_state_bindings", {})),
                input_data_bindings=dict(raw.get("input_data_bindings", {})),
                binding_evidence=tuple(raw.get("binding_evidence", [])),
                cleanup_policy=dict(raw.get("cleanup_policy", {})),
                oracle_snapshot=dict(raw.get("oracle_snapshot", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimePreparationError("PREPARED_ATTEMPT_PAYLOAD_INVALID") from exc
        if prepared.attempt_id != attempt_id or prepared.target_id != target_id or prepared.status != "PREPARED":
            raise RuntimePreparationError("PREPARED_ATTEMPT_IDENTITY_MISMATCH")
        evidence_ids = tuple(row.get("evidence_refs", []))
        if not evidence_ids:
            raise RuntimePreparationError("PREPARED_ATTEMPT_EVIDENCE_REQUIRED")
        for evidence_id in evidence_ids:
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != control.mission_id:
                raise RuntimePreparationError("PREPARED_ATTEMPT_EVIDENCE_NOT_DURABLE")
        return RuntimePreparedAttempt(
            prepared=prepared,
            artifact_id=str(row["artifact_id"]),
            evidence_ids=evidence_ids,
            content_ref=content_ref,
            content_hash=str(row.get("content_hash") or ""),
            case_sha256=case_sha256,
        )
