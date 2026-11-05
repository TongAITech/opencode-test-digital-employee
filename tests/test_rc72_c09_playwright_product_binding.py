"""C09 product entry: signed Playwright/CDP is never a generic HTTP tool.

A production Host must supply the canonical B-owned BrowserPool and exact
OfficialJourneyExecutionService. Factory composition cannot perform browser
business I/O or claim bank Field authorization.
"""
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_browser_resources import BrowserPool
from rc7_runtime.rc72_journey_playwright import JourneyPlaywrightAdapter
from rc7_runtime.rc72_journey_n7_adapter import SignedN7OfficialJourneyAdapter
from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService
from rc7_runtime.rc72_mission_factory import create_mission_driver
from rc72_n2_test_support import RELEASE
from test_rc72_mission_factory import _setup


def approved_playwright_host(tmp_path):
    truth, options = _setup(tmp_path)
    pool = BrowserPool(truth, release_id=RELEASE)
    adapter = JourneyPlaywrightAdapter(
        browser_pool=pool, evidence_root=tmp_path / 'real-cdp-evidence',
        reference_resolver=lambda ref, kind, scope: None,
        connector=lambda endpoint: pytest.fail('factory must not connect to CDP'))
    official = OfficialJourneyExecutionService(
        truth, release_id=RELEASE, browser_pool=pool, adapter=adapter)
    options['tool_registry'] = {
        'api_http': ('api_http',),
        'browser:write': ('journey_playwright',),
    }
    return truth, options, official


def test_formal_n7_binds_playwright_to_signed_official_adapter_without_r1_mutation(tmp_path):
    truth, options, official = approved_playwright_host(tmp_path)
    options['official_playwright_execution'] = official
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    adapters = driver.n7_pipeline.dispatch.adapters
    assert type(adapters['journey_playwright']) is SignedN7OfficialJourneyAdapter
    assert adapters['journey_playwright'].execution is official
    assert adapters['api_http'] is driver.n7_pipeline.runner
    assert adapters['journey_playwright'] is not driver.n7_pipeline.runner
    assert official.adapter.field_verified is False
    assert truth.store.path.read_bytes() == before
    assert not truth.query('rc72_official_journey_execution')
    assert not truth.query('rc72_n7_tool_dispatch')


@pytest.mark.parametrize('violation', [
    'missing', 'unregistered', 'fake', 'wrong_release', 'foreign_truth',
    'different_pool', 'wrong_adapter', 'unsafe_field_claim',
])
def test_playwright_requires_trusted_exact_host_before_any_r1_or_browser_io(
        tmp_path, violation):
    truth, options, official = approved_playwright_host(tmp_path)
    options['official_playwright_execution'] = official
    if violation == 'missing':
        options.pop('official_playwright_execution')
    elif violation == 'unregistered':
        options['tool_registry'] = {'api_http': ('api_http',)}
    elif violation == 'fake':
        options['official_playwright_execution'] = {'state': 'PASSED'}
    elif violation == 'wrong_release':
        official.release_id = 'foreign-release'
    elif violation == 'foreign_truth':
        official.truth = object()
    elif violation == 'different_pool':
        official.adapter.pool = BrowserPool(truth, release_id=RELEASE)
    elif violation == 'wrong_adapter':
        official.adapter = object()
    elif violation == 'unsafe_field_claim':
        official.trusted_field_adapter_kinds.add('PLAYWRIGHT_CDP_LOCAL')
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='MISSION_FACTORY_PLAYWRIGHT_'):
        create_mission_driver(truth, **options)
    assert truth.store.path.read_bytes() == before
    assert not truth.query('rc72_n7_tool_dispatch')


def test_unapproved_official_asset_never_reaches_cdp_from_signed_n7(tmp_path):
    truth, options, official = approved_playwright_host(tmp_path)
    options['official_playwright_execution'] = official
    adapter = create_mission_driver(
        truth, **options).n7_pipeline.dispatch.adapters['journey_playwright']
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match='JOURNEY_N7_'):
        adapter.preflight(
            contract={'tool_route': {'tool': 'journey_playwright'},
                      'request': {'official_asset_id': 'not-approved',
                                  'source_ref': 'official-journey://not-approved'},
                      'case_id': 'CASE-NOT-APPROVED'},
            context={'workitem_id': 'WI-NO', 'attempt_id': 'ATT-NO',
                     'worker_id': 'WORKER-NO', 'session_id': 'SESSION-NO',
                     'browser_lease_ids': []})
    assert truth.store.path.read_bytes() == before
