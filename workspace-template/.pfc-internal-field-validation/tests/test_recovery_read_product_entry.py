"""Actual product read boundaries over canonical R1; no bank/model PASS claim.

Only the OpenCode session transport is a deterministic construction fixture.
Mission intake, plan routing, attempts, product dispatch, release/document
persistence and execution-binding filtering use the production implementation.
AITEST_TEST_RUNTIME_SOURCE can select the packaged workspace on Windows CI.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE_WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME_WORKSPACE = Path(os.environ.get("AITEST_TEST_RUNTIME_SOURCE") or SOURCE_WORKSPACE).resolve()
sys.path.insert(0, str(RUNTIME_WORKSPACE / "ai-test/runtime"))

from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.service import recommended_plan
from aitest_runtime.recovery_intake import RecoveryIntakeService
from aitest_runtime.r2_1 import canonical_store

# Import fixture helpers after the selected runtime is loaded, so staged-package
# validation never silently switches back to source-tree product modules.
sys.path.insert(0, str(Path(__file__).parent))
from test_g3_testing_intelligence_product_path import binding, finish, intake_request


class RecoveryReadProductEntryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="recovery-read-product-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "state/runtime-spine.db"
        self.legacy = self.root / "forbidden-legacy/aitest.db"
        environment = patch.dict(os.environ, {
            "AITEST_WORKSPACE_ROOT": str(self.root),
            "AITEST_RUNTIME_SPINE_DB": str(self.db),
            "PFC_LOCAL_STATE_ROOT": str(self.root),
            "AITEST_DB_PATH": str(self.legacy),
            "AITEST_HOST_SESSION_ID": "",
            "AITEST_HOST_MESSAGE_ID": "",
            "AITEST_G4_PROVIDER_FACTORY": "",
            "RECOVERY_READ_FIXTURE_ABSENT_ENV": "",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.runtime = create_canonical_runtime(self.root, db_path=self.db)
        self.orchestration = G21AutonomousOrchestrationService(
            self.runtime, self.root, session_provider=FakeOpenCodeSessionProvider(self.root))
        for name, value in (
            ("orchestration_service", lambda _root=None: self.orchestration),
            ("default_service", lambda _runtime, _root: self.orchestration),
        ):
            override = patch.object(product_entry, name, value)
            override.start()
            self.addCleanup(override.stop)
        request = intake_request()
        request.pop("resolution", None)
        request.update(intake_id="recovery-read-product", scope={
            "mode": "EXPLICIT_SET", "project_id": "LOCAL-READ", "version": "BLOAN1.9.4"})
        result = product_entry.orchestration_command("DIRECTOR", "start_test", {"request": request})
        self.assertEqual(result["status"], "PLANNING")
        self.mission = result["intake"]["intake"]["mission_id"]
        self.service = RecoveryIntakeService(self.runtime)
        source = self.root / "requirement.md"
        source.write_text("# Local fixture\nLoan amounts must be positive.\n", encoding="utf-8")
        self.document = self.service.import_document(self.mission, source, "LOAN-R1")["document"]
        self.repository = {"repository_id": "loan-code", "application_id": "loan",
                           "repository_path": "C:/approved/loan", "base_ref": "a" * 40, "head_ref": "b" * 40}
        export = self.root / "approved-release.json"
        export.write_text(json.dumps({
            "project_id": "LOCAL-READ", "release_id": "BLOAN1.9.4", "revision": "1",
            "observed_at": "2026-09-08T01:00:00Z",
            "requirements": [{"requirement_id": "LOAN-R1", "sst_ids": ["LOAN-SST1"]}],
            "repositories": [{**self.repository, "operator_notes": "withheld-operator-metadata"}],
        }), encoding="utf-8")
        approval = {"adapter": "APPROVED_EXPORT", "source_system": "STARLINK", "binding_id": "read-fixture",
                    "revision": "1", "project_id": "LOCAL-READ", "release_id": "BLOAN1.9.4",
                    "approved_by": "local-fixture-human", "approval_ref": "fixture:release-approval",
                    "approved_at": "2020-01-01T00:00:00Z", "valid_until": "2099-01-01T00:00:00Z",
                    "expected_sha256": hashlib.sha256(export.read_bytes()).hexdigest()}
        self.release = self.service.import_current_release(self.mission, export, approval)["current_release"]
        folder = self.root / "bindings"
        folder.mkdir()
        self.execution_config = {
            "approved": True, "approval_ref": "fixture:execution-approval",
            "allowed_origins": ["https://loan.test:8443", "https://user:password@withheld.test"],
            "allowed_methods": ["GET", "POST"], "auth_env_ref": "RECOVERY_READ_FIXTURE_ABSENT_ENV",
            "native_runners": {"project-pytest": {"argv": ["withheld-native-argument"], "cwd": "withheld-native-directory"}},
            "operator_notes": "withheld-operator-metadata",
        }
        self.execution_path = folder / "execution.json"
        self.execution_path.write_text(json.dumps(self.execution_config), encoding="utf-8")
        self.binding_bytes = self.execution_path.read_bytes()

    def assert_unchanged(self, seq):
        self.assertEqual(self.runtime.get_head_seq(self.mission), seq)
        self.assertEqual(self.execution_path.read_bytes(), self.binding_bytes)
        self.assertFalse(self.legacy.exists())

    def assert_read_context(self, command, role, bound):
        seq = self.runtime.get_head_seq(self.mission)
        context = command(role, "intake_context", bound)
        self.assertEqual(context["current_release"]["repositories"], [self.repository])
        self.assertEqual(context["current_release"]["release_id"], "BLOAN1.9.4")
        source = command(role, "read_intake_source", {**bound, "fact_id": self.release["fact_id"]})
        self.assertEqual(source["payload"]["repositories"], [self.repository])
        document = command(role, "read_intake_source", {**bound, "fact_id": self.document["fact_id"]})
        self.assertEqual(document["text"], self.document["payload"]["text"])
        scope = command(role, "binding_context", bound)
        self.assertEqual(scope["truth_source"], "R1_EVENT_STREAM")
        self.assertEqual(scope["actual_coverage"], "NOT_ASSERTED")
        execution = scope["execution_binding"]
        self.assertEqual(execution["authorized_scope"], {
            "origins": ["https://loan.test:8443"], "runner_ids": ["project-pytest"]})
        self.assertEqual(execution["allowed_methods"], ["GET", "POST"])
        self.assertEqual(execution["auth_state"], "AUTH_REQUIRED")
        self.assertTrue(execution["execution_requires_g4_admission"])
        text = json.dumps([context, source, document, scope])
        for withheld in ("withheld-operator-metadata", "withheld-native-argument", "withheld-native-directory",
                         "RECOVERY_READ_FIXTURE_ABSENT_ENV", "user:password", "withheld.test"):
            self.assertNotIn(withheld, text)
        self.assert_unchanged(seq)

    def assert_mutation_rejected(self, command, role, bound):
        seq = self.runtime.get_head_seq(self.mission)
        for action in ("import_document", "analyze_requirements", "import_current_release"):
            with self.subTest(role=role, mutation=action):
                result = command(role, action, {**bound, "path": str(self.execution_path)})
                self.assertEqual(result["status"], "HOLD")
                self.assertIn("ACTION_NOT_AUTHORIZED", result["reason"])
                self.assert_unchanged(seq)
        with self.assertRaisesRegex(Exception, "RECOVERY_READ_INPUT_INVALID"):
            command(role, "binding_context", {**bound, "action": "import_document", "path": str(self.execution_path)})
        self.assert_unchanged(seq)

    def assert_worker_guards(self, command, role, bound, prefix):
        seq = self.runtime.get_head_seq(self.mission)
        for action in ("intake_context", "read_intake_source", "binding_context"):
            extras = {"fact_id": self.release["fact_id"]} if action == "read_intake_source" else {}
            for key in ("task_id", "attempt_id", "session_id"):
                with self.subTest(role=role, action=action, omitted=key):
                    missing = {k: v for k, v in bound.items() if k != key}
                    with self.assertRaisesRegex(Exception, prefix + "_GOVERNED_WORKER_BINDING_REQUIRED"):
                        command(role, action, {**missing, **extras})
                    self.assert_unchanged(seq)
                with self.subTest(role=role, action=action, incorrect=key):
                    reason = "_SESSION_ROUTER_ROLE_BINDING_MISMATCH" if key == "task_id" else "_R2_5_ATTEMPT_SESSION_BINDING_MISMATCH"
                    with self.assertRaisesRegex(Exception, prefix + reason):
                        command(role, action, {**bound, **extras, key: "unbound-fixture-id"})
                    self.assert_unchanged(seq)
        with self.assertRaisesRegex(Exception, prefix + "_SESSION_ROUTER_ROLE_BINDING_MISMATCH"):
            command(role, "binding_context", {**bound, "mission_id": "unrelated-mission"})
        self.assert_unchanged(seq)

    def test_actual_product_read_context_role_binding_and_mutation_guards(self):
        planner_bound = {"mission_id": self.mission}
        self.assert_read_context(product_entry.orchestration_command, "PLANNER", planner_bound)
        self.assert_mutation_rejected(product_entry.orchestration_command, "PLANNER", planner_bound)

        code_task = recommended_plan("CHANGE_IMPACT_ANALYSIS")["tasks"][1]
        executor_task = {"task_key": "read-execution-binding", "intent": "Read approved execution origins and runner identities",
                         "acceptance_criteria": [{"id": "read-only", "description": "Use only authorized execution scope"}],
                         "routing": {"role": "EXECUTOR", "required_capabilities": ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
                                     "isolation_policy": "DEDICATED_TASK_SESSION", "parallelism_policy": "PARALLEL_SAFE"}}
        plan = product_entry.orchestration_command("PLANNER", "propose_plan", {
            "mission_id": self.mission, "proposal": {
                "objective": "Validate local product read-role boundaries",
                "tasks": [code_task, executor_task],
                "dependencies": [{"from": code_task["task_key"], "to": executor_task["task_key"]}],
            }})
        self.assertEqual(plan["status"], "PASS")
        self.assertEqual(plan["next"]["route"]["role"], "CODE_ANALYST")
        code_bound = binding(plan["next"])
        self.assert_read_context(product_entry.g3_command, "CODE_ANALYST", code_bound)
        self.assert_worker_guards(product_entry.g3_command, "CODE_ANALYST", code_bound, "G3")
        self.assert_mutation_rejected(product_entry.g3_command, "CODE_ANALYST", code_bound)
        seq = self.runtime.get_head_seq(self.mission)
        with self.assertRaisesRegex(Exception, "G4_SESSION_ROUTER_ROLE_BINDING_MISMATCH"):
            product_entry.g4_command("EXECUTOR", "binding_context", code_bound)
        self.assert_unchanged(seq)

        dispatched = finish(self.orchestration, code_bound, "Read-only local source context validated")["next"]
        self.assertEqual(dispatched["route"]["role"], "EXECUTOR")
        executor_bound = binding(dispatched)
        self.assert_read_context(product_entry.g4_command, "EXECUTOR", executor_bound)
        self.assert_worker_guards(product_entry.g4_command, "EXECUTOR", executor_bound, "G4")
        self.assert_mutation_rejected(product_entry.g4_command, "EXECUTOR", executor_bound)
        seq = self.runtime.get_head_seq(self.mission)
        with self.assertRaisesRegex(Exception, "G3_SESSION_ROUTER_ROLE_BINDING_MISMATCH"):
            product_entry.g3_command("CODE_ANALYST", "binding_context", executor_bound)
        self.assert_unchanged(seq)

        # G3/G4 product factories already re-open the database for every command;
        # recreate the Planner's canonical service too to verify process recovery.
        self.orchestration = G21AutonomousOrchestrationService(
            create_canonical_runtime(self.root, db_path=self.db), self.root,
            session_provider=self.orchestration.session_provider)
        self.assert_read_context(product_entry.orchestration_command, "PLANNER", planner_bound)

    def test_canonical_snapshot_lookup_closes_database_on_match_and_query_error(self):
        store = canonical_store.CanonicalObservationSnapshotStore(self.runtime, self.mission)
        resolution = next(store._records())
        original_connect = sqlite3.connect
        connections = []
        fail_query = False

        class ObservedConnection(sqlite3.Connection):
            def execute(self, *args, **kwargs):
                if fail_query:
                    raise sqlite3.OperationalError("fixture query failure")
                return super().execute(*args, **kwargs)

        def connect(*args, **kwargs):
            connection = original_connect(*args, factory=ObservedConnection, **kwargs)
            connections.append(connection)
            return connection

        with patch.object(canonical_store.sqlite3, "connect", connect):
            self.assertEqual(store.find_by_resolution(resolution["resolution_id"]), resolution)
            self.assertEqual(len(connections), 1)
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                connections[-1].execute("SELECT 1")
            fail_query = True
            with self.assertRaisesRegex(sqlite3.OperationalError, "fixture query failure"):
                store.find_by_resolution("any-resolution")
            self.assertEqual(len(connections), 2)
            fail_query = False
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                connections[-1].execute("SELECT 1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
