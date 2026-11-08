"""Bring the *approved* native Windows DSH main binary into the RC7.2 ZIP.

A plugin archive or an installed bank-side executable is NOT a turnkey main
binary. The release builder must be given a separately approved binary plus
an independently recorded SHA256. This module never guesses a release URL,
writes a successful substitute, or treats a mock executable as bank proof.
Python 3.8 compatible. A successful result is PHYSICAL_CANDIDATE_ONLY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
DSH_RELATIVE_PATH = "workspace-template/runtime/dsh/dsh.exe"
MAX_SIZE = 250 * 1024 * 1024
MIN_SIZE = 4096


class DshMainPayloadError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _approved_executable(path):
    """Check PE32+/x64 instead of accepting a renamed shell stub."""
    path = Path(path)
    size = path.stat().st_size
    if size < MIN_SIZE or size > MAX_SIZE:
        raise DshMainPayloadError("DSH_MAIN_BINARY_SIZE_INVALID")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise DshMainPayloadError("DSH_MAIN_NOT_WINDOWS_PE")
        stream.seek(0x3c)
        raw = stream.read(4)
        if len(raw) != 4:
            raise DshMainPayloadError("DSH_MAIN_PE_HEADER_MISSING")
        offset = struct.unpack("<I", raw)[0]
        if offset < 64 or offset > min(size - 26, 1024 * 1024):
            raise DshMainPayloadError("DSH_MAIN_PE_HEADER_INVALID")
        stream.seek(offset)
        if stream.read(4) != b"PE\x00\x00":
            raise DshMainPayloadError("DSH_MAIN_PE_SIGNATURE_INVALID")
        if stream.read(2) != b"\x64\x86":  # IMAGE_FILE_MACHINE_AMD64
            raise DshMainPayloadError("DSH_MAIN_X64_REQUIRED")
        stream.seek(offset + 24)
        if stream.read(2) != b"\x0b\x02":  # PE32+ optional header
            raise DshMainPayloadError("DSH_MAIN_PE32_PLUS_REQUIRED")


class _DenyRedirect(HTTPRedirectHandler):
    """Never forward approved-source Authorization to a redirected host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _stream_download(url, destination):
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.fragment):
        raise DshMainPayloadError("DSH_MAIN_APPROVED_HTTPS_SOURCE_REQUIRED")
    if parts.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise DshMainPayloadError("DSH_MAIN_LOOPBACK_SOURCE_FORBIDDEN")
    headers = {"User-Agent": "RC72-Offline-Release-Builder"}
    authorization = os.environ.get("RC72_DSH_MAIN_AUTHORIZATION", "").strip()
    if authorization:
        if "\r" in authorization or "\n" in authorization:
            raise DshMainPayloadError("DSH_MAIN_AUTHORIZATION_HEADER_INVALID")
        headers["Authorization"] = authorization
    # urllib.urlopen transparently follows redirects, including cross-host
    # HTTPS redirects with the Authorization header. C12 has no authority to
    # disclose a bank/vendor token to a URL not independently approved.
    opener = build_opener(_DenyRedirect())
    try:
        with opener.open(Request(url, headers=headers), timeout=90) as response:
            if response.geturl() != url or response.status != 200:
                raise DshMainPayloadError("DSH_MAIN_SOURCE_RESPONSE_CHANGED")
            with Path(destination).open("wb") as output:
                total = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_SIZE:
                        raise DshMainPayloadError("DSH_MAIN_BINARY_TOO_LARGE")
                    output.write(block)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise DshMainPayloadError("DSH_MAIN_HTTP_REDIRECT_FORBIDDEN") from None
        raise DshMainPayloadError("DSH_MAIN_HTTPS_FETCH_FAILED") from None
    except (URLError, OSError, ValueError):
        # An underlying exception may embed the approved URL/token; never
        # serialize it into a build receipt or CI log.
        raise DshMainPayloadError("DSH_MAIN_HTTPS_FETCH_FAILED") from None


