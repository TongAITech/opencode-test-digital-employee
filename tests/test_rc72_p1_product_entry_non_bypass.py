"""Second-round formal product-entry guards; never claim Field approval."""
import ast
import inspect
import textwrap

from rc7_runtime.rc72_release_driver import ReleaseBatchDriver
from rc7_runtime.rc72_mission_factory import create_mission_driver
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService
from rc7_runtime.rc72_native_coverage_rerun import NativeCoverageRerunService
from test_rc72_mission_factory import _setup


def test_n9_initial_active_run_uses_professional_gate_and_cannot_skip_original_defect(tmp_path):
    """N9 READY must not take a weaker route than REVIEW_PENDING or cold replay."""
    src = textwrap.dedent(inspect.getsource(ReleaseBatchDriver.run))
    tree = ast.parse(src)
    candidates = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.BoolOp):
            continue
        if not any(isinstance(term, ast.Constant) and term.value == "N9_DEFECT"
                   for term in ast.walk(node.test)):
            continue
        candidates.append(node)
    assert len(candidates) == 1
    body = candidates[0].body
    calls = [term for statement in body for term in ast.walk(statement)
             if isinstance(term, ast.Call)]
    # No unapproved direct accepted-scope N9 call at the active product entry.
    assert any(isinstance(call.func, ast.Attribute)
               and call.func.attr == "_complete_gate"
               and isinstance(call.func.value, ast.Name)
               and call.func.value.id == "self"
               for call in calls)
    assert not any(isinstance(call.func, ast.Attribute)
                   and call.func.attr == "complete"
                   and isinstance(call.func.value, ast.Attribute)
                   and call.func.value.attr == "n9_pipeline"
                   for call in calls)


def test_native_factory_owns_n8_n10_recovery_and_fresh_coverage_rerun_without_r1_pass(tmp_path):
    truth, options = _setup(tmp_path)
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    assert driver.n8_pipeline.n7 is driver.n7_pipeline
    assert driver.n8_pipeline.diagnosis is driver.n7_pipeline.diagnosis
    n10 = driver.n10_pipeline
    assert isinstance(n10.repair, NativeCoverageRepairService)
    assert isinstance(n10.rerun, NativeCoverageRerunService)
    assert n10.rerun.repair is n10.repair
    assert n10.repair.diagnosis is n10.diagnosis
    assert truth.store.path.read_bytes() == before
    assert not truth.query("rc72_node_gate", node_type="N10_RELEASE_CONVERGENCE")
