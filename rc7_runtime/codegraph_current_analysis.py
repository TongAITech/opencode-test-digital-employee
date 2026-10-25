"""Current-analysis Git/CodeGraph provenance for RC7.1 N3.

Worker-authored ``tool_calls`` and semantic evidence are proposals, never proof.
This binder replays R1 for the exact analyzer invocation that produced the
current CODE_ANALYSIS Artifact and emits only proofs bound to the current task,
analysis id, target, source revision and changed file/symbol inventory.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .dsh_proof import code_tool_category
from .models import Evidence
from .truth_overlay import append_entity


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _argument_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    except (TypeError, ValueError):
        return str(value).lower()


def _revision_tokens(revision: str) -> Tuple[str, ...]:
    value = str(revision or "").strip()
    if not value:
        return ()
    parts = [item for item in re.split(r"\.\.\.?|->|\s+", value) if item]
    return tuple(dict.fromkeys(parts or [value]))


def _changed_symbol_refs(analysis: Mapping[str, Any]) -> Tuple[str, ...]:
    refs: List[str] = []
    values = analysis.get("changed_symbols")
    if not isinstance(values, list):
        return ()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        for key in ("symbol", "qualified_name", "name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in refs:
                refs.append(value.strip())
    return tuple(refs)


def _changed_symbol_ids(analysis: Mapping[str, Any]) -> Tuple[str, ...]:
    refs: List[str] = []
    values = analysis.get("changed_symbols")
    if not isinstance(values, list):
        return ()
    for item in values:
        if isinstance(item, Mapping):
            value = item.get("id")
            if isinstance(value, str) and value.strip() and value.strip() not in refs:
                refs.append(value.strip())
    return tuple(refs)


def _changed_files(analysis: Mapping[str, Any]) -> Tuple[str, ...]:
    values = analysis.get("changed_files")
    if not isinstance(values, list):
        return ()
    return tuple(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))


def _target_matches(arguments: Any, target_id: str) -> bool:
    if isinstance(arguments, Mapping):
        for key in ("repo_path", "repo", "repository", "target_id", "application"):
            value = arguments.get(key)
            if isinstance(value, str) and target_id.lower() in value.lower():
                return True
    return target_id.lower() in _argument_text(arguments)


def _git_matches(arguments: Any, target_id: str, revision: str) -> bool:
    if not _target_matches(arguments, target_id):
        return False
    text = _argument_text(arguments)
    tokens = _revision_tokens(revision)
    return bool(tokens) and all(token.lower() in text for token in tokens)


def _codegraph_matches(
    arguments: Any,
    target_id: str,
    files: Sequence[str],
    symbols: Sequence[str],
) -> bool:
    if not _target_matches(arguments, target_id):
        return False
    text = _argument_text(arguments)
    forbidden = (
        "tools/list", "tools_list", "list_tools", "capabilities", "health", "probe", "status",
    )
    if any(token in text for token in forbidden):
        return False
    anchors = [value.lower() for value in symbols if value]
    for path in files:
        if not path:
            continue
        anchors.append(path.lower())
        anchors.append(path.replace("\\", "/").rsplit("/", 1)[-1].lower())
    return bool(anchors) and any(anchor in text for anchor in anchors)


@dataclass(frozen=True)
class BoundCodeTools:
    evidence_ids: Tuple[str, ...]
    tool_calls: Tuple[Dict[str, str], ...]
    graph_evidence: Tuple[Dict[str, Any], ...]
    analyzer_attempt_id: str


class CurrentAnalysisCodeToolBinder:
    def bind(
        self,
        control: Any,
        *,
        analyzer_worker_id: str,
        task_id: str,
        artifact_id: str,
        artifact_row: Mapping[str, Any],
        target_id: str,
        analysis: Dict[str, Any],
    ) -> BoundCodeTools:
        analysis_id = str(analysis.get("analysis_id") or "").strip()
        if not analysis_id:
            raise RuntimeError("CODE_CURRENT_ANALYSIS_ID_REQUIRED")
        files = _changed_files(analysis)
        symbols = _changed_symbol_refs(analysis)
        symbol_ids = _changed_symbol_ids(analysis)
        java_changed = any(path.lower().endswith(".java") for path in files)
        if java_changed:
            # Java change can never opt out via a model-authored boolean.
            analysis["codegraph_required"] = True

        source_revisions = analysis.get("source_revisions")
        revision = ""
        if isinstance(source_revisions, Mapping):
            value = source_revisions.get(target_id)
            if isinstance(value, str):
                revision = value.strip()
        attempt_id = self._current_analyzer_attempt(
            control,
            artifact_row=artifact_row,
            analyzer_worker_id=analyzer_worker_id,
            task_id=task_id,
        )
        if not attempt_id or not revision:
            analysis["graph_evidence"] = []
            return BoundCodeTools((), (), (), attempt_id)

        proofs = self._current_tool_events(
            control,
            analyzer_worker_id=analyzer_worker_id,
            task_id=task_id,
            attempt_id=attempt_id,
        )
        evidence_ids: List[str] = []
        calls: List[Dict[str, str]] = []
        graph_rows: List[Dict[str, Any]] = []
        for proof in proofs:
            category = code_tool_category(str(proof["tool_name"]))
            arguments = proof.get("arguments")
            if proof.get("result_status") != "SUCCESS" or not proof.get("result_ref") or not proof.get("result_sha256"):
                continue
            if category == "git":
                if not _git_matches(arguments, target_id, revision):
                    continue
                kind = "GIT_CURRENT_ANALYSIS_PROVENANCE"
                evidence_id = _stable_id(
                    "EVD-CODE-GIT-CURRENT",
                    control.mission_id,
                    task_id,
                    analysis_id,
                    attempt_id,
                    str(proof["event_id"]),
                    str(proof["result_sha256"]),
                )
                content_ref = "git-current://%s/%s" % (
                    analysis_id,
                    str(proof["result_sha256"]).replace("sha256:", ""),
                )
            elif category == "codegraph":
                if not _codegraph_matches(arguments, target_id, files, symbols):
                    continue
                kind = "GRAPH_EVIDENCE_CURRENT_ANALYSIS"
                evidence_id = _stable_id(
                    "EVD-GRAPH-CURRENT",
                    control.mission_id,
                    task_id,
                    analysis_id,
                    attempt_id,
                    revision,
                    str(proof["event_id"]),
                    str(proof["result_sha256"]),
                )
                content_ref = "graph-evidence://%s/%s" % (
                    analysis_id,
                    str(proof["result_sha256"]).replace("sha256:", ""),
                )
            else:
                continue

            subject_refs = [
                task_id,
                artifact_id,
                analysis_id,
                target_id,
                attempt_id,
                "revision:%s" % revision,
            ]
            subject_refs.extend("file:%s" % path for path in files)
            subject_refs.extend("symbol:%s" % value for value in symbol_ids)
            if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
                append_entity(
                    control.truth,
                    Evidence(
                        evidence_id=evidence_id,
                        mission_id=control.mission_id,
                        kind=kind,
                        source_ref="r1-event://%s" % proof["event_id"],
                        content_ref=content_ref,
                        subject_refs=list(dict.fromkeys(subject_refs)),
                        content_hash=str(proof["result_sha256"]),
                    ),
                    release_id=control.release_id,
                    artifact_version=1,
                )
            evidence_ids.append(evidence_id)
            calls.append(
                {
                    "tool_id": category,
                    "call_ref": str(proof["call_ref"]),
                    "evidence_ref": evidence_id,
                    "target_id": target_id,
                    "analysis_id": analysis_id,
                    "attempt_id": attempt_id,
                    "result_ref": str(proof["result_ref"]),
                    "result_sha256": str(proof["result_sha256"]),
                    "source_revision": revision,
                }
            )
            if category == "codegraph":
                graph_rows.append(
                    {
                        "schema_version": "rc7.1.graph-evidence.v1",
                        "evidence_id": evidence_id,
                        "mission_id": control.mission_id,
                        "task_id": task_id,
                        "artifact_id": artifact_id,
                        "analysis_id": analysis_id,
                        "target_id": target_id,
                        "analyzer_worker_id": analyzer_worker_id,
                        "analyzer_attempt_id": attempt_id,
                        "source_revision": revision,
                        "changed_files": list(files),
                        "changed_symbol_ids": list(symbol_ids),
                        "codegraph_event_id": str(proof["event_id"]),
                        "call_ref": str(proof["call_ref"]),
                        "query_sha256": _canonical_hash(arguments),
                        "result_ref": str(proof["result_ref"]),
                        "result_sha256": str(proof["result_sha256"]),
                    }
                )

        # Runtime owns this field; any worker-authored graph_evidence is replaced.
        analysis["graph_evidence"] = graph_rows
        return BoundCodeTools(
            tuple(dict.fromkeys(evidence_ids)),
            tuple(calls),
            tuple(graph_rows),
            attempt_id,
        )

    @staticmethod
    def _current_analyzer_attempt(
        control: Any,
        *,
        artifact_row: Mapping[str, Any],
        analyzer_worker_id: str,
        task_id: str,
    ) -> str:
        attempts = set()
        refs = artifact_row.get("evidence_refs")
        if not isinstance(refs, list):
            return ""
        expected_source = "dsh://worker/%s" % analyzer_worker_id
        for evidence_id in refs:
            if not isinstance(evidence_id, str) or not evidence_id:
                continue
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                continue
            row = rows[0]
            if row.get("mission_id") != control.mission_id:
                continue
            if row.get("kind") != "DSH_RUNTIME_PROOF" or row.get("source_ref") != expected_source:
                continue
            subjects = row.get("subject_refs")
            if not isinstance(subjects, list) or task_id not in subjects:
                continue
            for value in subjects:
                if isinstance(value, str) and value and value != task_id:
                    attempts.add(value)
        return next(iter(attempts)) if len(attempts) == 1 else ""

    @staticmethod
    def _current_tool_events(
        control: Any,
        *,
        analyzer_worker_id: str,
        task_id: str,
        attempt_id: str,
    ) -> Tuple[Dict[str, Any], ...]:
        rows: List[Dict[str, Any]] = []
        expected_scope = "task:%s" % task_id
        seen = set()
        for event in control.truth.store.iter_raw():
            if event.get("event_type") != "WORKER_TOOL_CALLED":
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if payload.get("mission_id") != control.mission_id:
                continue
            if payload.get("worker_instance_id") != analyzer_worker_id:
                continue
            if payload.get("attempt_id") != attempt_id or payload.get("scope") != expected_scope:
                continue
            tool_call = payload.get("tool_call")
            if not isinstance(tool_call, Mapping):
                continue
            event_id = event.get("event_id")
            call_ref = tool_call.get("call_ref")
            tool_name = tool_call.get("tool_name")
            if not all(isinstance(value, str) and value for value in (event_id, call_ref, tool_name)):
                continue
            identity = (event_id, call_ref)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(
                {
                    "event_id": event_id,
                    "call_ref": call_ref,
                    "tool_name": tool_name,
                    "arguments": tool_call.get("arguments"),
                    "result_ref": tool_call.get("result_ref"),
                    "result_sha256": tool_call.get("result_sha256"),
                    "result_status": tool_call.get("result_status"),
                }
            )
        return tuple(rows)
