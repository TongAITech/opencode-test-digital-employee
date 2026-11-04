"""E-owned read-only C09 host composition fixtures, NOT Field credentials.

These fixtures construct the actual production typed services against the
same BrowserPool/R1/release, but deliberately prohibit any physical browser,
4A authorization or Business Oracle I/O. A tool-registry string by itself is
never allowed to manufacture BSK/CDP worker privileges.
"""
from rc7_runtime.rc72_browser_resources import BrowserPool
from rc7_runtime.rc72_journey_bsk import JourneyBSKAdapter
from rc7_runtime.rc72_journey_playwright import JourneyPlaywrightAdapter
from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService


def _no_browser_io(*args, **kwargs):
    raise AssertionError(
        'C09 QA product composition must not touch CDP, BSK, 4A or business I/O')


def bind_native_bsk_host(truth, options, tmp_path):
    pool = BrowserPool(truth, release_id=options['release_id'])
    adapter = JourneyBSKAdapter(
        browser_pool=pool, evidence_root=tmp_path / 'qa-bsk-evidence',
        bsk_executable=tmp_path / 'BSK-BANK-BINARY-NOT-PRESENT',
        session_resolver=lambda scope, instance: {},
        session_receipt_verifier=lambda session, scope, instance: False,
        reference_resolver=lambda ref, kind, scope: None,
        runner=_no_browser_io,
    )
    official = OfficialJourneyExecutionService(
        truth, release_id=options['release_id'],
        browser_pool=pool, adapter=adapter)
    options['official_bsk_execution'] = official
    return official


def bind_native_playwright_host(truth, options, tmp_path):
    pool = BrowserPool(truth, release_id=options['release_id'])
    adapter = JourneyPlaywrightAdapter(
        browser_pool=pool, evidence_root=tmp_path / 'qa-cdp-evidence',
        reference_resolver=lambda ref, kind, scope: None,
        connector=_no_browser_io,
    )
    official = OfficialJourneyExecutionService(
        truth, release_id=options['release_id'],
        browser_pool=pool, adapter=adapter)
    options['official_playwright_execution'] = official
    return official
