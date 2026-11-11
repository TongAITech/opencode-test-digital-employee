"""Read-only binding evidence for an existing bank-host DSH CLI.

This does not download, copy, install, authorize or redistribute the executable.
It checks the Windows PE32+/AMD64 shape and optionally compares a supplied SHA256.
A successful observation is not proof of vendor identity, bank authorization,
Agent Teams operation, field qualification or BANK_FINAL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from .rc72_dsh_main_payload import _approved_executable, DshMainPayloadError

_SHA256 = re.compile("[0-9a-fA-F]{64}")


class DshHostBindingError(RuntimeError):
    pass


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_host_dsh(executable, expected_sha256=None):
    path = Path(executable).expanduser()
    if not path.is_absolute():
        raise DshHostBindingError("DSH_HOST_PATH_MUST_BE_ABSOLUTE")
    if path.is_symlink() or not path.is_file():
        raise DshHostBindingError("DSH_HOST_EXECUTABLE_NOT_REGULAR_FILE")
    if path.name.lower() != "dsh.exe":
        raise DshHostBindingError("DSH_HOST_EXECUTABLE_NAME_MUST_BE_DSH_EXE")
    try:
        _approved_executable(path)
    except (OSError, DshMainPayloadError):
        raise DshHostBindingError("DSH_HOST_EXECUTABLE_NOT_PE32_PLUS_AMD64") from None

    observed = _sha256(path)
    supplied = expected_sha256.strip().lower() if expected_sha256 else None
    if supplied is not None:
        if not _SHA256.fullmatch(supplied):
            raise DshHostBindingError("DSH_HOST_EXPECTED_SHA256_INVALID")
        if observed != supplied:
            raise DshHostBindingError("DSH_HOST_EXPECTED_SHA256_MISMATCH")

    return {
        "schema": "RC72_EXTERNAL_DSH_HOST_BINDING_OBSERVATION_V1",
        "status": "EXTERNAL_HOST_DSH_OBSERVED",
        "binding_mode": "EXPLICIT_BANK_HOST_EXECUTABLE",
        "executable_path": str(path.resolve()),
        "sha256": observed,
        "expected_sha256_supplied": supplied is not None,
        "expected_sha256_matched": supplied is not None,
        "pe32_plus_amd64_shape": True,
        "vendor_identity_verified": False,
        "bank_authorization_verified": False,
        "redistribution_authorized": False,
        "field_verified": False,
        "bank_final": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Observe an existing bank-host DSH CLI without copying it")
    parser.add_argument("--executable", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        result = inspect_host_dsh(args.executable, args.expected_sha256)
        if args.output:
            output = Path(args.output)
            if output.is_symlink():
                raise DshHostBindingError("DSH_HOST_RECEIPT_SYMLINK_FORBIDDEN")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                              encoding="utf-8")
    except (OSError, ValueError, DshHostBindingError) as exc:
        result = {
            "schema": "RC72_EXTERNAL_DSH_HOST_BINDING_OBSERVATION_V1",
            "status": "HOLD",
            "reason": str(exc) if isinstance(exc, DshHostBindingError) else "DSH_HOST_BINDING_IO_FAILED",
            "field_verified": False,
            "bank_final": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
