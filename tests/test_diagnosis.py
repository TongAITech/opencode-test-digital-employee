import unittest

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.diagnosis import (
    AttemptHistory,
    AttemptHistoryEntry,
    CATPolicy,
    CorrelationScope,
    DiagnosisContractError,
    DiagnosisRuntime,
    FailureContext,
    RecoveryEngine,
)


TARGET = "TARGET-BLOAN-PF1.2.0-FAT1"


def context(layer="L3", attempt="ATT-1", assertion_failed=False, remote=False, correlation=True):
    scope = None
    if correlation:
        scope = CorrelationScope(
            applications=("cfg-center", "cfg-data"),
            window_start=1000,
            window_end=1060,
            trace_id="trace-123",
        )
    return FailureContext(
        attempt_id=attempt,
        tc_id="TC-1",
        case_version=1,
        target_id=TARGET,
        layer=layer,
        execution_status="FAIL",
        preparation_verified=True,
        real_action_executed=True,
        assertion_failed=assertion_failed,
        execution_evidence_refs=(f"evidence://execution/{attempt}",),
        correlation=scope,
        remote_integration=remote,
    )


def classifier(failure_class):
    def classify(ctx, signals):
        return {
            "failure_class": failure_class,
            "classifier_ref": "classifier://deterministic/v1",
            "rationale": f"classified as {failure_class}",
            "evidence_refs": ["evidence://classifier/1"],
        }
    return classify


class DiagnosisRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
        self.broker = ToolCapabilityBroker()

    def _diagnostic_worker(self, attempt="ATT-1", allow_cat=True):
        worker = self.authority.issue_identity("FAILURE_DIAGNOSTIC", "DIAGNOSIS", None, 0, "diag-session")
        tools = ["cat"] if allow_cat else []
        lease = self.authority.issue_lease(
            worker.worker_id,
            f"attempt:{attempt}",
            ["failure_diagnosis", "recovery_decision", "evidence"],
            tools,
        )
        return worker, lease

    def _ready_cat(self, worker_id):
        self.broker.discover("cat", "https://cat.internal")
        self.broker.mark_executable("cat", "exec://cat")
        self.broker.register("cat", "mcp://cat")
        self.broker.bind_worker("cat", worker_id, visible=True, permitted=True)
        self.broker.record_probe("cat", success=True, tool_call_ref="toolcall://probe/cat", evidence_ref="evidence://probe/cat")
        self.broker.mark_target_ready("cat", TARGET, "evidence://target/cat")

    @staticmethod
    def cat_query(scope, ctx):
        return {
            "tool_call_ref": f"toolcall://cat/{ctx.attempt_id}",
            "evidence_ref": f"evidence://cat/{ctx.attempt_id}",
            "signals": {"error_type": "timeout", "trace_id": scope.trace_id},
        }

    def test_l3_requires_bounded_cat_before_diagnosis(self):
        ctx = context("L3")
        worker, lease = self._diagnostic_worker()
        self._ready_cat(worker.worker_id)
        runtime = DiagnosisRuntime(
            authority=self.authority,
            tool_broker=self.broker,
            classifier=classifier("TRANSIENT"),
            cat_query=self.cat_query,
        )
        result = runtime.diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id)
        self.assertTrue(result.cat_required)
        self.assertTrue(result.cat_queried)
        self.assertIn("evidence://cat/ATT-1", result.evidence_refs)

    def test_l5_also_requires_cat(self):
        ctx = context("L5")
        worker, lease = self._diagnostic_worker()
        self._ready_cat(worker.worker_id)
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TOOL"), cat_query=self.cat_query)
        self.assertTrue(runtime.diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id).cat_queried)

    def test_l1_cat_only_when_remote_integration(self):
        worker, lease = self._diagnostic_worker(allow_cat=False)
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TOOL"))
        local = runtime.diagnose(context=context("L1", correlation=False), worker_id=worker.worker_id, lease_id=lease.lease_id)
        self.assertFalse(local.cat_required)

        remote_ctx = context("L1", remote=True)
        worker2, lease2 = self._diagnostic_worker(attempt="ATT-1", allow_cat=True)
        self._ready_cat(worker2.worker_id)
        runtime2 = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TRANSIENT"), cat_query=self.cat_query)
        self.assertTrue(runtime2.diagnose(context=remote_ctx, worker_id=worker2.worker_id, lease_id=lease2.lease_id).cat_queried)

    def test_cat_missing_correlation_identifier_fails_closed(self):
        ctx = context("L3")
        ctx = FailureContext(**{**ctx.__dict__, "correlation": CorrelationScope(("cfg-data",), 1000, 1010)})
        worker, lease = self._diagnostic_worker()
        self._ready_cat(worker.worker_id)
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TRANSIENT"), cat_query=self.cat_query)
        with self.assertRaises(DiagnosisContractError) as e:
            runtime.diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id)
        self.assertEqual(str(e.exception), "CAT_CORRELATION_IDENTIFIER_REQUIRED")

    def test_cat_time_window_is_bounded(self):
        ctx = context("L3")
        ctx = FailureContext(**{**ctx.__dict__, "correlation": CorrelationScope(("cfg-data",), 0, 901, trace_id="t")})
        worker, lease = self._diagnostic_worker()
        self._ready_cat(worker.worker_id)
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TRANSIENT"), cat_query=self.cat_query, cat_policy=CATPolicy(max_window_seconds=900))
        with self.assertRaises(DiagnosisContractError) as e:
            runtime.diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id)
        self.assertEqual(str(e.exception), "CAT_TIME_WINDOW_TOO_WIDE")

    def test_cat_not_ready_blocks_before_query(self):
        calls = []
        worker, lease = self._diagnostic_worker()
        runtime = DiagnosisRuntime(
            authority=self.authority,
            tool_broker=self.broker,
            classifier=classifier("TRANSIENT"),
            cat_query=lambda scope, ctx: calls.append(True),
        )
        with self.assertRaises(DiagnosisContractError) as e:
            runtime.diagnose(context=context("L3"), worker_id=worker.worker_id, lease_id=lease.lease_id)
        self.assertIn("CAT_TOOL_NOT_READY", str(e.exception))
        self.assertEqual(calls, [])

    def test_wrong_role_cannot_diagnose(self):
        worker = self.authority.issue_identity("L3_EXECUTE", "EXECUTION", "L3", 0, "s")
        lease = self.authority.issue_lease(worker.worker_id, "attempt:ATT-1", ["evidence"], ["cat"])
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TRANSIENT"), cat_query=self.cat_query)
        with self.assertRaises(DiagnosisContractError) as e:
            runtime.diagnose(context=context("L3"), worker_id=worker.worker_id, lease_id=lease.lease_id)
        self.assertEqual(str(e.exception), "FAILURE_DIAGNOSTIC_ROLE_REQUIRED")

    def test_valid_product_assertion_failure_cannot_be_relabeled_transient(self):
        worker, lease = self._diagnostic_worker()
        self._ready_cat(worker.worker_id)
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TRANSIENT"), cat_query=self.cat_query)
        with self.assertRaises(DiagnosisContractError) as e:
            runtime.diagnose(context=context("L3", assertion_failed=True), worker_id=worker.worker_id, lease_id=lease.lease_id)
        self.assertEqual(str(e.exception), "VALID_PRODUCT_ASSERTION_FAILURE_MUST_BE_PRODUCT")

    def test_product_failure_is_terminal_and_never_retried_or_reprepared(self):
        ctx = context("L3", assertion_failed=True)
        worker, lease = self._diagnostic_worker()
        self._ready_cat(worker.worker_id)
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("PRODUCT"), cat_query=self.cat_query)
        diagnosis = runtime.diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id)
        history = AttemptHistory()
        history.append(AttemptHistoryEntry("ATT-1", None, "TC-1", 1, TARGET, "L3", "FAIL", ctx.execution_evidence_refs, 1000))
        decision = RecoveryEngine(history).decide(ctx, diagnosis)
        self.assertEqual(decision.action, "PRODUCT_DEFECT")
        self.assertTrue(decision.terminal)
        self.assertFalse(decision.retry_allowed)
        self.assertFalse(decision.reprepare_allowed)
        self.assertIsNone(decision.next_attempt_id)

    def test_transient_retry_is_bounded_and_attempt_history_is_append_only(self):
        ctx = context("L2", correlation=False)
        worker, lease = self._diagnostic_worker(allow_cat=False)
        runtime = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TRANSIENT"))
        diagnosis = runtime.diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id)
        history = AttemptHistory()
        first = AttemptHistoryEntry("ATT-1", None, "TC-1", 1, TARGET, "L2", "FAIL", ctx.execution_evidence_refs, 1000)
        history.append(first)
        engine = RecoveryEngine(history, max_transient_retries=1)
        decision = engine.decide(ctx, diagnosis)
        self.assertEqual(decision.action, "RETRY_SAME_STEP")
        self.assertTrue(decision.retry_allowed)
        second = engine.record_successor(decision, first)
        self.assertEqual(second.parent_attempt_id, "ATT-1")
        with self.assertRaises(DiagnosisContractError):
            history.append(AttemptHistoryEntry("ATT-1", None, "TC-1", 1, TARGET, "L2", "PASS", (), 1001))

        ctx2 = context("L2", attempt=second.attempt_id, correlation=False)
        worker2, lease2 = self._diagnostic_worker(attempt=second.attempt_id, allow_cat=False)
        diag2 = DiagnosisRuntime(authority=self.authority, tool_broker=self.broker, classifier=classifier("TRANSIENT")).diagnose(context=ctx2, worker_id=worker2.worker_id, lease_id=lease2.lease_id)
        exhausted = engine.decide(ctx2, diag2)
        self.assertEqual(exhausted.action, "RETRY_BUDGET_EXHAUSTED")
        self.assertFalse(exhausted.retry_allowed)

    def test_semantic_failures_route_to_distinct_recovery_actions(self):
        expected = {
            "DATA": ("RESEARCH_OR_REBUILD_DATA", True),
            "PRECONDITION": ("RECONSTRUCT_PRECONDITION", True),
            "AUTH": ("REAUTH", True),
            "TOOL": ("REPAIR_TOOL_BINDING", False),
            "ROUTE": ("RECONCILE_ROUTE_BINDING", False),
            "ENVIRONMENT": ("REQUALIFY_TARGET", False),
            "DESIGN": ("REOPEN_DESIGN", False),
            "UNKNOWN": ("BLOCKED_DIAGNOSIS", False),
        }
        for failure_class, (action, reprepare) in expected.items():
            with self.subTest(failure_class=failure_class):
                authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
                broker = ToolCapabilityBroker()
                worker = authority.issue_identity("FAILURE_DIAGNOSTIC", "DIAGNOSIS", None, 0, "s")
                lease = authority.issue_lease(worker.worker_id, "attempt:ATT-1", ["failure_diagnosis", "recovery_decision", "evidence"], [])
                ctx = context("L2", correlation=False)
                diag = DiagnosisRuntime(authority=authority, tool_broker=broker, classifier=classifier(failure_class)).diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id)
                history = AttemptHistory()
                history.append(AttemptHistoryEntry("ATT-1", None, "TC-1", 1, TARGET, "L2", "FAIL", ctx.execution_evidence_refs, 1000))
                decision = RecoveryEngine(history).decide(ctx, diag)
                self.assertEqual(decision.action, action)
                self.assertEqual(decision.reprepare_allowed, reprepare)
                self.assertFalse(decision.retry_allowed)


if __name__ == "__main__":
    unittest.main()
