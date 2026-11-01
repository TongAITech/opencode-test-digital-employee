import subprocess

from rc7_release import rc72_bounded_pytest as bounded


def test_discover_is_sorted_and_file_only(tmp_path, monkeypatch):
    first = tmp_path / "test_rc72_b.py"
    second = tmp_path / "test_rc72_a.py"
    ignored = tmp_path / "test_rc72_dir.py"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    ignored.mkdir()
    monkeypatch.chdir(tmp_path)

    assert bounded.discover("test_rc72_*.py") == [
        "test_rc72_a.py",
        "test_rc72_b.py",
    ]


def test_timeout_is_fail_closed_and_next_file_still_runs(tmp_path, monkeypatch, capsys):
    calls = []

    class Result:
        returncode = 0

    def fake_run(command, timeout, check):
        calls.append((command[-1], timeout, check))
        if command[-1].endswith("test_rc72_hang.py"):
            raise subprocess.TimeoutExpired(command, timeout)
        return Result()

    monkeypatch.setattr(bounded.subprocess, "run", fake_run)
    result = bounded.run_files(
        ["tests/test_rc72_hang.py", "tests/test_rc72_ok.py"],
        timeout_seconds=7,
        junit_dir=str(tmp_path / "junit"),
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "RC72_BOUNDED_PYTEST_TIMEOUT::tests/test_rc72_hang.py::timeout=7s" in output
    assert "RC72_BOUNDED_PYTEST_PASS::tests/test_rc72_ok.py" in output
    assert [item[0] for item in calls] == [
        "tests/test_rc72_hang.py",
        "tests/test_rc72_ok.py",
    ]


def test_nonzero_pytest_exit_is_fail_closed(tmp_path, monkeypatch, capsys):
    class Result:
        returncode = 3

    monkeypatch.setattr(bounded.subprocess, "run", lambda *args, **kwargs: Result())
    result = bounded.run_files(
        ["tests/test_rc72_fail.py"],
        timeout_seconds=9,
        junit_dir=str(tmp_path / "junit"),
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "RC72_BOUNDED_PYTEST_FAIL::tests/test_rc72_fail.py::exit=3" in output
