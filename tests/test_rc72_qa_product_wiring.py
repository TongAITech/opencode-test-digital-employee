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
