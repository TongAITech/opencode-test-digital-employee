import pytest

from rc8_center.code_source import CodeSourceSnapshot, CodeSourceSnapshotError


def _snapshot(**overrides):
    values = {
        "snapshot_id": "src-cfg-data-001",
        "repository_id": "cfg-data",
        "repository_url": "ssh://git.example.invalid/pfc/cfg-data.git",
        "application_id": "cfg-data",
        "base_commit_sha": "1111111111111111111111111111111111111111",
        "commit_sha": "2222222222222222222222222222222222222222",
        "subpath": "service/core",
        "created_at": 1,
    }
    values.update(overrides)
    return CodeSourceSnapshot(**values)


def test_frozen_ref_is_deterministic_and_commit_bound():
    first = _snapshot()
    second = _snapshot()

    assert first.frozen_ref == second.frozen_ref
    assert first.frozen_ref.startswith("code-source:src-cfg-data-001:")
    assert first.proves_materialized_commit(first.commit_sha)
    assert not first.proves_materialized_commit("3333333333333333333333333333333333333333")


def test_source_identity_changes_when_head_or_base_changes():
    original = _snapshot()
    changed_head = _snapshot(commit_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    changed_base = _snapshot(base_commit_sha="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    assert original.identity != changed_head.identity
    assert original.identity != changed_base.identity


def test_windows_and_linux_subpath_spelling_share_identity():
    windows = _snapshot(subpath="service\\core")
    linux = _snapshot(subpath="service/core")

    assert windows.identity == linux.identity


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"snapshot_id": ""}, "CODE_SOURCE_SNAPSHOT_ID_REQUIRED"),
        ({"repository_id": ""}, "CODE_SOURCE_REPOSITORY_ID_REQUIRED"),
        ({"repository_url": ""}, "CODE_SOURCE_REPOSITORY_URL_REQUIRED"),
        ({"commit_sha": ""}, "CODE_SOURCE_COMMIT_SHA_REQUIRED"),
        ({"subpath": "../outside"}, "CODE_SOURCE_SUBPATH_INVALID"),
    ],
)
def test_incomplete_or_unsafe_source_identity_fails_closed(overrides, error):
    with pytest.raises(CodeSourceSnapshotError, match=error):
        _snapshot(**overrides).validate()
