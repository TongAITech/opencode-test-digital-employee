"""Recovery intake facade over existing R1/G3/R3.1 authority.

Documents, approved release exports and versioned BR/SR/TR are immutable G3
facts. Their content and provenance replay after Session/process replacement.
Caches contain original attachment bytes only; they never decide product truth.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from urllib.parse import urlsplit
from datetime import datetime, timezone
from typing import Any, Mapping
from xml.etree import ElementTree

from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.g3.contracts import G3State, _json
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.r2_1.contracts import validate_secret_boundary

SCHEMA = "aitest.recovery-intake.v1"
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024
KINDS = {"BR", "SR", "TR"}
SEMANTIC_FIELDS = ("business_rules", "field_data_rules", "state_transitions", "positive_paths", "negative_paths",
                   "exception_paths", "boundary_rules", "permission_rules", "cross_system_flows", "acceptance_criteria",
                   "non_functional_risks", "unknowns")


def _release_index(payload: Mapping[str, Any], *, offset: int = 0, limit: int = 24) -> dict[str, Any]:
    """Bounded, explicit repository/requirement identity from approved exports."""
    fields = ("repository_id", "application_id", "repository_path", "repo_path", "base_ref", "head_ref", "base_commit", "head_commit", "branch")
    repositories = list(payload.get("repositories") or [])
    requirements = list(payload.get("requirements") or [])
    rows = []
    for value in repositories[offset:offset + limit]:
        if not isinstance(value, Mapping):
            continue
        row = {}
        for field in fields:
            item = value.get(field)
            if isinstance(item, str) and item.strip():
                parsed = urlsplit(item)
                if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
                    row[field + "_withheld"] = "CREDENTIAL_BEARING_URL"
                elif len(item) > 1024:
                    row[field + "_withheld"] = "VALUE_EXCEEDS_CONTEXT_BUDGET"
                else:
                    row[field] = item
        rows.append(row)
    req_rows = []
    for value in requirements[offset:offset + limit]:
        if not isinstance(value, Mapping):
            continue
        row = {key: value[key] for key in ("requirement_id", "revision") if isinstance(value.get(key), str) and len(value[key]) <= 1024}
        if isinstance(value.get("sst_ids"), list):
            row["sst_ids"] = [item for item in value["sst_ids"][:20] if isinstance(item, str) and len(item) <= 256]
            row["sst_count"] = len(value["sst_ids"])
        req_rows.append(row)
    return {"repositories": rows, "requirements": req_rows, "repository_count": len(repositories),
            "requirement_count": len(requirements), "next_offset": offset + limit if offset + limit < max(len(repositories), len(requirements)) else None}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("RECOVERY_INPUT_INVALID", f"{field} must be non-empty text")
    return value.strip()


def _sha(value: Any, field: str = "sha256") -> str:
    result = _text(value, field)
    if not re.fullmatch("[0-9a-f]{64}", result):
        raise RuntimeError("RECOVERY_DIGEST_INVALID", field)
    return result


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone required")
        return result
    except (TypeError, ValueError) as exc:
        raise RuntimeError("RECOVERY_TIME_INVALID", str(value)) from exc


def _revision_guard(state: G3State, kind: str, payload: Mapping[str, Any], identity: tuple[str, ...]) -> None:
    for fact in state.by_kind(kind):
        if all(fact.payload.get(name) == payload.get(name) for name in identity):
            if canonical_sha256(fact.payload) != canonical_sha256(payload):
                raise RuntimeError("RECOVERY_REVISION_CONFLICT", "existing revision is immutable; supply a new revision")


def validate_recovery_fact(kind: str, payload: Mapping[str, Any], state: G3State) -> None:
    """Enforce intake invariants at G3 command ingress, including direct calls."""
    if kind not in {"SOURCE_DOCUMENT", "REQUIREMENT_ANALYSIS_ARTIFACT", "CURRENT_RELEASE", "CURRENT_RELEASE_BINDING", "RUNTIME_FACTS_RESOLUTION"}:
        return
    _json(payload, allow_sensitive_references=kind == "RUNTIME_FACTS_RESOLUTION")
    validate_secret_boundary(payload)
    if kind == "RUNTIME_FACTS_RESOLUTION":
        resolution = payload.get("resolution")
        if not isinstance(resolution, Mapping) or not resolution.get("snapshot_id"):
            raise RuntimeError("RECOVERY_RESOLUTION_INVALID", "full canonical resolution required")
        for name in ("resolution_id", "request_digest", "status", "scope"):
            if not resolution.get(name):
                raise RuntimeError("RECOVERY_RESOLUTION_INVALID", name)
        return
    if kind == "SOURCE_DOCUMENT":
        for name in ("source_id", "source_kind", "revision", "locator", "text", "parser"):
            _text(payload.get(name), name)
        if payload["source_kind"] not in {"REQUIREMENT", "SST", "DESIGN"}:
            raise RuntimeError("RECOVERY_SOURCE_KIND_INVALID", str(payload["source_kind"]))
        _sha(payload.get("sha256"))
        if hashlib.sha256(payload["text"].encode("utf-8")).hexdigest() != payload.get("text_sha256"):
            raise RuntimeError("RECOVERY_TEXT_DIGEST_MISMATCH", str(payload["source_id"]))
        _revision_guard(state, kind, payload, ("source_id", "revision"))
    elif kind == "REQUIREMENT_ANALYSIS_ARTIFACT":
        for name in ("artifact_id", "scope_identity", "revision", "text", "kind"):
            _text(payload.get(name), name)
        level = payload["kind"]
        if level not in KINDS:
            raise RuntimeError("RECOVERY_ANALYSIS_KIND_INVALID", str(level))
        sources = payload.get("source_refs")
        if not isinstance(sources, list) or not sources:
            raise RuntimeError("RECOVERY_PROVENANCE_REQUIRED", "source document references required")
        for ref in sources:
            fact = state.by_id(str(ref))
            if fact is None or fact.fact_kind != "SOURCE_DOCUMENT":
                raise RuntimeError("RECOVERY_SOURCE_NOT_FOUND", str(ref))
        parents = payload.get("parent_refs") or []
        if level != "BR" and not parents:
            raise RuntimeError("RECOVERY_PARENT_REQUIRED", level)
        if level == "BR" and parents:
            raise RuntimeError("RECOVERY_PARENT_KIND_INVALID", "BR derives from source documents")
        expected = {"SR": "BR", "TR": "SR"}.get(level)
        for ref in parents:
            parent = state.by_id(str(ref))
            if parent is None or parent.fact_kind != kind or parent.payload.get("kind") != expected or parent.payload.get("scope_identity") != payload["scope_identity"]:
                raise RuntimeError("RECOVERY_PARENT_KIND_INVALID", str(ref))
        for ref in payload.get("asset_refs") or []:
            if not isinstance(ref, Mapping) or ref.get("kind") not in {"CODE", "API", "PAGE"}:
                raise RuntimeError("RECOVERY_ASSET_INVALID", "explicit CODE/API/PAGE references only")
            _text(ref.get("ref"), "asset_ref")
        _revision_guard(state, kind, payload, ("scope_identity", "artifact_id", "revision"))
    elif kind == "CURRENT_RELEASE_BINDING":
        validate_release_binding(payload)
        _revision_guard(state, kind, payload, ("binding_id", "revision"))
    elif kind == "CURRENT_RELEASE":
        for name in ("release_id", "project_id", "revision", "binding_ref", "sha256", "observed_at"):
            _text(payload.get(name), name)
        _sha(payload["sha256"])
        bound = state.by_id(payload["binding_ref"])
        if bound is None or bound.fact_kind != "CURRENT_RELEASE_BINDING":
            raise RuntimeError("RECOVERY_RELEASE_UNAPPROVED", "approved binding is required")
        binding = bound.payload
        if binding["expected_sha256"] != payload["sha256"] or binding["project_id"] != payload["project_id"] or binding["release_id"] != payload["release_id"]:
            raise RuntimeError("RECOVERY_RELEASE_BINDING_MISMATCH", "export must match approved project and exact bytes")
        _revision_guard(state, kind, payload, ("project_id", "release_id", "revision"))


def validate_release_binding(value: Mapping[str, Any], *, check_freshness: bool = False) -> dict[str, Any]:
    data = dict(value)
    _json(data)
    validate_secret_boundary(data)
    if data.get("adapter") != "APPROVED_EXPORT" or data.get("source_system") != "STARLINK":
        raise RuntimeError("RECOVERY_RELEASE_ADAPTER_INVALID", "supported adapter is STARLINK APPROVED_EXPORT")
    for name in ("binding_id", "revision", "project_id", "release_id", "approved_by", "approval_ref", "approved_at", "valid_until"):
        _text(data.get(name), name)
    _sha(data.get("expected_sha256"), "expected_sha256")
    approved = _time(data["approved_at"])
    expiry = _time(data["valid_until"])
    if expiry <= approved:
        raise RuntimeError("RECOVERY_RELEASE_EXPIRY_INVALID", "valid_until must follow approved_at")
    if check_freshness:
        now = datetime.now(timezone.utc)
        if approved > now or expiry <= now:
            raise RuntimeError("RECOVERY_RELEASE_BINDING_EXPIRED", "renew approval for this export")
    return data


def parse_document(path: str | Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    file = Path(path).expanduser().resolve()
    if not file.is_file() or file.stat().st_size > MAX_DOCUMENT_BYTES:
        raise RuntimeError("RECOVERY_DOCUMENT_UNAVAILABLE", "file missing or exceeds 20 MiB")
    raw = file.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest != _sha(expected_sha256):
        raise RuntimeError("RECOVERY_DOCUMENT_HASH_MISMATCH", file.name)
    suffix = file.suffix.lower()
    if suffix in {".txt", ".md", ".json"}:
        try:
            text = raw.decode("utf-8-sig")
            if suffix == ".json":
                parsed = json.loads(text)
                validate_secret_boundary(parsed)
                text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (UnicodeError, ValueError) as exc:
            raise RuntimeError("RECOVERY_DOCUMENT_INVALID", "valid UTF-8/JSON required") from exc
        parser = "python-stdlib:" + suffix[1:]
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                member = archive.getinfo("word/document.xml")
                if member.file_size > MAX_DOCUMENT_BYTES:
                    raise ValueError("expanded document exceeds size limit")
                root = ElementTree.fromstring(archive.read(member))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text = "\n".join("".join(n.text or "" for n in p.findall(".//w:t", ns)) for p in root.findall(".//w:p", ns))
            parser = "python-stdlib:docx-ooxml"
        except (KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise RuntimeError("RECOVERY_DOCUMENT_INVALID", "invalid DOCX package") from exc
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            binary = os.environ.get("PFC_PDFTOTEXT") or shutil.which("pdftotext")
            if not binary:
                raise RuntimeError("OPEN_EXTERNAL_PAYLOAD_REQUIRED", "PDF parser requires local pypdf or pdftotext")
            result = subprocess.run([binary, "-layout", str(file), "-"], capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError("RECOVERY_DOCUMENT_INVALID", "pdftotext rejected PDF")
            text = result.stdout.decode("utf-8", errors="strict")
            parser = "pdftotext:local"
        else:
            try:
                reader = PdfReader(io.BytesIO(raw))
                if reader.is_encrypted:
                    raise ValueError("encrypted PDF requires approved decrypted export")
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                parser = "pypdf:local"
            except Exception as exc:
                raise RuntimeError("RECOVERY_DOCUMENT_INVALID", "PDF extraction failed") from exc
    else:
        raise RuntimeError("RECOVERY_DOCUMENT_FORMAT_UNSUPPORTED", suffix)
    if not text.strip():
        raise RuntimeError("RECOVERY_DOCUMENT_TEXT_UNAVAILABLE", "scanned images require approved text export")
    if len(text) > MAX_TEXT_CHARS:
        raise RuntimeError("RECOVERY_DOCUMENT_TOO_LARGE", "split attachment into smaller source revisions")
    validate_secret_boundary(text)
    return {"sha256": digest, "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "format": suffix[1:], "parser": parser, "byte_size": len(raw), "locator": file.as_uri()}


class RecoveryIntakeService:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.g3 = G3TestingIntelligenceService(runtime)

    def import_document(self, mission_id: str, path: str | Path, source_id: str, *, source_kind: str = "REQUIREMENT",
                        revision: str = "1", expected_sha256: str | None = None) -> dict[str, Any]:
        parsed = parse_document(path, expected_sha256=expected_sha256)
        payload = {**parsed, "source_id": _text(source_id, "source_id"), "source_kind": source_kind,
                   "revision": str(revision), "semantic_analysis_status": "PENDING_G3_ANALYSIS"}
        state = self.g3.state(mission_id)
        validate_recovery_fact("SOURCE_DOCUMENT", payload, state)
        fact_id = "document:" + canonical_sha256({"source_id": source_id, "revision": str(revision)})[:32]
        existing = state.by_id(fact_id)
        if existing:
            return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "document": existing.to_dict(), "replayed": True}
        # Original attachment bytes are a cache governed by the Event fact's hash.
        cache = self.runtime.db_path.parent / "attachments" / (parsed["sha256"] + Path(path).suffix.lower())
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists() or hashlib.sha256(cache.read_bytes()).hexdigest() != parsed["sha256"]:
            source_bytes = Path(path).read_bytes()
            if hashlib.sha256(source_bytes).hexdigest() != parsed["sha256"]:
                raise RuntimeError("RECOVERY_DOCUMENT_CHANGED", "source changed during import; retry")
            cache.write_bytes(source_bytes)
        fact = self.g3._record(mission_id, "SOURCE_DOCUMENT", payload, provenance_refs=(parsed["locator"],), fact_id=fact_id)
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "document": fact, "replayed": False}

    @staticmethod
    def artifact_ref(scope_identity: str, artifact_id: str, revision: str) -> str:
        return "requirement-analysis:" + canonical_sha256({"scope": scope_identity, "id": artifact_id, "revision": str(revision)})[:32]

    def analyze_requirements(self, mission_id: str, scope_identity: str, artifacts: list[Mapping[str, Any]]) -> dict[str, Any]:
        scope = _text(scope_identity, "scope_identity")
        if not artifacts:
            raise RuntimeError("RECOVERY_ANALYSIS_EMPTY", "BR/SR/TR artifacts required")
        state = self.g3.state(mission_id)
        existing = list(state.by_kind("REQUIREMENT_ANALYSIS_ARTIFACT"))
        refs = {f.payload["artifact_id"]: f.fact_id for f in existing if f.payload["scope_identity"] == scope}
        prepared = []
        for item in artifacts:
            artifact_id = _text(item.get("artifact_id"), "artifact_id")
            revision = _text(str(item.get("revision", "1")), "revision")
            ref = self.artifact_ref(scope, artifact_id, revision)
            if any(x[0] == ref for x in prepared):
                raise RuntimeError("RECOVERY_ANALYSIS_DUPLICATE", artifact_id)
            refs[artifact_id] = ref
            prepared.append((ref, {**dict(item), "artifact_id": artifact_id, "revision": revision, "scope_identity": scope}))
        prepared.sort(key=lambda x: {"BR": 0, "SR": 1, "TR": 2}.get(x[1].get("kind"), 9))
        # Validate the complete graph before first write; simulate facts only for
        # validation. Persisted source/parent refs remain exact immutable IDs.
        from dataclasses import replace
        from aitest_runtime.g3.contracts import G3Fact
        simulated = state
        for ref, payload in prepared:
            payload["parent_refs"] = [refs.get(str(p), str(p)) for p in payload.get("parent_refs") or []]
            payload["asset_refs"] = list(payload.get("asset_refs") or [])
            payload["source_refs"] = list(payload.get("source_refs") or [])
            validate_recovery_fact("REQUIREMENT_ANALYSIS_ARTIFACT", payload, simulated)
            if simulated.by_id(ref) is None:
                dummy = G3Fact(ref, "REQUIREMENT_ANALYSIS_ARTIFACT", mission_id, payload, tuple(payload["source_refs"]),
                               "validation-only", "validation-only", 1, "validation-only")
                simulated = replace(simulated, facts=simulated.facts + (dummy,))
        results = []
        for ref, payload in prepared:
            results.append(self.g3._record(mission_id, "REQUIREMENT_ANALYSIS_ARTIFACT", payload,
                                           provenance_refs=tuple(payload["source_refs"] + payload["parent_refs"]), fact_id=ref))
        # G3's existing semantics service derives R3.1 obligations, provenance,
        # coverage gaps, and downstream G3 case/strategy references.
        all_current = self.current_artifacts(mission_id, scope)
        source_ids = {ref for artifact in all_current for ref in artifact["payload"]["source_refs"]}
        documents = {ref: self.g3.state(mission_id).by_id(ref) for ref in source_ids}
        semantics = {name: [] for name in SEMANTIC_FIELDS}
        semantics["source_refs"] = [{"source_id": ref, "source_kind": doc.payload["source_kind"], "revision": doc.payload["revision"],
                                     "locator": doc.payload["locator"], "source_digest": doc.payload["sha256"]} for ref, doc in sorted(documents.items())]
        for artifact in all_current:
            data = artifact["payload"]
            category = {"BR": "business_rules", "SR": "acceptance_criteria", "TR": "positive_paths"}[data["kind"]]
            semantics[category].append({"text": data["text"], "obligation_id": artifact["fact_id"],
                                        "source_id": data["source_refs"][0], "analysis_kind": data["kind"],
                                        "artifact_id": data["artifact_id"], "revision": data["revision"],
                                        "parent_refs": data["parent_refs"], "source_refs": data["source_refs"],
                                        "code_refs": [x["ref"] for x in data["asset_refs"]],
                                        "asset_refs": data["asset_refs"]})
        analysis = self.g3.analyze_requirement(mission_id, scope, semantics)
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "artifacts": results, "analysis": analysis,
                "r3_1_reference": analysis["r3_1_reference"], "actual_coverage": "NOT_ASSERTED"}

    def current_artifacts(self, mission_id: str, scope_identity: str | None = None) -> list[dict[str, Any]]:
        latest = {}
        for fact in self.g3.state(mission_id).by_kind("REQUIREMENT_ANALYSIS_ARTIFACT"):
            if scope_identity is None or fact.payload["scope_identity"] == scope_identity:
                latest[(fact.payload["scope_identity"], fact.payload["artifact_id"])] = fact.to_dict()
        return list(latest.values())

    def import_current_release(self, mission_id: str, path: str | Path, binding: Mapping[str, Any]) -> dict[str, Any]:
        approved = validate_release_binding(binding, check_freshness=True)
        file = Path(path).expanduser().resolve()
        if not file.is_file() or file.stat().st_size > MAX_DOCUMENT_BYTES:
            raise RuntimeError("RECOVERY_RELEASE_UNAVAILABLE", "export missing or too large")
        raw = file.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != approved["expected_sha256"]:
            raise RuntimeError("RECOVERY_RELEASE_HASH_MISMATCH", "export does not match approved hash")
        try:
            export = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("RECOVERY_RELEASE_INVALID", "UTF-8 JSON export required") from exc
        if not isinstance(export, dict):
            raise RuntimeError("RECOVERY_RELEASE_INVALID", "export must be an object")
        validate_secret_boundary(export)
        _json(export)
        for name in ("release_id", "project_id", "revision", "observed_at"):
            _text(export.get(name), name)
        _time(export["observed_at"])
        if export["project_id"] != approved["project_id"] or export["release_id"] != approved["release_id"]:
            raise RuntimeError("RECOVERY_RELEASE_BINDING_MISMATCH", "project/release differs from approval")
        for field in ("requirements", "repositories"):
            if not isinstance(export.get(field), list):
                raise RuntimeError("RECOVERY_RELEASE_INVALID", f"{field} must be an array, including empty when unknown")
        for requirement in export["requirements"]:
            if not isinstance(requirement, Mapping) or not requirement.get("requirement_id"):
                raise RuntimeError("RECOVERY_RELEASE_INVALID", "requirement_id required")
        binding_ref = "release-binding:" + canonical_sha256({"id": approved["binding_id"], "revision": approved["revision"]})[:32]
        state = self.g3.state(mission_id)
        validate_recovery_fact("CURRENT_RELEASE_BINDING", approved, state)
        payload = {**export, "sha256": digest, "binding_ref": binding_ref, "locator": file.as_uri(),
                   "adapter": "APPROVED_EXPORT", "bank_verification": "BANK_FIELD_VALIDATION_REQUIRED",
                   "live_starlink_connection": "NOT_ASSERTED"}
        _revision_guard(state, "CURRENT_RELEASE", payload, ("project_id", "release_id", "revision"))
        self.g3._record(mission_id, "CURRENT_RELEASE_BINDING", approved, provenance_refs=(approved["approval_ref"],), fact_id=binding_ref)
        ref = "current-release:" + canonical_sha256({"project": export["project_id"], "id": export["release_id"], "revision": export["revision"]})[:32]
        fact = self.g3._record(mission_id, "CURRENT_RELEASE", payload, provenance_refs=(binding_ref, file.as_uri()), fact_id=ref)
        return {"status": "READY", "truth_source": "R1_EVENT_STREAM", "current_release": fact,
                "bank_validation": "BANK_FIELD_VALIDATION_REQUIRED", "live_starlink": "BANK_BINDING_REQUIRED"}

    def work_context(self, mission_id: str, *, offset: int = 0, limit: int = 24) -> dict[str, Any]:
        offset, limit = max(0, int(offset)), min(100, max(1, int(limit)))
        state = self.g3.state(mission_id)
        artifacts = self.current_artifacts(mission_id)
        release = state.latest("CURRENT_RELEASE")
        status = "BANK_BINDING_REQUIRED"
        if release:
            binding = state.by_id(release.payload["binding_ref"])
            status = "READY" if binding and _time(binding.payload["valid_until"]) > datetime.now(timezone.utc) else "BANK_BINDING_REQUIRED"
        selected = artifacts[offset:offset + limit]
        return {"schema_version": SCHEMA, "truth_source": "R1_EVENT_STREAM", "mission_id": mission_id,
                "starlink_export_status": status, "live_starlink_status": "BANK_BINDING_REQUIRED",
                "current_release": None if release is None else {"fact_id": release.fact_id, **{k: release.payload[k] for k in ("release_id", "project_id", "revision", "sha256", "binding_ref")},
                                                                  **_release_index(release.payload, offset=offset, limit=limit)},
                "documents": [{"fact_id": f.fact_id, **{k: f.payload[k] for k in ("source_id", "source_kind", "revision", "sha256")}} for f in state.by_kind("SOURCE_DOCUMENT")][-100:],
                "artifacts": [{"fact_id": f["fact_id"], **{k: f["payload"][k] for k in ("artifact_id", "kind", "revision", "scope_identity", "parent_refs", "source_refs", "asset_refs")},
                               "text_excerpt": f["payload"]["text"][:600]} for f in selected],
                "artifact_count": len(artifacts), "next_offset": offset + limit if offset + limit < len(artifacts) else None,
                "g6": "HOLD", "actual_coverage": "NOT_ASSERTED"}

    def source(self, mission_id: str, fact_id: str, *, offset: int = 0, limit: int = 8000) -> dict[str, Any]:
        fact = self.g3.state(mission_id).by_id(fact_id)
        if fact is None or fact.fact_kind not in {"SOURCE_DOCUMENT", "REQUIREMENT_ANALYSIS_ARTIFACT", "CURRENT_RELEASE"}:
            raise RuntimeError("RECOVERY_SOURCE_NOT_FOUND", fact_id)
        payload = dict(fact.payload)
        text = payload.pop("text", None)
        offset, limit = max(0, int(offset)), min(32000, max(1, int(limit)))
        if fact.fact_kind == "CURRENT_RELEASE":
            index = _release_index(payload, offset=offset, limit=min(limit, 100))
            return {"fact_id": fact_id, "truth_source": "R1_EVENT_STREAM", "payload": {
                **{key: payload[key] for key in ("release_id", "project_id", "revision", "sha256", "binding_ref", "observed_at")}, **index},
                "text": None, "next_offset": index["next_offset"]}
        return {"fact_id": fact_id, "truth_source": "R1_EVENT_STREAM", "payload": payload, "text": text[offset:offset+limit] if text else None,
                "next_offset": offset + limit if text and offset + limit < len(text) else None}


def read_dispatch(workspace_root: str | Path, action: str, payload: Mapping[str, Any], *, runtime: Any = None) -> dict[str, Any]:
    """Read-only product seam; caller retains its existing role/binding checks."""
    if action not in {"intake_context", "read_intake_source", "binding_context"}:
        raise RuntimeError("RECOVERY_READ_ACTION_FORBIDDEN", action)
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    canonical = runtime or create_canonical_runtime(workspace_root)
    service = RecoveryIntakeService(canonical)
    data = dict(payload)
    mission = _text(data.pop("mission_id", None), "mission_id")
    if canonical.replay(mission).mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", mission)
    for key in ("task_id", "attempt_id", "session_id", "root_attempt_id", "logical_agent_id"):
        data.pop(key, None)
    if action == "binding_context":
        if data:
            raise RuntimeError("RECOVERY_READ_INPUT_INVALID", "binding_context takes only the canonical Mission/worker binding")
        from aitest_runtime.recovery_executors import safe_binding_context
        return {"truth_source": "R1_EVENT_STREAM", "mission_id": mission, "execution_binding": safe_binding_context(workspace_root),
                "current_release": service.work_context(mission, limit=24)["current_release"], "actual_coverage": "NOT_ASSERTED"}
    method = service.work_context if action == "intake_context" else service.source
    return method(mission, **data)


def dispatch(workspace_root: str | Path, action: str, payload: Mapping[str, Any], *, runtime: Any = None) -> dict[str, Any]:
    from aitest_runtime.canonical_runtime import create_canonical_runtime
    service = RecoveryIntakeService(runtime or create_canonical_runtime(workspace_root))
    data = dict(payload)
    mission = _text(data.pop("mission_id", None), "mission_id")
    if action == "import_current_release":
        if "binding" in data:
            raise RuntimeError("RECOVERY_RELEASE_UNAPPROVED", "tool input cannot self-approve; use the locally approved binding file")
        bindings = (Path(workspace_root).resolve() / "bindings").resolve()
        binding_path = Path(data.pop("binding_path", bindings / "starlink.json")).expanduser()
        if not binding_path.is_absolute():
            binding_path = Path(workspace_root) / binding_path
        binding_path = binding_path.resolve()
        if not binding_path.is_relative_to(bindings) or not binding_path.is_file():
            raise RuntimeError("RECOVERY_RELEASE_UNAPPROVED", "approved binding must exist inside workspace/bindings")
        data["binding"] = json.loads(binding_path.read_text(encoding="utf-8"))
    actions = {"import_document": service.import_document, "analyze_requirements": service.analyze_requirements,
               "import_current_release": service.import_current_release, "intake_context": service.work_context,
               "read_intake_source": service.source}
    if action not in actions:
        raise RuntimeError("RECOVERY_ACTION_UNSUPPORTED", action)
    return actions[action](mission, **data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--payload", required=True, help="Path to a UTF-8 JSON request")
    args = parser.parse_args()
    try:
        result = dispatch(args.workspace, args.action, json.loads(Path(args.payload).read_text(encoding="utf-8")))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
