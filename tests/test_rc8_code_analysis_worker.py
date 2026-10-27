import pytest

from rc8_node.code_analysis_worker import CodeAnalysisWorkerError, _scope_value


def test_scope_value_requires_single_explicit_colon_ref():
    refs = ("repo-path:C:/work/repo", "git-base:abc123", "git-head:def456")
    assert _scope_value(refs, "repo-path") == "C:/work/repo"
    assert _scope_value(refs, "git-base") == "abc123"
    assert _scope_value(refs, "git-head") == "def456"


def test_scope_value_is_fail_closed_for_missing_or_ambiguous_values():
    assert _scope_value(("repo-path:",), "repo-path") is None
    with pytest.raises(CodeAnalysisWorkerError):
        _scope_value(("git-head:a", "git-head:b"), "git-head")
