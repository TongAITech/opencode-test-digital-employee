from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from rc7_release import runtime_turnkey_certificate as certificate


COMMIT = "a" * 40


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _fake_package(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SOURCE_COMMIT").write_text(COMMIT + "\n", encoding="utf-8")
    _write_json(
        root / "runtime-lock.json",
        {
            "payloads": {
                "node": {
                    "required_for_delivery": True,
                    "relative_target": "workspace-template/runtime/node/node.exe",
                }
            }
        },
    )
    node = root / "workspace-template/runtime/node/node.exe"
    node.parent.mkdir(parents=True, exist_ok=True)
    node.write_bytes(b"node")
    _write_json(root / "RUNTIME_PAYLOADS.json", {"payloads": [{"payload": "node"}]})
    _write_json(root / "PACKAGE_MANIFEST.json", {"source_commit": COMMIT})


def _fake_smoke():
    return {
        "schema_version": "pfc.aitest.rc7.runtime-clean-smoke.v1",
        "status": "PASS",
        "delivery_runtime_complete": True,
        "required_payload_count": 1,
        "smoke_count": 1,
        "smokes": [{"capability": "node", "status": "PASS", "output": "v22"}],
    }


def _transport_zip(root: Path, package_root: Path) -> Path:
    path = root / "transport.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(package_root.rglob("*")):
            if item.is_file():
                archive.write(item, (Path(package_root.name) / item.relative_to(package_root)).as_posix())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Path(str(path) + ".sha256").write_text("%s  %s\n" % (digest, path.name), encoding="utf-8")
    return path


def test_issue_certificate_binds_clean_runtime_and_repacks_transport(tmp_path: Path, monkeypatch):
    built = tmp_path / "built" / "PFC"
    clean = tmp_path / "clean" / "PFC"
    _fake_package(built)
    _fake_package(clean)
    transport = _transport_zip(tmp_path, built)
    pre_digest = hashlib.sha256(transport.read_bytes()).hexdigest()
    monkeypatch.setattr(certificate, "_run_clean_smoke", lambda root: _fake_smoke())

    result = certificate.issue_turnkey_certificate(built, clean, transport)

    assert result["status"] == "PASS"
    assert result["pre_certificate_transport_zip_sha256"] == pre_digest
    assert result["final_transport_zip_sha256"] != pre_digest
    cert = json.loads((built / certificate.CERTIFICATE_FILE).read_text(encoding="utf-8"))
    assert cert["source_commit"] == COMMIT
    assert cert["smoke_capabilities"] == ["node"]
    manifest = json.loads((built / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["turnkey_runtime_qualification"]["path"] == certificate.CERTIFICATE_FILE
    sidecar = Path(str(transport) + ".sha256").read_text(encoding="utf-8").split()[0]
    assert sidecar == hashlib.sha256(transport.read_bytes()).hexdigest()
    assert certificate.verify_turnkey_certificate(built)["status"] == "PASS"


def test_verify_rejects_runtime_inventory_tamper(tmp_path: Path, monkeypatch):
    built = tmp_path / "built" / "PFC"
    clean = tmp_path / "clean" / "PFC"
    _fake_package(built)
    _fake_package(clean)
    transport = _transport_zip(tmp_path, built)
    monkeypatch.setattr(certificate, "_run_clean_smoke", lambda root: _fake_smoke())
    certificate.issue_turnkey_certificate(built, clean, transport)

    _write_json(built / "RUNTIME_PAYLOADS.json", {"payloads": [{"payload": "node", "tampered": True}]})

    with pytest.raises(certificate.TurnkeyRuntimeCertificateError, match="INVENTORY_HASH_MISMATCH"):
        certificate.verify_turnkey_certificate(built)


def test_issue_rejects_non_pass_clean_smoke(tmp_path: Path, monkeypatch):
    built = tmp_path / "built" / "PFC"
    clean = tmp_path / "clean" / "PFC"
    _fake_package(built)
    _fake_package(clean)
    transport = _transport_zip(tmp_path, built)
    monkeypatch.setattr(
        certificate,
        "_run_clean_smoke",
        lambda root: {
            "status": "FAIL",
            "delivery_runtime_complete": True,
            "required_payload_count": 1,
            "smoke_count": 1,
            "smokes": [{"capability": "node", "status": "FAIL"}],
        },
    )

    with pytest.raises(certificate.TurnkeyRuntimeCertificateError, match="CLEAN_RUNTIME_SMOKE_NOT_PASS"):
        certificate.issue_turnkey_certificate(built, clean, transport)


def test_verify_rerun_smoke_must_match_certificate_capabilities(tmp_path: Path, monkeypatch):
    built = tmp_path / "built" / "PFC"
    clean = tmp_path / "clean" / "PFC"
    _fake_package(built)
    _fake_package(clean)
    transport = _transport_zip(tmp_path, built)
    monkeypatch.setattr(certificate, "_run_clean_smoke", lambda root: _fake_smoke())
    certificate.issue_turnkey_certificate(built, clean, transport)

    monkeypatch.setattr(
        certificate,
        "_run_clean_smoke",
        lambda root: {
            "status": "PASS",
            "delivery_runtime_complete": True,
            "required_payload_count": 1,
            "smoke_count": 1,
            "smokes": [{"capability": "different", "status": "PASS"}],
        },
    )
    with pytest.raises(certificate.TurnkeyRuntimeCertificateError, match="RERUN_CAPABILITY_SET_MISMATCH"):
        certificate.verify_turnkey_certificate(built, rerun_smoke=True)
