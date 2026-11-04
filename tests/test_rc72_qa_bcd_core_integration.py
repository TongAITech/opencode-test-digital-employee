"""RC7.2 QA: A/B/C integration may not discard real production responsibilities.

Necessary product-wiring smoke guards; a GREEN source shape still needs
complete N6->N7->N8->N9->N10 runtime/evidence and in-bank Field Q3-Q9 proof.
This suite is deliberately RED against the unintegrated main HEAD.
"""
import ast
import inspect
import textwrap

from rc7_runtime.rc72_mission_factory import create_mission_driver
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from test_rc72_mission_factory import _setup


def _calls_of(method):
    return [n for n in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(method))))
            if isinstance(n, ast.Call)]


def _method_call(calls, name):
    return any(isinstance(n.func, ast.Attribute) and n.func.attr == name
               for n in calls)


def test_qa_ab_formal_n7_preserves_captain_fencing_and_a_professional_triage():
    """Prevent a successful merge from silently replacing A or B's N7 path."""
    assert hasattr(N7PipelineService, "_prepare_governed_item"), (
        "C07 P0: A/B integration dropped B's Captain-fenced preparation; "
        "a generic legacy preparation is not an autonomous AgentTeams dispatch"
    )
    prepare_calls = _calls_of(N7PipelineService._prepare_governed_item)
    assert _method_call(prepare_calls, "dispatch_etu"), (
        "C07 P0: N7 Case preparation does not use Captain-dispatched professional Worker"
    )
    assert any(isinstance(n.func, ast.Attribute)
               and n.func.attr == "prepare"
               and any(k.arg == "fenced_admission" for k in n.keywords)
               for n in prepare_calls), (
        "C07 P0: formal N7 must consume SAME signed Captain admission in N7 resource preparation"
    )
    run_calls = _calls_of(N7PipelineService.complete)
    assert _method_call(run_calls, "_prepare_governed_item"), (
        "C07 P0: formal N7.complete never consumes B's Captain-governed entry"
    )
    assert hasattr(N7PipelineService, "_diagnose_failure"), (
        "C04 P0: N7 failure cannot disappear after B's Captain merge"
    )
    diagnosis = textwrap.dedent(inspect.getsource(N7PipelineService._diagnose_failure))
    assert "NativeN9ProfessionalIntakeService" in diagnosis, (
        "C04 P0: A's real VALID_TEST_FAILURE -> N9 qualification route was lost"
    )
    assert _method_call(_calls_of(N7PipelineService._diagnose_failure), "queue_reproduction"), (
        "C04 P0: N9 professional intake is not called from real N7 failure path"
    )


def test_qa_ac_formal_n7_registers_signed_bsk_official_asset_dispatch(tmp_path):
    """A C09 merge must actually consume the BSK adapter under signed N7."""
    truth, options = _setup(tmp_path)
    options["tool_registry"]["journey_bsk"] = ("journey_bsk",)
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    adapters = driver.n7_pipeline.dispatch.adapters
    assert "journey_bsk" in adapters, (
        "C09 P0: product N7 has no journey_bsk signed tool route"
    )
    from rc7_runtime.rc72_journey_n7_adapter import SignedN7OfficialBSKAdapter
    assert type(adapters["journey_bsk"]) is SignedN7OfficialBSKAdapter, (
        "C09 P0: A must wire real SignedN7OfficialBSKAdapter, "
        "not the generic HTTP runner or an unapproved callback"
    )
    assert adapters["journey_bsk"].execution.truth is truth
    assert adapters["journey_bsk"].execution.release_id == options["release_id"]
    assert truth.store.path.read_bytes() == before, (
        "C09 product composition must not append fictitious PASS/field evidence"
    )
