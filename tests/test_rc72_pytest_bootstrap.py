import subprocess

from rc7_release import rc72_pytest_bootstrap as bootstrap


def _requirements(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("pytest==8.3.5\n", encoding="utf-8")
    return str(path)


def test_reuses_exact_pinned_pytest_without_pip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "_installed_version", lambda: "8.3.5")

    def should_not_run(*args, **kwargs):
        raise AssertionError("pip must not run when the pinned pytest is present")

    monkeypatch.setattr(bootstrap.subprocess, "run", should_not_run)
    result = bootstrap.ensure_pytest(_requirements(tmp_path), timeout_seconds=7)

    assert result == 0
    assert "RC72_PYTEST_BOOTSTRAP_REUSE::pytest==8.3.5" in capsys.readouterr().out


def test_install_timeout_is_explicit_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "_installed_version", lambda: None)

    def timeout(command, check, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(bootstrap.subprocess, "run", timeout)
    result = bootstrap.ensure_pytest(_requirements(tmp_path), timeout_seconds=9)

    output = capsys.readouterr().out
    assert result == 124
    assert "RC72_PYTEST_BOOTSTRAP_TIMEOUT::pytest==8.3.5::timeout=9s" in output


def test_successful_install_must_verify_exact_version(tmp_path, monkeypatch, capsys):
    versions = iter([None, "8.3.5"])
    monkeypatch.setattr(bootstrap, "_installed_version", lambda: next(versions))

    class Result:
        returncode = 0

    calls = []

    def success(command, check, timeout):
        calls.append((command, check, timeout))
        return Result()

    monkeypatch.setattr(bootstrap.subprocess, "run", success)
    result = bootstrap.ensure_pytest(_requirements(tmp_path), timeout_seconds=11)

    assert result == 0
    assert calls[0][2] == 11
    assert "--retries" in calls[0][0]
    assert "--timeout" in calls[0][0]
    assert "pytest==8.3.5" in calls[0][0]
    assert "RC72_PYTEST_BOOTSTRAP_READY::pytest==8.3.5" in capsys.readouterr().out


def test_requirement_file_is_fail_closed(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("pytest>=8\n", encoding="utf-8")

    try:
        bootstrap.ensure_pytest(str(path))
    except ValueError as error:
        assert str(error) == "RC72_PYTEST_BOOTSTRAP_REQUIREMENT_INVALID"
    else:
        raise AssertionError("unpinned pytest requirement must be rejected")
