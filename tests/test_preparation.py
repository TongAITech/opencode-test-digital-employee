import unittest

from rc6_runtime.preparation import (
    AttemptBindingStore,
    PreparationContractError,
    PreparationRecoveryEngine,
    PreparationRuntime,
    PreparationSpecParser,
)


def frozen_case():
    return {
        "tc_id": "TC-L3-001",
        "case_version": 2,
        "layer": "L3",
        "status": "FROZEN",
        "preconditions": [
            {"id": "PRE-ENV", "type": "ENVIRONMENT", "requirement": "FAT1 target is qualified"},
            {"id": "PRE-AUTH", "type": "AUTH", "requirement": "4A session is valid"},
        ],
        "test_data": {
            "initial_state": [
                {"id": "STATE-LOAN", "selectors": {"loan_status": "DRAFT"}, "allowed_strategies": ["REUSE_EXISTING", "API_CREATE", "DB_CREATE"]}
            ],
            "input_data": [
                {"id": "INPUT-AMOUNT", "selectors": {"amount": 1000}, "allowed_strategies": ["DERIVE"]}
            ],
            "cleanup_policy": {"mode": "ROLLBACK", "scope": "created-only"},
        },
        "oracle": {"checks": [{"type": "API_RESPONSE", "evidence_ref": "evidence://oracle/api"}]},
    }


def resolver(spec, context):
    return {"success": True, "evidence_ref": f"evidence://pre/{spec['id']}"}


def verifier(requirement, binding, context):
    return {"success": True, "evidence_ref": f"evidence://verify/{requirement['id']}"}


class ParserTests(unittest.TestCase):
    def test_only_frozen_case_can_prepare(self):
        case = frozen_case()
        case["status"] = "CANDIDATE"
        with self.assertRaises(PreparationContractError) as ctx:
            PreparationSpecParser().parse(case)
        self.assertEqual(str(ctx.exception), "CASE_MUST_BE_FROZEN_BEFORE_PREPARATION")

    def test_initial_state_and_input_data_remain_separate(self):
        plan = PreparationSpecParser().parse(frozen_case())
        self.assertEqual([x["id"] for x in plan.initial_state_requirements], ["STATE-LOAN"])
        self.assertEqual([x["id"] for x in plan.input_data_requirements], ["INPUT-AMOUNT"])
        self.assertEqual(plan.cleanup_policy["mode"], "ROLLBACK")
        self.assertTrue(plan.oracle_snapshot)


