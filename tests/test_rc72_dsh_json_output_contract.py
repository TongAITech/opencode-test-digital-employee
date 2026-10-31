from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher

# Importing rc7_runtime installs the RC7.2 strict final-JSON contract.
import rc7_runtime  # noqa: F401


def test_nested_strict_json_selects_complete_outer_candidate():
    expected = {
        "status": "CANDIDATE",
        "cases": [
            {
                "tc_id": "TC-1",
                "oracle": {"checks": [{"type": "API", "evidence_ref": "ev://1"}]},
                "coverage_links": [
                    {"subject_id": "OBL-1", "evidence_ref": "ev://2"}
                ],
            }
        ],
    }
    text = 'worker final: {"status":"CANDIDATE","cases":[{"tc_id":"TC-1","oracle":{"checks":[{"type":"API","evidence_ref":"ev://1"}]},"coverage_links":[{"subject_id":"OBL-1","evidence_ref":"ev://2"}]}]}'

    assert DshHeadlessWorkerLauncher._last_json_object(text) == expected


def test_multiple_json_objects_selects_last_complete_outer_object_not_nested_tail():
    text = (
        '{"old":1}\n'
        'analysis text\n'
        '{"status":"CANDIDATE","payload":{"nested":{"value":2}}}'
    )

    assert DshHeadlessWorkerLauncher._last_json_object(text) == {
        "status": "CANDIDATE",
        "payload": {"nested": {"value": 2}},
    }
