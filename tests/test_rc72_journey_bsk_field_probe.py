"""Read-only BSK bank qualification requires real local PNG and live extension."""
import json
from pathlib import Path

import pytest

from rc7_release.rc72_journey_bsk_qualify import qualify_bsk
from test_rc72_journey_bsk_import import _PNG


class ProbeRunner:
    def __init__(self, *, missing_extension=False, bad_tab=False,
                 invalid_png=False):
        self.calls = []
        self.missing_extension = missing_extension
        self.bad_tab = bad_tab
        self.invalid_png = invalid_png

    def __call__(self, argv):
        self.calls.append(list(argv))
        if "--version" in argv:
            return {"returncode": 0, "stdout": "bsk 1.8.0\n"}
        if "capabilities" in argv:
            return {"returncode": 0, "stdout": json.dumps({
                "capabilities": {
                    "cli": {"protocol": "1.8"},
                    "extension": {} if not self.missing_extension else None}})}
        if "cooperate" in argv:
            return {"returncode": 0, "stdout": json.dumps({
                "context_id": "BSK-CONTEXT", "tab_id": 43 if self.bad_tab else 37})}
        if "screenshot" in argv:
            screenshot = Path(argv[argv.index("--out") + 1])
            screenshot.write_bytes(b"bad" if self.invalid_png else _PNG)
            return {"returncode": 0, "stdout": json.dumps({
                "tab_id": 37, "byte_size": screenshot.stat().st_size,
                "format": "png"})}
        raise AssertionError("Unexpected BSK probe command " + repr(argv))


def _probe(tmp_path, runner, binary=None):
    package = tmp_path / "package"
    package.mkdir(exist_ok=True)
    (package / "SOURCE_COMMIT").write_text("a" * 40)
    executable = binary or (package / "tools" / "bsk.exe")
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"portable BSK fixture")
    output = tmp_path / "qualification"
    receipt = qualify_bsk(
        package_root=package, bsk_executable=executable,
        bsk_session_id="owned-bsk-session", tab_id=37,
        output_root=output, runner=runner)
    return receipt, output


def test_bsk_bank_probe_produces_read_only_sha_receipt_without_field_pass(tmp_path):
    cli = ProbeRunner()
    proof, path = _probe(tmp_path, cli)
    assert proof["status"] == "READ_ONLY_BSK_PROBE_PASS"
    assert proof["field_verified"] is False
    assert proof["official_journey_approved"] is False
    assert proof["sut_mutation_count"] == 0
    assert proof["source_commit"] == "a" * 40
    assert len(proof["bsk_sha256"]) == 64
    assert len(proof["screenshot"]["sha256"]) == 64
    assert (path / "live-browser.png").is_file()
    assert json.loads((path / "c09-bsk-probe.json").read_text())[
        "status"] == "READ_ONLY_BSK_PROBE_PASS"
    assert not any("step" in x or "click" in x or "fill" in x
                   for x in cli.calls)


@pytest.mark.parametrize("options,expected", [
    ({"missing_extension": True}, "BSK_PROBE_LIVE_EXTENSION_NOT_VERIFIED"),
    ({"bad_tab": True}, "BSK_PROBE_COOPERATIVE_CONTROL_NOT_GRANTED"),
    ({"invalid_png": True}, "JOURNEY_BSK_SCREENSHOT_SIZE_INVALID"),
])
def test_bsk_probe_does_not_claim_field_or_pass_on_missing_extension_tab_or_image(tmp_path, options, expected):
    proof, output = _probe(tmp_path, ProbeRunner(**options))
    assert proof["status"] == "BLOCKED"
    assert proof["field_verified"] is False
    assert proof["failure_code"] == expected
    assert (output / "c09-bsk-probe.json").is_file()
