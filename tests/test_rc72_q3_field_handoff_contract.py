from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = "b" * 40
REQUIRED_PACKAGE_FILES = {
    "SOURCE_COMMIT",
    "packaging/rc7.2/Q3-FIELD-HANDOFF.sh",
    "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
    "packaging/rc7.2/AITEST.sh",
    "rc7_release/rc72_target_linux_attestation.py",
    "rc7_release/rc72_target_linux_reality.py",
}


def _git_bash_executable():
    if os.name != "nt":
        return shutil.which("bash") or "bash"
    override = os.environ.get("PFC_GIT_BASH")
    candidates = [Path(override)] if override else []
    git = shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        candidates.extend([git_path.with_name("bash.exe"), git_path.parent.parent / "bin" / "bash.exe"])
    for env_name in ("ProgramW6432", "ProgramFiles"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise AssertionError("GIT_BASH_EXECUTABLE_NOT_FOUND")


def _bash_path(path):
    if os.name != "nt":
        return str(path)
    bash = _git_bash_executable()
    return subprocess.check_output([bash, "-lc", 'cygpath -u "$1"', "bash", str(path)], text=True).strip()


def _package_fixture(tmp_path, source=SOURCE):
    root = tmp_path / "package"
    (root / "packaging" / "rc7.2").mkdir(parents=True)
    (root / "rc7_release").mkdir(parents=True)
    for name in ("Q3-FIELD-HANDOFF.sh", "Q3-TARGET-LINUX-PROBE.sh", "AITEST.sh"):
        shutil.copy2(REPO_ROOT / "packaging" / "rc7.2" / name, root / "packaging" / "rc7.2" / name)
    shutil.copy2(REPO_ROOT / "rc7_release" / "__init__.py", root / "rc7_release" / "__init__.py")
    for name in ("rc72_target_linux_attestation.py", "rc72_target_linux_reality.py"):
        shutil.copy2(REPO_ROOT / "rc7_release" / name, root / "rc7_release" / name)
    (root / "SOURCE_COMMIT").write_text(source + "\n", encoding="utf-8")
    return root


def _handoff_env():
    env = dict(os.environ)
    env["PFC_RC72_PACKAGE_PYTHON"] = _bash_path(Path(sys.executable))
    return env


def _run_handoff(package, output, runner_kind="GITHUB_HOSTED_GENERIC", runner_identity="contract-handoff", source=SOURCE):
    handoff = package / "packaging" / "rc7.2" / "Q3-FIELD-HANDOFF.sh"
    return subprocess.run([_git_bash_executable(), _bash_path(handoff), "--package-root", _bash_path(package), "--source-commit", source, "--runner-kind", runner_kind, "--runner-identity", runner_identity, "--output-dir", _bash_path(output)], env=_handoff_env(), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def test_field_handoff_script_is_posix_and_contains_no_install_or_self_approval_path():
    handoff = REPO_ROOT / "packaging" / "rc7.2" / "Q3-FIELD-HANDOFF.sh"
    subprocess.run([_git_bash_executable(), "-n", _bash_path(handoff)], check=True)
    lowered = handoff.read_text(encoding="utf-8").lower()
    for forbidden in ("apt install", "apt-get install", "yum install", "dnf install", "pip install", "npm install", "curl http", "wget http", "target_linux_verified=true", "field_verified=true", "bank_final=true", '"decision":"approved"', '"status":"pass"'):
        assert forbidden not in lowered


def test_field_handoff_fails_closed_on_package_source_mismatch(tmp_path):
    package = _package_fixture(tmp_path, source="c" * 40)
    output = tmp_path / "evidence"
    result = _run_handoff(package, output)
    assert result.returncode != 0
    assert "Q3_FIELD_HANDOFF_PACKAGE_SOURCE_MISMATCH" in result.stdout
    assert not output.exists()


def test_field_handoff_binds_transport_package_evidence_and_never_approves_target(tmp_path):
    package = _package_fixture(tmp_path)
    output = tmp_path / "evidence"
    result = _run_handoff(package, output)
    assert result.returncode == 0, result.stdout
    request = json.loads((output / "q3-target-attestation-request.json").read_text(encoding="utf-8"))
    package_evidence = json.loads((output / "q3-target-package-evidence.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "q3-target-handoff-manifest.json").read_text(encoding="utf-8"))
    assert request["package_evidence_bound"] is True
    assert request["package_evidence_digest"] == manifest["package_evidence_digest"]
    assert len(request["package_evidence_digest"]) == 64
    assert package_evidence["package_source_match"] is True
    assert set(package_evidence["critical_files"]) == REQUIRED_PACKAGE_FILES
    assert all(len(value) == 64 for value in package_evidence["critical_files"].values())
    assert package_evidence["network_install_performed"] is False
    assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert manifest["qualification_state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert manifest["trusted_verifier_required"] is True
    assert request["target_linux_verified"] is False
    assert manifest["field_verified"] is False
    assert manifest["bank_final"] is False


def test_mutating_critical_package_file_changes_bound_package_digest(tmp_path):
    package = _package_fixture(tmp_path)
    output1 = tmp_path / "evidence1"
    result1 = _run_handoff(package, output1)
    assert result1.returncode == 0, result1.stdout
    digest1 = json.loads((output1 / "q3-target-attestation-request.json").read_text(encoding="utf-8"))["package_evidence_digest"]
    reality = package / "rc7_release" / "rc72_target_linux_reality.py"
    reality.write_text(reality.read_text(encoding="utf-8") + "\n# transported mutation\n", encoding="utf-8")
    output2 = tmp_path / "evidence2"
    result2 = _run_handoff(package, output2)
    assert result2.returncode == 0, result2.stdout
    digest2 = json.loads((output2 / "q3-target-attestation-request.json").read_text(encoding="utf-8"))["package_evidence_digest"]
    assert digest1 != digest2


def test_bank_field_runner_label_is_only_observed_not_self_approved(tmp_path):
    package = _package_fixture(tmp_path)
    output = tmp_path / "evidence"
    result = _run_handoff(package, output, runner_kind="BANK_FIELD_TARGET", runner_identity="bank-target-host-01")
    assert result.returncode == 0, result.stdout
    request = json.loads((output / "q3-target-attestation-request.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "q3-target-handoff-manifest.json").read_text(encoding="utf-8"))
    assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
    assert request["package_evidence_bound"] is True
    assert "decision" not in request
    assert manifest["field_verified"] is False
    assert manifest["bank_final"] is False
