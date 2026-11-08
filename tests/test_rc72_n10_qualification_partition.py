"""No N10 scenario may disappear while fixing the Windows Q1 timeout."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULES = (
    "test_rc72_n10_control.py",
    "test_rc72_n10_feedback_tamper.py",
)


def test_q1_n10_repartition_keeps_all_six_original_cases_and_seven_tamper_scenarios():
    original, separate = (
        ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for name in MODULES
    )
    original_cases = {
        stmt.name for stmt in original.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name.startswith("test_")
    }
    negative = [
        stmt for stmt in separate.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name.startswith("test_")
    ]
    assert len(original_cases) == 6, original_cases
    assert len(negative) == 1
    assert negative[0].name == "test_n10_structured_feedback_rejects_mutated_r1_snapshot_without_new_io"
    markers = negative[0].decorator_list
    assert len(markers) == 1
    decorator = markers[0]
    assert isinstance(decorator, ast.Call)
    assert decorator.args[0].value == "tamper"
    values = ast.literal_eval(decorator.args[1])
    assert values == [
        "blockers", "facts", "manifest_id", "scope_snapshot_id",
        "proven_obligation_ids", "coverage_observation_ids", "created_at",
    ]
    # Keeping both files under tests/test_rc72_*.py ensures Q1 invokes
    # the original six and all seven signed-scope adversarial cases.
    assert all(name.startswith("test_rc72_") for name in MODULES)
