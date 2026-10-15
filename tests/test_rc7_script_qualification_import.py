from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_release.script_qualification_strict import _fixed_import_accepted_design
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission


def test_imported_test_design_pass_is_authorized_by_local_evaluation(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    mission_id = "MISSION-SCRIPT-IMPORT-LOCAL-EVAL"
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id="RC7-TEST",
            goal="prove imported Test Design PASS is locally evaluated",
        ),
    )
    upstream_result_path = tmp_path / "upstream" / "rc7-dsh-test-design-result.json"
    upstream_result_path.parent.mkdir(parents=True, exist_ok=True)
    upstream_result_path.write_text("{}", encoding="utf-8")
    upstream_evaluation_id = "EVAL-UPSTREAM-OTHER-MISSION"
    upstream_result = {
        "mission_id": "MISSION-UPSTREAM-OTHER",
        "task_id": "TASK-UPSTREAM-TD",
        "evaluation_id": upstream_evaluation_id,
    }
    envelope = {
        "semantic_payload": {
            "cases": [
                {
                    "tc_id": "TC-001",
                    "runner_type": "PYTEST",
                }
            ]
        }
    }
    raw = b'{"upstream":"qualified-test-design"}\n'

    artifact_id, relative_path = _fixed_import_accepted_design(
        control,
        state_root=tmp_path,
        upstream_result_path=upstream_result_path,
        upstream_result=upstream_result,
        envelope=envelope,
        raw=raw,
    )

    tasks = truth.query("rc7_task")
    imported_tasks = [row for row in tasks if row.get("task_type") == "IMPORTED_UPSTREAM_PASS"]
    assert len(imported_tasks) == 1
    task = imported_tasks[0]
    assert task["mission_id"] == mission_id
    assert task["state"] == "PASS"
    assert task["evaluation_id"] != upstream_evaluation_id
    assert artifact_id in task["output_artifact_refs"]

    evaluations = truth.query("rc7_evaluation", evaluation_id=task["evaluation_id"])
    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation["mission_id"] == mission_id
    assert evaluation["node"] == "TEST_DESIGN"
    assert evaluation["result"] == "PASS"
    assert artifact_id in evaluation["artifact_refs"]
    assert evaluation["dimensions"]["imported_upstream_pass"] is True
    assert evaluation["dimensions"]["upstream_evaluation_id"] == upstream_evaluation_id

    artifacts = truth.query("rc7_artifact", artifact_id=artifact_id)
    assert len(artifacts) == 1
    assert artifacts[0]["mission_id"] == mission_id
    assert artifacts[0]["artifact_type_name"] == "TEST_DESIGN_MODEL"
    assert (tmp_path / relative_path).is_file()