class PreparationRuntimeTests(unittest.TestCase):
    def test_search_reuse_precedes_construction(self):
        calls = []

        def reuse(req, ctx):
            calls.append("REUSE_EXISTING")
            return {
                "success": True,
                "binding": {"loan_id": "L100"},
                "tool_call_ref": "toolcall://db/search/L100",
                "evidence_ref": "evidence://db/search/L100",
            }

        def api(req, ctx):
            calls.append("API_CREATE")
            return {
                "success": True,
                "binding": {"loan_id": "L200"},
                "tool_call_ref": "toolcall://api/create/L200",
                "evidence_ref": "evidence://api/create/L200",
            }

        def derive(req, ctx):
            calls.append("DERIVE")
            return {
                "success": True,
                "binding": {"amount": 1000},
                "tool_call_ref": "toolcall://derive/amount",
                "evidence_ref": "evidence://derive/amount",
            }

        runtime = PreparationRuntime(
            precondition_resolvers={"ENVIRONMENT": resolver, "AUTH": resolver},
            data_strategies={"REUSE_EXISTING": reuse, "API_CREATE": api, "DERIVE": derive},
            data_verifier=verifier,
        )
        prepared = runtime.prepare(case=frozen_case(), attempt_id="ATT-1", target_id="TARGET-1")
        self.assertEqual(prepared.status, "PREPARED")
        self.assertEqual(prepared.initial_state_bindings["STATE-LOAN"]["loan_id"], "L100")
        self.assertEqual(prepared.input_data_bindings["INPUT-AMOUNT"]["amount"], 1000)
        self.assertEqual(calls, ["REUSE_EXISTING", "DERIVE"])
        self.assertEqual(prepared.cleanup_policy["mode"], "ROLLBACK")

    def test_failed_search_can_fall_through_to_api_create_then_verify(self):
        calls = []

        def reuse(req, ctx):
            calls.append("REUSE_EXISTING")
            return {"success": False, "reason": "not found"}

        def api(req, ctx):
            calls.append("API_CREATE")
            return {
                "success": True,
                "binding": {"loan_id": "L201"},
                "tool_call_ref": "toolcall://api/create/L201",
                "evidence_ref": "evidence://api/create/L201",
            }

        def derive(req, ctx):
            calls.append("DERIVE")
            return {
                "success": True,
                "binding": {"amount": 1000},
                "tool_call_ref": "toolcall://derive/amount",
                "evidence_ref": "evidence://derive/amount",
            }

        runtime = PreparationRuntime(
            precondition_resolvers={"ENVIRONMENT": resolver, "AUTH": resolver},
            data_strategies={"REUSE_EXISTING": reuse, "API_CREATE": api, "DERIVE": derive},
            data_verifier=verifier,
        )
        prepared = runtime.prepare(case=frozen_case(), attempt_id="ATT-2", target_id="TARGET-1")
        self.assertEqual(prepared.initial_state_bindings["STATE-LOAN"]["loan_id"], "L201")
        self.assertEqual(calls[:2], ["REUSE_EXISTING", "API_CREATE"])

    def test_db_create_requires_human_gate(self):
        case = frozen_case()
        case["test_data"]["initial_state"][0]["allowed_strategies"] = ["DB_CREATE"]

        def db_create(req, ctx):
            return {
                "success": True,
                "binding": {"loan_id": "L300"},
                "tool_call_ref": "toolcall://db/create/L300",
                "evidence_ref": "evidence://db/create/L300",
            }

        runtime = PreparationRuntime(
            precondition_resolvers={"ENVIRONMENT": resolver, "AUTH": resolver},
            data_strategies={"DB_CREATE": db_create, "DERIVE": lambda r, c: {"success": True, "binding": {"amount": 1000}, "tool_call_ref": "tc", "evidence_ref": "ev"}},
            data_verifier=verifier,
        )
        with self.assertRaises(PreparationContractError) as ctx:
            runtime.prepare(case=case, attempt_id="ATT-3", target_id="TARGET-1")
        self.assertIn("HUMAN_GATE_REQUIRED:STATE-LOAN:DB_CREATE", str(ctx.exception))

    def test_db_create_with_approved_gate_is_bound_with_gate_evidence(self):
        case = frozen_case()
        case["test_data"]["initial_state"][0]["allowed_strategies"] = ["DB_CREATE"]

        def db_create(req, ctx):
            return {
                "success": True,
                "binding": {"loan_id": "L301"},
                "tool_call_ref": "toolcall://db/create/L301",
                "evidence_ref": "evidence://db/create/L301",
            }

        runtime = PreparationRuntime(
            precondition_resolvers={"ENVIRONMENT": resolver, "AUTH": resolver},
            data_strategies={
                "DB_CREATE": db_create,
                "DERIVE": lambda r, c: {"success": True, "binding": {"amount": 1000}, "tool_call_ref": "toolcall://derive", "evidence_ref": "evidence://derive"},
            },
            data_verifier=verifier,
            human_gate=lambda action: "human-gate://approved/123",
        )
        prepared = runtime.prepare(case=case, attempt_id="ATT-4", target_id="TARGET-1")
        self.assertIn("human-gate://approved/123", prepared.binding_evidence)

    def test_verification_failure_blocks_binding(self):
        def bad_verifier(requirement, binding, context):
            return {"success": False, "evidence_ref": "evidence://verify/fail"}

        runtime = PreparationRuntime(
            precondition_resolvers={"ENVIRONMENT": resolver, "AUTH": resolver},
            data_strategies={
                "REUSE_EXISTING": lambda r, c: {"success": True, "binding": {"loan_id": "bad"}, "tool_call_ref": "tc", "evidence_ref": "ev"},
                "DERIVE": lambda r, c: {"success": True, "binding": {"amount": 1000}, "tool_call_ref": "tc2", "evidence_ref": "ev2"},
            },
            data_verifier=bad_verifier,
        )
        with self.assertRaises(PreparationContractError) as ctx:
            runtime.prepare(case=frozen_case(), attempt_id="ATT-5", target_id="TARGET-1")
        self.assertIn("DATA_VERIFICATION_FAILED", str(ctx.exception))
        self.assertIsNone(runtime.binding_store.get("ATT-5"))

    def test_attempt_binding_is_immutable_and_idempotent(self):
        store = AttemptBindingStore()
        runtime = PreparationRuntime(
            precondition_resolvers={"ENVIRONMENT": resolver, "AUTH": resolver},
            data_strategies={
                "REUSE_EXISTING": lambda r, c: {"success": True, "binding": {"loan_id": "L1"}, "tool_call_ref": "tc", "evidence_ref": "ev"},
                "DERIVE": lambda r, c: {"success": True, "binding": {"amount": 1000}, "tool_call_ref": "tc2", "evidence_ref": "ev2"},
            },
            data_verifier=verifier,
            binding_store=store,
        )
        first = runtime.prepare(case=frozen_case(), attempt_id="ATT-6", target_id="TARGET-1")
        second = runtime.prepare(case=frozen_case(), attempt_id="ATT-6", target_id="TARGET-1")
        self.assertEqual(first, second)
        changed = frozen_case()
        changed["case_version"] = 3
        with self.assertRaises(PreparationContractError):
            runtime.prepare(case=changed, attempt_id="ATT-6", target_id="TARGET-1")

    def test_preconditions_are_verified_before_data_strategy(self):
        order = []

        def ordered_resolver(spec, ctx):
            order.append(spec["id"])
            return {"success": True, "evidence_ref": f"evidence://{spec['id']}"}

        def reuse(req, ctx):
            order.append("DATA")
            return {"success": True, "binding": {"loan_id": "L1"}, "tool_call_ref": "tc", "evidence_ref": "ev"}

        runtime = PreparationRuntime(
            precondition_resolvers={"ENVIRONMENT": ordered_resolver, "AUTH": ordered_resolver},
            data_strategies={
                "REUSE_EXISTING": reuse,
                "DERIVE": lambda r, c: {"success": True, "binding": {"amount": 1000}, "tool_call_ref": "tc2", "evidence_ref": "ev2"},
            },
            data_verifier=verifier,
        )
        runtime.prepare(case=frozen_case(), attempt_id="ATT-7", target_id="TARGET-1")
        self.assertEqual(order[:3], ["PRE-ENV", "PRE-AUTH", "DATA"])


