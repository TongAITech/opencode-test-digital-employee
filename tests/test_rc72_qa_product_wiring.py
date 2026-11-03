"""QA admission guard for the real production factory (not a service fixture).

A product cannot claim C05/C08 while a formally composed N10 cannot drive
native repair and fresh N7/Libra. This intentionally fails on the audited
7efb3c8 baseline and must be fixed in A-owned production composition.
"""
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService
from rc7_runtime.rc72_native_coverage_rerun import NativeCoverageRerunService
from test_rc72_mission_factory import _setup
from rc7_runtime.rc72_mission_factory import create_mission_driver


def test_qa_formal_factory_wires_coverage_repair_and_fresh_n7_rerun(tmp_path):
    truth, options = _setup(tmp_path)
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    controller = driver.n10_pipeline
    assert isinstance(controller.repair, NativeCoverageRepairService), (
        'P0: native factory omits the N10 repair provider; standalone component tests are not product admission')
    assert isinstance(controller.rerun, NativeCoverageRerunService), (
        'P0: native factory omits the N10 fresh N7 rerun provider; no formal repair convergence')
    assert controller.rerun.repair is controller.repair
    assert controller.repair.diagnosis is controller.diagnosis
    assert truth.store.path.read_bytes() == before



def test_qa_release_driver_has_an_owned_non_bypass_n8_product_execution_route():
    """Necessary source seam only; NOT a sufficient end-to-end N8 admission.

    The current product driver explicitly *skips* N8 for accepted N7 results,
    but an N7 failure needs an owned service route, not a HOLD/default fallthrough.
    This intentionally remains RED until production supplies that route.
    """
    import ast
    import inspect
    import textwrap
    from rc7_runtime.rc72_release_driver import ReleaseBatchDriver

    tree = ast.parse(textwrap.dedent(inspect.getsource(ReleaseBatchDriver.run)))
    owners = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not any(isinstance(k, ast.Constant) and k.value == "N8_DIAGNOSIS_RECOVERY"
                   for k in ast.walk(node.test)):
            continue
        # Exclude the historical accepted-N7 bypass, which merely continues,
        # and the N8-filtering branch, which removes it from pending work.
        body_calls = [k for stmt in node.body for k in ast.walk(stmt)
                      if isinstance(k, ast.Call)]
        if any(isinstance(call.func, ast.Attribute)
               and call.func.attr in {"complete", "run", "dispatch", "resume", "reconcile"}
               for call in body_calls):
            owners.append(node)
    assert owners, (
        "P0: ReleaseBatchDriver.run lacks an owned non-bypass N8 execution/recovery "
        "branch; N8 failure must not end as NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED"
    )



def test_qa_product_driver_cannot_unconditionally_hold_after_all_n1_to_n10_gates_pass():
    """Necessary formal admission: terminal N10 must reach an actual outcome.

    The released RC7.2 Mission must not call a fully audited N1-N10 chain
    permanently HOLD just because no terminal routing was implemented.
    This is a source-level necessary gate; actual final R1 and Field Q7/Q9
    evidence remain separately mandatory.
    """
    import ast
    import inspect
    import textwrap
    from rc7_runtime.rc72_release_driver import ReleaseBatchDriver

    tree = ast.parse(textwrap.dedent(inspect.getsource(ReleaseBatchDriver.run)))
    stalled = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not (isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
                and isinstance(node.test.operand, ast.Name)
                and node.test.operand.id == "pending"):
            continue
        for branch in node.body:
            if not isinstance(branch, ast.Return):
                continue
            if any(isinstance(term, ast.Constant)
                   and term.value == "RELEASE_CONVERGENCE_AUDIT_REQUIRED"
                   for term in ast.walk(branch.value)):
                stalled.append(branch)
    assert not stalled, (
        "P0: after all formal N1-N10 PASS, ReleaseBatchDriver.run still "
        "returns unconditional RELEASE_CONVERGENCE_AUDIT_REQUIRED HOLD "
        "rather than deriving a terminal outcome from signed R1 N10 Gate"
    )



def test_qa_formal_factory_owns_non_bypass_n8_service_without_side_effects(tmp_path):
    """The real factory must not strand a native N8 service as an orphan module.

    Checks only the product ownership/scope necessary to dispatch formal
    failures. Native N7->N8 back-edge, classified root cause, fresh retry,
    no duplicate business I/O and cold resume still require runtime evidence.
    """
    truth, options = _setup(tmp_path)
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    n8 = getattr(driver, "n8_pipeline", None)
    assert n8 is not None, (
        "C03 P0: formal create_mission_driver does not own an N8 "
        "non-bypass recovery service; module existence is not integration"
    )
    from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
    assert type(n8) is NativeN8ProductRecoveryService, (
        "C03 formal N8 must be the actual native product recovery service, "
        "not a mock callback or a generic PASS-shaped substitute"
    )
    assert n8.truth is truth, "C03 N8 truth must be the canonical Mission R1"
    assert n8.n7 is driver.n7_pipeline, "C03 N8 must use the exact formal N7"
    assert n8.release_id == options["release_id"], "C03 N8 cross-release binding"
    assert n8.source_commit == options["source_commit"], "C03 N8 cross-source binding"
    assert getattr(n8, "diagnosis", None) is driver.n7_pipeline.diagnosis, (
        "C03 N8 must not silently substitute its diagnosis evidence"
    )
    assert n8.boundary.diagnosis is n8.diagnosis
    assert n8.continuation.diagnosis is n8.diagnosis
    assert truth.store.path.read_bytes() == before, (
        "C03 factory wiring must not generate a synthetic PASS or mutate R1"
    )
