from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = "b" * 40


def _git_bash_executable():
    if os.name != "nt":
        return shutil.which("bash") or "bash"

    override = os.environ.get("PFC_GIT_BASH")
    candidates = []
    if override:
        candidates.append(Path(override))

    git = shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        candidates.extend(
            [
                git_path.with_name("bash.exe"),
                git_path.parent.parent / "bin" / "bash.exe",
            ]
        )

    for env_name in ("ProgramW6432", "ProgramFiles"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise AssertionError("GIT_BASH_EXECUTABLE_NOT_FOUND")


def _bash_path(path):
    text = str(path)
    if os.name != "nt":
        return text
    bash = _git_bash_executable()
    return subprocess.check_output(
        [bash, "-lc", 'cygpath -u "$1"', "bash", text],
        text=True,
    ).strip()


def _package_fixture(tmp_path, source=SOURCE):
    root = tmp_path / "package"
    (root / "packaging" / "rc7.2").mkdir(parents=True)
    (root / "rc7_release").mkdir(parents=True)
    for name in ("Q3-FIELD-HANDOFF.sh", "Q3-TARGET-LINUX-PROBE.sh", "AITEST.sh"):
        shutil.copy2(REPO_ROOT / "packaging" / "rc7.2" / name, root / "packaging" / "rc7.2" / name)
    shutil.copy2(REPO_ROOT / "rc7_release" / "__init__.py", root / "rc7_release" / "__init__.py")
    shutil.copy2(
        REPO_ROOT / "rc7_release" / "rc72_target_linux_attestation.py",
        root / "rc7_release" / "rc72_target_linux_attestation.py",
    )
    (root / "SOURCE_COMMIT").write_text(source + "\n", encoding="utf-8")
    return root


def _handoff_env():
    env = dict(os.environ)
    env["PFC_RC72_PACKAGE_PYTHON"] = _bash_path(Path(sys.executable))
    return env


def test_field_handoff_script_is_posix_and_contains_no_install_or_self_approval_path():
    handoff = REPO_ROOT / "packaging" / "rc7.2" / "Q3-FIELD-HANDOFF.sh"
    assert handoff.is_file()
    subprocess.run([_git_bash_executable(), "-n", _bash_path(handoff)], check=True)
    lowered = handoff.read_text(encoding="utf-8").lower()
    for forbidden in (
        "apt install",
        "apt-get install",
        "yum install",
        "dnf install",
        "pip install",
        "npm install",
        "curl http",
        "wget http",
        "target_linux_verified=true",
        "field_verified=true",
        "bank_final=true",
        '"decision":"approved"',
        '"status":"pass"',
    ):
        assert forbidden not in lowered


def test_field_handoff_fails_closed_on_package_source_mismatch(tmp_path):
    package = _package_fixture(tmp_path, source="c" * 40)
    output = tmp_path / "evidence"
    handoff = package / "packaging" / "rc7.2" / "Q3-FIELD-HANDOFF.sh"
    result = subprocess.run(
        [
            _git_bash_executable(),
            _bash_path(handoff),
            "--package-root",
            _bash_path(package),
            "--source-commit",
            SOURCE,
            "--runner-kind",
            "GITHUB_HOSTED_GENERIC",
            "--runner-identity",
            "contract-handoff",
            "--output-dir",
            _bash_path(output),
        ],
        env=_handoff_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode != 0
    assert "Q3_FIELD_HANDOFF_PACKAGE_SOURCE_MISMATCH" in result.stdout
    assert not output.exists()


def test_field_handoff_emits_digest_bound_evidence_but_never_approves_target(tmp_path):
    package = _package_fixture(tmp_path)
    output = tmp_path / "evidence"
    handoff = package / "packaging" / "rc7.2" / "Q3-FIELD-HANDOFF.sh"
    subprocess.run(
        [
            _git_bash_executable(),
            _bash_path(handoff),
            "--package-root",
            _bash_path(package),
            "--source-commit",
            SOURCE,
            "--runner-kind",
            "GITHUB_HOSTED_GENERIC",
            "--runner-identity",
            "contract-handoff",
            "--output-dir",
            _bash_path(output),
        ],
        env=_handoff_env(),
        check=True,
        cwd=REPO_ROOT,
    )

    observation = json.loads((output / "q3-target-observation.json").read_text(encoding="utf-8"))
    request = json.loads((output / "q3-target-attestation-request.json").read_text(encoding="utf-8"))
    package_evidence = json.loads((output / "q3-target-package-evidence.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "q3-target-handoff-manifest.json").read_text(encoding="utf-8"))

    assert observation["source_commit"] == SOURCE
    assert observation["runner_kind"] == "GITHUB_HOSTED_GENERIC"
    assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert request["observation_digest"] == manifest["observation_digest"]
    assert request["target_linux_verified"] is False
    assert request["field_verified"] is False
    assert request["bank_final"] is False

    assert package_evidence["package_source_match"] is True
    assert package_evidence["shell_syntax_verified"] is True
    assert package_evidence["network_install_performed"] is False
    assert package_evidence["target_linux_verified"] is False
    assert package_evidence["field_verified"] is False
    assert package_evidence["bank_final"] is False

    assert manifest["qualification_state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert manifest["next_action"] == "OBTAIN_TRUSTED_EXTERNAL_ATTESTATION"
    assert manifest["trusted_verifier_required"] is True
    assert manifest["target_linux_verified"] is False
    assert manifest["field_verified"] is False
    assert manifest["bank_final"] is False
    assert set(manifest["files"]) == {"observation", "attestation_request", "package_evidence"}
    for item in manifest["files"].values():
        assert len(item["sha256"]) == 64


def test_bank_field_runner_label_is_only_observed_not_self_approved(tmp_path):
    package = _package_fixture(tmp_path)
    output = tmp_path / "evidence"
    handoff = package / "packaging" / "rc7.2" / "Q3-FIELD-HANDOFF.sh"
    subprocess.run(
        [
            _git_bash_executable(),
            _bash_path(handoff),
            "--package-root",
            _bash_path(package),
            "--source-commit",
            SOURCE,
            "--runner-kind",
            "BANK_FIELD_TARGET",
            "--runner-identity",
            "bank-target-host-01",
            "--output-dir",
            _bash_path(output),
        ],
        env=_handoff_env(),
        check=True,
        cwd=REPO_ROOT,
    )
    observation = json.loads((output / "q3-target-observation.json").read_text(encoding="utf-8"))
    request = json.loads((output / "q3-target-attestation-request.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "q3-target-handoff-manifest.json").read_text(encoding="utf-8"))
    assert observation["runner_kind"] == "BANK_FIELD_TARGET"
    assert observation["runner_identity"] == "bank-target-host-01"
    assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert manifest["qualification_state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert "decision" not in request
    assert "target_environment_approved" not in request
    assert manifest["field_verified"] is False
    assert manifest["bank_final"] is False