class RecoveryTests(unittest.TestCase):
    def test_valid_product_failure_cannot_be_reprepared_or_retried_to_green(self):
        decision = PreparationRecoveryEngine().decide(
            "PRODUCT", preparation_verified=True, real_action_executed=True, assertion_failed=True
        )
        self.assertEqual(decision.action, "PRODUCT_DEFECT")
        self.assertFalse(decision.retry_allowed)
        self.assertFalse(decision.reprepare_allowed)
        self.assertTrue(decision.terminal_product_failure)

    def test_data_failure_allows_reprepare_but_not_same_step_retry(self):
        decision = PreparationRecoveryEngine().decide(
            "DATA", preparation_verified=False, real_action_executed=False, assertion_failed=False
        )
        self.assertEqual(decision.action, "RESEARCH_OR_REBUILD_DATA")
        self.assertTrue(decision.reprepare_allowed)
        self.assertFalse(decision.retry_allowed)

    def test_transient_failure_allows_same_step_retry_without_reprepare(self):
        decision = PreparationRecoveryEngine().decide(
            "TRANSIENT", preparation_verified=True, real_action_executed=False, assertion_failed=False
        )
        self.assertEqual(decision.action, "RETRY_SAME_STEP")
        self.assertTrue(decision.retry_allowed)
        self.assertFalse(decision.reprepare_allowed)


if __name__ == "__main__":
    unittest.main()
