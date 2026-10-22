from pathlib import Path

from rc8_node.failure_classification import JUnitFailureClassifier
from rc8_runtime.governance import FailureOwnership


def _report(tmp_path: Path, body: str, name: str = "TEST-fail.xml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_assertion_mismatch_stays_unknown_instead_of_fake_product_defect(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        '''<testsuite tests="1" failures="1" errors="0">
          <testcase classname="com.acme.FooTest" name="shouldClassify">
            <failure type="org.opentest4j.AssertionFailedError" message="expected: &lt;1&gt; but was: &lt;2&gt;">stack</failure>
          </testcase>
        </testsuite>''',
    )
    result = JUnitFailureClassifier(str(tmp_path / "evidence")).classify([str(report)])

    assert result.primary_ownership == FailureOwnership.UNKNOWN
    assert result.semantic_review_required is True
    assert result.facts[0].ownership == FailureOwnership.UNKNOWN
    assert result.facts[0].reason_code == "ASSERTION_MISMATCH_REQUIRES_SEMANTIC_ADJUDICATION"
    assert Path(result.result_path).is_file()


def test_strong_dependency_linkage_error_can_be_classified_mechanically(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        '''<testsuite tests="1" failures="0" errors="1">
          <testcase classname="com.acme.FooTest" name="loadsClass">
            <error type="java.lang.NoClassDefFoundError" message="com/acme/Missing">java.lang.NoClassDefFoundError: com/acme/Missing</error>
          </testcase>
        </testsuite>''',
    )
    result = JUnitFailureClassifier(str(tmp_path / "evidence")).classify([str(report)])

    assert result.primary_ownership == FailureOwnership.DEPENDENCY
    assert result.semantic_review_required is False
    assert result.ownership_counts == {"DEPENDENCY": 1}
    assert result.facts[0].confidence == "HIGH"


def test_strong_environment_error_can_be_classified_mechanically(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        '''<testsuite tests="1" failures="0" errors="1">
          <testcase classname="com.acme.RemoteTest" name="connects">
            <error type="java.net.ConnectException" message="Connection refused">java.net.ConnectException: Connection refused</error>
          </testcase>
        </testsuite>''',
    )
    result = JUnitFailureClassifier(str(tmp_path / "evidence")).classify([str(report)])

    assert result.primary_ownership == FailureOwnership.ENVIRONMENT
    assert result.semantic_review_required is False
    assert result.facts[0].reason_code == "EXECUTION_ENVIRONMENT_FAILURE"


def test_mixed_ownership_is_unknown_at_attempt_level(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        '''<testsuite tests="2" failures="1" errors="1">
          <testcase classname="com.acme.FooTest" name="dependency">
            <error type="java.lang.ClassNotFoundException" message="Missing">java.lang.ClassNotFoundException: Missing</error>
          </testcase>
          <testcase classname="com.acme.FooTest" name="assertion">
            <failure type="java.lang.AssertionError" message="expected 1 but was 2">java.lang.AssertionError</failure>
          </testcase>
        </testsuite>''',
    )
    result = JUnitFailureClassifier(str(tmp_path / "evidence")).classify([str(report)])

    assert result.primary_ownership == FailureOwnership.UNKNOWN
    assert result.ownership_counts == {"DEPENDENCY": 1, "UNKNOWN": 1}
    assert result.semantic_review_required is True


def test_missing_testcase_failure_detail_is_preserved_as_unknown(tmp_path: Path) -> None:
    report = _report(tmp_path, '<testsuite tests="1" failures="1" errors="0"></testsuite>')
    result = JUnitFailureClassifier(str(tmp_path / "evidence")).classify([str(report)])

    assert result.primary_ownership == FailureOwnership.UNKNOWN
    assert result.facts[0].reason_code == "JUNIT_FAILURE_DETAIL_MISSING"
    assert result.facts[0].semantic_review_required is True


def test_detail_hash_and_excerpt_preserve_traceability_without_deciding_ownership(tmp_path: Path) -> None:
    detail = "x" * 2500
    report = _report(
        tmp_path,
        '<testsuite tests="1" failures="1" errors="0"><testcase classname="C" name="t"><failure type="CustomException">%s</failure></testcase></testsuite>' % detail,
    )
    result = JUnitFailureClassifier(str(tmp_path / "evidence")).classify([str(report)])

    assert len(result.facts[0].detail_excerpt) == 2000
    assert len(result.facts[0].detail_sha256) == 64
    assert result.facts[0].ownership == FailureOwnership.UNKNOWN
