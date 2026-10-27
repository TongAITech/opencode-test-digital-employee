"""Fail-closed N4 TEST_DESIGN node worker.

Produces candidate test cases against the frozen risk denominator. The worker
never declares design sufficiency, MissionNode PASS, product quality or release.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import quote

from rc8_runtime import RuntimeProducerKind, runtime_event
from rc8_runtime.artifacts import ArtifactManifest

from .dsh_json_runner import DshJsonRunner, DshJsonRunnerError


class TestDesignWorkerError(RuntimeError):
    pass


class TestDesignWorker:
    producer_ref = "RC8_TEST_DESIGN_WORKER"

    def __init__(self, *, agent: Any, dsh_runner: DshJsonRunner, work_dir: str, now_fn: Optional[Any] = None) -> None:
        self.agent = agent
        self.dsh_runner = dsh_runner
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._now = now_fn or (lambda: int(time.time()))

    def execute(self, claimed: Any) -> Dict[str, Any]:
        work = getattr(claimed, "work_item", None)
        if not isinstance(work, dict) or not isinstance(work.get("identity"), dict):
            raise TestDesignWorkerError("CLAIMED_WORK_ITEM_IDENTITY_REQUIRED")
        identity = work["identity"]
        if str(identity.get("stage") or "") != "TEST_DESIGN":
            raise TestDesignWorkerError("WORK_ITEM_STAGE_NOT_TEST_DESIGN")
        work_item_id = self._required(identity.get("work_item_id"), "WORK_ITEM_ID_REQUIRED")
        test_run_id = self._required(identity.get("test_run_id"), "TEST_RUN_ID_REQUIRED")
        lease_id = self._required(getattr(claimed, "lease_id", None), "WORK_ITEM_LEASE_ID_REQUIRED")
        stage_instance_id = self._required(getattr(claimed, "stage_instance_id", None), "STAGE_INSTANCE_ID_REQUIRED")
        scope_refs = tuple(str(v).strip() for v in identity.get("scope_refs") or [] if str(v).strip())
        if not scope_refs:
            raise TestDesignWorkerError("N4_FROZEN_SCOPE_REFS_REQUIRED")

        self.agent.start(work_item_id, lease_id=lease_id)
        try:
            result = self.dsh_runner.run(self._prompt(scope_refs))
            candidate = self.validate_candidate(result.output)
        except DshJsonRunnerError as exc:
            raise TestDesignWorkerError("TEST_DESIGN_DSH_FAILED:%s" % exc.reason)

        artifact = {
            "schema_version": "rc8.test-design.v1", "authority": "NODE_OBSERVATION_ONLY",
            "test_run_id": test_run_id, "work_item_id": work_item_id,
            "stage_instance_id": stage_instance_id, "scope_refs": list(scope_refs),
            "candidate": candidate, "dsh_session_id": result.session_id,
            "tool_calls": list(result.tool_calls), "generated_at": self._now(),
        }
        artifact_id = "artifact-test-design-%s" % uuid.uuid4().hex
        artifact_ref = self._upload(artifact_id, artifact, test_run_id, work_item_id, stage_instance_id, lease_id, scope_refs)
        self.agent.append_runtime_event(runtime_event(
            event_id="evt-test-design-%s" % uuid.uuid4().hex, test_run_id=test_run_id,
            work_item_id=work_item_id, node_id=self.agent.identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER, producer_ref=self.producer_ref,
            event_type="ATTEMPT_COMPLETED", sequence=self._next_sequence(test_run_id),
            attempt_id=lease_id, refs=list(scope_refs),
            data={"stage_instance_id": stage_instance_id, "evidence_refs": [artifact_ref],
                  "authority": "NODE_OBSERVATION_ONLY", "finished_at": self._now()},
        ), lease_id=lease_id)
        terminal = self.agent.complete(work_item_id, lease_id=lease_id)
        return {"status": "COMPLETED", "attempt_id": lease_id, "artifact_ref": artifact_ref, "terminal": terminal}

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise TestDesignWorkerError("TEST_DESIGN_OUTPUT_OBJECT_REQUIRED")
        cases = value.get("test_cases")
        risk_ids = value.get("risk_denominator")
        evidence_refs = value.get("evidence_refs")
        if not isinstance(cases, list) or not cases:
            raise TestDesignWorkerError("TEST_CASES_NONEMPTY_REQUIRED")
        if not isinstance(risk_ids, list) or not risk_ids or len(set(str(x).strip() for x in risk_ids if str(x).strip())) != len(risk_ids):
            raise TestDesignWorkerError("RISK_DENOMINATOR_NONEMPTY_UNIQUE_REQUIRED")
        if not isinstance(evidence_refs, list) or not [x for x in evidence_refs if str(x).strip()]:
            raise TestDesignWorkerError("TEST_DESIGN_EVIDENCE_REFS_NONEMPTY_REQUIRED")
        denominator = {str(x).strip() for x in risk_ids}
        covered = set()
        case_ids = set()
        for case in cases:
            if not isinstance(case, dict) or not str(case.get("case_id") or "").strip():
                raise TestDesignWorkerError("TEST_CASE_ID_REQUIRED")
            case_id = str(case["case_id"]).strip()
            if case_id in case_ids:
                raise TestDesignWorkerError("TEST_CASE_ID_DUPLICATE")
            case_ids.add(case_id)
            mapped = {str(x).strip() for x in case.get("risk_ids") or [] if str(x).strip()}
            if not mapped or not mapped.issubset(denominator):
                raise TestDesignWorkerError("TEST_CASE_RISK_MAPPING_INVALID")
            for field in ("preconditions", "steps", "expected_results"):
                if not isinstance(case.get(field), list) or not case[field]:
                    raise TestDesignWorkerError("TEST_CASE_%s_NONEMPTY_REQUIRED" % field.upper())
            covered.update(mapped)
        if covered != denominator:
            raise TestDesignWorkerError("RISK_DENOMINATOR_NOT_FULLY_COVERED")
        return dict(value)

    def _upload(self, artifact_id: str, content: Dict[str, Any], test_run_id: str, work_item_id: str, stage_instance_id: str, lease_id: str, refs: Sequence[str]) -> str:
        target = self.work_dir / (artifact_id + ".json")
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        target.write_bytes(raw)
        manifest = ArtifactManifest(artifact_id=artifact_id, test_run_id=test_run_id, work_item_id=work_item_id,
            node_id=self.agent.identity.node_id, kind="TEST_DESIGN", producer_kind=RuntimeProducerKind.WORKER,
            producer_ref=self.producer_ref, file_name="test-design.json", sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), attempt_id=lease_id, refs=list(refs) + ["stage:%s" % stage_instance_id],
            metadata={"stage": "TEST_DESIGN", "authority": "NODE_OBSERVATION_ONLY"}, created_at=self._now())
        self.agent.upload_artifact_file(manifest, str(target), lease_id=lease_id)
        return "artifact:%s" % artifact_id

    def _next_sequence(self, test_run_id: str) -> int:
        value = self.agent.center.get("/api/v1/test-runs/%s/nodes/%s/runtime-sequence" % (quote(test_run_id, safe=""), quote(self.agent.identity.node_id, safe="")))
        sequence = value.get("next_sequence")
        if not isinstance(sequence, int) or sequence < 0:
            raise TestDesignWorkerError("R1_NEXT_SEQUENCE_INVALID")
        return sequence

    @staticmethod
    def _prompt(scope_refs: Sequence[str]) -> str:
        return ("You are RC8 N4 TEST_DESIGN. Use only frozen scope refs %s. Return strict JSON with test_cases, risk_denominator, evidence_refs. "
                "Every test case needs case_id, risk_ids, non-empty preconditions, steps and expected_results. Cover every risk denominator item; do not shrink it. "
                "Include normal, negative, boundary/state cases when supported by evidence. Never declare sufficiency, PASS, quality or release." % json.dumps(list(scope_refs), ensure_ascii=False))

    @staticmethod
    def _required(value: Any, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise TestDesignWorkerError(error)
        return normalized