def materialize(package_root, *, expected_sha256, source_file=None, source_url=None):
    if not SHA256.fullmatch(str(expected_sha256 or "")):
        raise DshMainPayloadError("DSH_MAIN_APPROVED_SHA256_REQUIRED")
    if bool(source_file) == bool(source_url):
        raise DshMainPayloadError("DSH_MAIN_EXACTLY_ONE_APPROVED_SOURCE_REQUIRED")
    root = Path(package_root).resolve()
    if not root.is_dir() or not (root / "SOURCE_COMMIT").is_file():
        raise DshMainPayloadError("DSH_MAIN_PACKAGE_ROOT_REQUIRED")
    target_dir = root / "workspace-template/runtime/dsh"
    # Reject inherited parent symlinks too. A checked dsh directory alone
    # cannot prevent a package-root/runtime junction from escaping the ZIP.
    parent = root
    for component in ("workspace-template", "runtime", "dsh"):
        parent = parent / component
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise DshMainPayloadError("DSH_MAIN_TARGET_SYMLINK_OR_NONDIR")
    target = target_dir / "dsh.exe"
    if target.is_symlink():
        raise DshMainPayloadError("DSH_MAIN_TARGET_SYMLINK_FORBIDDEN")
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rc72-dsh-main-") as temp:
        staged = Path(temp) / "approved-dsh.exe"
        if source_file:
            source = Path(source_file)
            if source.is_symlink() or not source.is_file():
                raise DshMainPayloadError("DSH_MAIN_SOURCE_NOT_REGULAR_FILE")
            if not MIN_SIZE <= source.stat().st_size <= MAX_SIZE:
                raise DshMainPayloadError("DSH_MAIN_BINARY_SIZE_INVALID")
            shutil.copyfile(str(source), str(staged))
        else:
            _stream_download(source_url, staged)
        observed = sha256_file(staged)
        if observed != expected_sha256.lower():
            raise DshMainPayloadError("DSH_MAIN_APPROVED_SHA256_MISMATCH")
        _approved_executable(staged)
        # Do not overwrite a prior independently materialized nonmatching DSH.
        if target.exists():
            if not target.is_file() or sha256_file(target) != observed:
                raise DshMainPayloadError("DSH_MAIN_EXISTING_TARGET_CONFLICT")
        else:
            shutil.copyfile(str(staged), str(target))
        if sha256_file(target) != observed:
            raise DshMainPayloadError("DSH_MAIN_COPIED_BYTES_MISMATCH")
    return {"schema": "RC72_DSH_MAIN_PHYSICAL_SOURCE_V1",
            "status": "PHYSICAL_CANDIDATE_ONLY", "relative_path": DSH_RELATIVE_PATH,
            "sha256": observed, "bytes": target.stat().st_size,
            "source_commit": (root / "SOURCE_COMMIT").read_text(encoding="utf-8").strip(),
            "field_verified": False, "bank_final": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Require approved DSH main bytes before RC7.2 release packaging")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--source-file", default=os.environ.get("RC72_DSH_MAIN_SOURCE_FILE"))
    parser.add_argument("--source-url", default=os.environ.get("RC72_DSH_MAIN_URL"))
    parser.add_argument("--expected-sha256", default=os.environ.get("RC72_DSH_MAIN_SHA256"))
    parser.add_argument("--receipt")
    args = parser.parse_args(argv)
    try:
        result = materialize(args.package_root, expected_sha256=args.expected_sha256,
                             source_file=args.source_file, source_url=args.source_url)
        if args.receipt:
            receipt = Path(args.receipt).resolve()
            root = Path(args.package_root).resolve()
            if os.path.commonpath([str(root), str(receipt)]) == str(root):
                raise DshMainPayloadError("DSH_MAIN_RECEIPT_MUST_BE_OUTSIDE_PACKAGE")
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, DshMainPayloadError) as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc),
                          "field_verified": False, "bank_final": False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
