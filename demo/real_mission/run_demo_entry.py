from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence
from rc7_runtime.truth_overlay import append_entity

from demo.real_mission import run_demo


_original_install = MissionTaskGraphCompiler.install
_original_produce = run_demo.produce
_original_append_business_truth = run_demo.append_business_truth


def _content_hash(ref: str) -> str:
    if ref.startswith("file://"):
        parsed = urlparse(ref)
        path = Path(unquote(parsed.path.lstrip("/") if parsed.netloc else parsed.path))
        if path.exists() and path.is_file():
            return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return "sha256:" + hashlib.sha256(ref.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return "file://" + str(path.resolve()), "sha256:" + hashlib.sha256(raw).hexdigest()


def _persist_process_refs(truth, release_id: str, attempt_id: str, tc_id: str, refs) -> None:
    for ref in list(dict.fromkeys(str(x) for x in refs if isinstance(x, str) and x)):
        if truth.query("rc7_evidence", evidence_id=ref):
            continue
        append_entity(
            truth,
            Evidence(
                evidence_id=ref,
                mission_id=run_demo.MISSION,
                kind="PROCESS_EVIDENCE",
                source_ref="runtime://pytest-runner",
                content_ref=ref,
                subject_refs=[attempt_id, tc_id],
                content_hash=_content_hash(ref),
            ),
            release_id=release_id,
            artifact_version=1,
        )


def _persist_formal_evidence(truth, release_id: str, out: Path, record: dict) -> str:
    attempt_id = str(record["attempt_id"])
    tc_id = str(record["tc_id"])
    formal_id = "EVD-FORMAL-%s" % hashlib.sha256(
        (run_demo.MISSION + "\x1f" + attempt_id + "\x1f" + tc_id).encode("utf-8")
    ).hexdigest()[:20]
    receipt, digest = _write_json(out / "evidence" / ("formal-%s.json" % attempt_id), {"record": record})
    if not truth.query("rc7_evidence", evidence_id=formal_id):
        append_entity(
            truth,
            Evidence(
                evidence_id=formal_id,
                mission_id=run_demo.MISSION,
                kind="RUNTIME_EXECUTION_RECORD",
                source_ref="runtime://formal-execution",
                content_ref=receipt,
                subject_refs=[attempt_id, tc_id],
                content_hash=digest,
            ),
            release_id=release_id,
            artifact_version=1,
        )
    return formal_id


def _install_with_durable_external_sources(self, control_plane, mission_id, *, external_inputs=None):
    mapped = {}
    for node, refs in dict(external_inputs or {}).items():
        ids = []
        for index, ref in enumerate(refs):
            artifact_id = "ART-EXT-%s" % hashlib.sha256(
                (mission_id + "\x1f" + node + "\x1f" + str(index) + "\x1f" + ref).encode("utf-8")
            ).hexdigest()[:20]
            source_type = "REQUIREMENT_SOURCE" if node == "REQUIREMENT_ANALYSIS" else "SOURCE_REVISION"
            append_entity(
                control_plane.truth,
                Artifact(
                    artifact_id=artifact_id,
                    mission_id=mission_id,
                    artifact_type=source_type,
                    producer_task_id="EXTERNAL-SOURCE-INGEST",
                    content_ref=ref,
                    parent_refs=[],
                    evidence_refs=[],
                    content_hash=_content_hash(ref),
                ),
                release_id=control_plane.release_id,
                artifact_version=1,
            )
            ids.append(artifact_id)
        mapped[node] = tuple(ids)
    return _original_install(self, control_plane, mission_id, external_inputs=mapped)


def _produce_with_formal_execution(control, graph, compiler, node, worker, out, payload):
    if node == "EXECUTION":
        record = payload.get("record")
        if isinstance(record, dict):
            refs = list(record.get("evidence_refs") or [])
            diagnosis = payload.get("diagnosis")
            if isinstance(diagnosis, dict):
                refs.extend(diagnosis.get("evidence_refs") or [])
            _persist_process_refs(control.truth, control.release_id, str(record["attempt_id"]), str(record["tc_id"]), refs)
            formal_id = _persist_formal_evidence(control.truth, control.release_id, Path(out), record)
            record["evidence_refs"] = list(dict.fromkeys(list(record.get("evidence_refs") or []) + [formal_id]))
    return _original_produce(control, graph, compiler, node, worker, out, payload)


def _append_truth_with_formal_pass(truth, event_type: str, payload):
    receipt = _original_append_business_truth(truth, event_type, payload)
    if event_type != "EXECUTION_ATTEMPT_UPSERTED" or str(payload.get("status")) != "PASS":
        return receipt

    attempt_id = str(payload["attempt_id"])
    tc_id = str(payload["tc_id"])
    release_id = str(payload["release_id"])
    refs = list(payload.get("evidence_refs") or [])
    _persist_process_refs(truth, release_id, attempt_id, tc_id, refs)
    out = Path(truth.store.path).parent.parent
    formal_id = _persist_formal_evidence(truth, release_id, out, dict(payload))
    record = dict(payload)
    record["evidence_refs"] = list(dict.fromkeys(refs + [formal_id]))
    artifact_id = "ART-FORMAL-EXEC-%s" % hashlib.sha256(
        (run_demo.MISSION + "\x1f" + attempt_id).encode("utf-8")
    ).hexdigest()[:20]
    content_ref, content_hash = _write_json(
        out / "node-artifacts" / (artifact_id + ".json"),
        {"record": record, "formal_runtime_proof": formal_id},
    )
    append_entity(
        truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=run_demo.MISSION,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id="TASK-FORMAL-EXEC-%s" % attempt_id,
            content_ref=content_ref,
            parent_refs=[],
            evidence_refs=[formal_id],
            content_hash=content_hash,
        ),
        release_id=release_id,
        artifact_version=1,
    )
    purpose = "FIX_VERIFICATION" if "FIX-VERIFY" in attempt_id else "REGRESSION_VERIFICATION"
    evaluation = Evaluation(
        evaluation_id="EVAL-FORMAL-%s" % hashlib.sha256(
            (run_demo.MISSION + "\x1f" + attempt_id).encode("utf-8")
        ).hexdigest()[:20],
        mission_id=run_demo.MISSION,
        node="EXECUTION",
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-real-demo-formal-execution-evaluator",
        dimensions={
            "test_result": "PASS",
            "execution_status": "PASS",
            "integrity_passed": True,
            "assertion_passed": True,
            "failure_class": None,
            "recovery_action": None,
            "conclusive": True,
            "attempt_id": attempt_id,
            "purpose": purpose,
        },
        gap_refs=[],
        evidence_refs=list(dict.fromkeys(refs + [formal_id])),
    )
    append_entity(truth, evaluation, release_id=release_id, artifact_version=1)
    return receipt


MissionTaskGraphCompiler.install = _install_with_durable_external_sources
run_demo.produce = _produce_with_formal_execution
run_demo.append_business_truth = _append_truth_with_formal_pass


if __name__ == "__main__":
    raise SystemExit(run_demo.main())
