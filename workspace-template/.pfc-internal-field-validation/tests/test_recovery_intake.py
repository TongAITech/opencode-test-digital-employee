"""Executable offline local fixtures; no assertion of bank integration success."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / "ai-test/runtime"))
from aitest_runtime.canonical_runtime import create_canonical_runtime, execute_core_command
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.recovery_intake import RecoveryIntakeService, parse_document, dispatch
from aitest_runtime.r2_2 import MissionIntakeOrchestrator


class RecoveryIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "state/runtime-spine.db"
        self.runtime = create_canonical_runtime(self.root, db_path=self.db)
        self.mission = "recovery-test"
        execute_core_command(self.runtime, command_type="CREATE_MISSION", mission_id=self.mission)
        self.service = RecoveryIntakeService(self.runtime)

    def document(self):
        path = self.root / "requirement.md"
        path.write_text("# Loan eligibility\nLoan amount must be positive.\n", encoding="utf-8")
        return self.service.import_document(self.mission, path, "loan-requirement")["document"]

    def graph(self, source):
        return [{"artifact_id": "BR-1", "kind": "BR", "revision": "1", "text": "Loan amount must be positive", "source_refs": [source]},
                {"artifact_id": "SR-1", "kind": "SR", "revision": "1", "text": "Reject amount zero with 422", "source_refs": [source], "parent_refs": ["BR-1"]},
                {"artifact_id": "TR-1", "kind": "TR", "revision": "1", "text": "POST amount zero and assert 422", "source_refs": [source], "parent_refs": ["SR-1"], "asset_refs": [{"kind": "API", "ref": "POST /loan"}]}]

    def test_document_and_graph_restart_r31_traceability(self):
        document = self.document()
        result = self.service.analyze_requirements(self.mission, "LOAN", self.graph(document["fact_id"]))
        seq = self.runtime.get_head_seq(self.mission)
        restarted = RecoveryIntakeService(create_canonical_runtime(self.root, db_path=self.db))
        context = restarted.work_context(self.mission)
        self.assertEqual(context["artifact_count"], 3)
        self.assertEqual({a["kind"] for a in context["artifacts"]}, {"BR", "SR", "TR"})
        duplicate = restarted.analyze_requirements(self.mission, "LOAN", self.graph(document["fact_id"]))
        self.assertEqual(self.runtime.get_head_seq(self.mission), seq)
        self.assertEqual(duplicate["r3_1_reference"], result["r3_1_reference"])
        state = self.runtime.replay_composed(self.mission).extension_state("r3_1_requirement_coverage_traceability")
        snapshot = state.snapshot(result["r3_1_reference"]["snapshot_id"])
        body = json.dumps(snapshot.to_dict())
        self.assertIn("DERIVED_FROM_REQUIREMENT_ANALYSIS", body)
        self.assertIn("RELATES_TO_API", body)
        self.assertIn(document["payload"]["sha256"], body)
        self.assertIn("UNCOVERED", body)
        self.assertEqual(self.service.source(self.mission, document["fact_id"])["text"], document["payload"]["text"])
        self.assertFalse((self.root / "ai-test/state/aitest.db").exists())

    def test_atomic_validation_and_revision_immutability(self):
        doc = self.document()
        graph = self.graph(doc["fact_id"])
        broken = [dict(a) for a in graph]
        broken[2]["parent_refs"] = ["BR-1"]
        seq = self.runtime.get_head_seq(self.mission)
        with self.assertRaisesRegex(Exception, "RECOVERY_PARENT_KIND_INVALID"):
            self.service.analyze_requirements(self.mission, "LOAN", broken)
        self.assertEqual(self.runtime.get_head_seq(self.mission), seq)
        self.service.analyze_requirements(self.mission, "LOAN", graph)
        graph[0]["text"] = "Changed without new revision"
        with self.assertRaisesRegex(Exception, "RECOVERY_REVISION_CONFLICT"):
            self.service.analyze_requirements(self.mission, "LOAN", graph)
        graph[0]["revision"] = "2"
        # Existing SR/TR keep their exact old parent lineage; updating those
        # records requires explicit new revisions rather than silent mutation.
        self.service.analyze_requirements(self.mission, "LOAN", [graph[0]])
        self.assertEqual(len(self.service.g3.state(self.mission).by_kind("REQUIREMENT_ANALYSIS_ARTIFACT")), 4)

    def test_docx_txt_json_formats_and_hash_guard(self):
        docx = self.root / "sst.docx"
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Loan amount validation</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(parse_document(docx)["text"], "Loan amount validation")
        self.service.import_document(self.mission, docx, "SST-1", source_kind="SST")
        for suffix, text in (("txt", "A rule"), ("json", '{"rule":"A rule"}')):
            path = self.root / ("requirement." + suffix)
            path.write_text(text, encoding="utf-8")
            self.assertTrue(parse_document(path)["text"])
        with self.assertRaisesRegex(Exception, "RECOVERY_DOCUMENT_HASH_MISMATCH"):
            parse_document(docx, expected_sha256="0" * 64)
        bad = self.root / "bad.json"
        bad.write_text("{invalid")
        with self.assertRaisesRegex(Exception, "RECOVERY_DOCUMENT_INVALID"):
            parse_document(bad)

    def test_raw_secrets_and_malformed_files_rejected_before_write(self):
        seq = self.runtime.get_head_seq(self.mission)
        path = self.root / "bad.txt"
        path.write_text("password=do-not-persist")
        with self.assertRaisesRegex(Exception, "SECRET_VALUE_NOT_ALLOWED"):
            self.service.import_document(self.mission, path, "bad")
        path = self.root / "bad.docx"
        path.write_bytes(b"not a zip")
        with self.assertRaisesRegex(Exception, "RECOVERY_DOCUMENT_INVALID"):
            self.service.import_document(self.mission, path, "bad")
        self.assertEqual(self.runtime.get_head_seq(self.mission), seq)

    def export(self):
        path = self.root / "starlink-export.json"
        path.write_text(json.dumps({"project_id": "LOAN", "release_id": "BLOAN1.9.4", "revision": "1", "observed_at": "2026-09-08T01:00:00Z", "requirements": [{"requirement_id": "R-1", "sst_ids": ["SST-1"]}], "repositories": []}), encoding="utf-8")
        binding = {"adapter": "APPROVED_EXPORT", "source_system": "STARLINK", "binding_id": "starlink-loan", "revision": "1", "project_id": "LOAN", "release_id": "BLOAN1.9.4", "approved_by": "local-test-fixture-human", "approval_ref": "fixture:approval", "approved_at": "2020-01-01T00:00:00Z", "valid_until": "2099-01-01T00:00:00Z", "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return path, binding

    def test_approved_release_and_restart(self):
        path, binding = self.export()
        result = self.service.import_current_release(self.mission, path, binding)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["bank_validation"], "BANK_FIELD_VALIDATION_REQUIRED")
        seq = self.runtime.get_head_seq(self.mission)
        self.service.import_current_release(self.mission, path, binding)
        self.assertEqual(self.runtime.get_head_seq(self.mission), seq)
        restarted = RecoveryIntakeService(create_canonical_runtime(self.root, db_path=self.db))
        self.assertEqual(restarted.work_context(self.mission)["current_release"]["release_id"], "BLOAN1.9.4")
        self.assertEqual(restarted.work_context(self.mission)["starlink_export_status"], "READY")

    def test_unapproved_expired_wrong_project_and_tampered_exports(self):
        path, binding = self.export()
        seq = self.runtime.get_head_seq(self.mission)
        for update in ({"approved_by": ""}, {"valid_until": "2021-01-01T00:00:00Z"}, {"project_id": "OTHER"}, {"expected_sha256": "0" * 64}):
            with self.assertRaises(Exception):
                self.service.import_current_release(self.mission, path, {**binding, **update})
        self.assertEqual(self.runtime.get_head_seq(self.mission), seq)

    def test_dispatch_requires_real_local_approval_file(self):
        path, binding = self.export()
        with self.assertRaisesRegex(Exception, "RECOVERY_RELEASE_UNAPPROVED"):
            dispatch(self.root, "import_current_release", {"mission_id": self.mission, "path": str(path), "binding": binding}, runtime=self.runtime)
        approval = self.root / "bindings/starlink.json"
        approval.parent.mkdir()
        approval.write_text(json.dumps(binding))
        result = dispatch(self.root, "import_current_release", {"mission_id": self.mission, "path": str(path)}, runtime=self.runtime)
        self.assertEqual(result["status"], "READY")
        with self.assertRaisesRegex(Exception, "RECOVERY_RELEASE_UNAPPROVED"):
            dispatch(self.root, "import_current_release", {"mission_id": self.mission, "path": str(path), "binding_path": str(path)}, runtime=self.runtime)

    def test_pdf_text_extraction_or_explicit_missing_payload(self):
        # A complete one-page PDF fixture with a valid cross-reference table.
        stream = b"BT /F1 12 Tf 72 720 Td (Loan amount rule) Tj ET"
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
        raw = b"%PDF-1.4\n"; offsets = []
        for i, obj in enumerate(objects, 1):
            offsets.append(len(raw)); raw += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
        xref = len(raw)
        raw += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(f"{pos:010d} 00000 n \n".encode() for pos in offsets)
        raw += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"
        path = self.root / "requirement.pdf"; path.write_bytes(raw)
        import importlib.util, shutil
        if importlib.util.find_spec("pypdf") or shutil.which("pdftotext"):
            self.assertIn("Loan amount rule", parse_document(path)["text"])
        else:
            with self.assertRaisesRegex(Exception, "OPEN_EXTERNAL_PAYLOAD_REQUIRED"):
                parse_document(path)

    def test_default_intake_unknown_facts_and_fresh_process_replay(self):
        request = {"intake_id": "fresh-default", "operation": "CREATE", "scope": {"mode": "EXPLICIT_SET", "project_id": "LOAN"}, "goal": {"intent": "测试 BLOAN1.9.4"}, "actor": {"type": "USER", "id": "fixture"},
                   "source": {"kind": "USER", "source_ref": "fixture:user-turn", "source_digest": "a" * 64, "observed_at": "2026-09-08T01:00:00Z", "valid_until": None, "source_precedence": None}}
        legacy = self.root / "legacy/aitest.db"
        with patch.dict(os.environ, {"AITEST_DB_PATH": str(legacy)}):
            result = MissionIntakeOrchestrator(self.runtime).intake(request)
            self.assertTrue(result.ok)
            self.assertEqual(result.resolution["status"], "BLOCKED")
            self.assertEqual(result.resolution["reason_code"], "NO_DECLARED_FACTS_OR_CAPABILITIES")
            seq = self.runtime.get_head_seq(result.mission_id)
            again = MissionIntakeOrchestrator(create_canonical_runtime(self.root, db_path=self.db)).intake(request)
            self.assertEqual(again.mission_id, result.mission_id)
            self.assertEqual(self.runtime.get_head_seq(result.mission_id), seq)
            self.assertFalse(legacy.exists())
        request_file = self.root / "request.json"
        request_file.write_text(json.dumps(request))
        code = "import json,sys; from aitest_runtime.canonical_runtime import create_canonical_runtime; from aitest_runtime.r2_2 import MissionIntakeOrchestrator; r=MissionIntakeOrchestrator(create_canonical_runtime(sys.argv[1],db_path=sys.argv[2])).intake(json.load(open(sys.argv[3]))); print(r.resolution['status'])"
        completed = subprocess.run([sys.executable, "-c", code, str(self.root), str(self.db), str(request_file)], env={**os.environ, "PYTHONPATH": str(WORKSPACE / "ai-test/runtime")}, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "BLOCKED")

    def test_canonical_resolution_preserves_frozen_secret_reference_boundary(self):
        from aitest_runtime.r2_1.canonical_store import CanonicalObservationSnapshotStore
        from aitest_runtime.r2_1 import RuntimeFactsResolver
        resolver = RuntimeFactsResolver(CanonicalObservationSnapshotStore(self.runtime, self.mission))
        request = {"resolution_id": "reference-check", "scope": {"type": "PROJECT", "project_id": "LOAN"},
                   "facts": [{"attribute": "approved_binding", "value": {"password": "secret://bank/credential"}, "source_ref": "fixture:binding"}]}
        result = resolver.resolve(request)
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(resolver.snapshot_store.read(result["snapshot_id"])["facts"][0]["value_or_reference"]["password"], "secret://bank/credential")
        request["facts"][0]["value"]["password"] = "raw-value"
        with self.assertRaisesRegex(Exception, "SECRET_VALUE_NOT_ALLOWED"):
            resolver.resolve(request)

    def test_g3_context_has_all_levels_and_bounds_large_text(self):
        doc = self.document()
        graph = self.graph(doc["fact_id"])
        graph[0]["text"] *= 1000
        self.service.analyze_requirements(self.mission, "LOAN", graph)
        context = self.service.g3.work_context(self.mission)
        self.assertEqual(context["recovery_intake"]["artifact_count"], 3)
        self.assertLessEqual(len(context["recovery_intake"]["artifacts"][0]["text_excerpt"]), 600)
        self.assertNotIn("SOURCE_DOCUMENT", context["latest"])


if __name__ == "__main__":
    unittest.main()
