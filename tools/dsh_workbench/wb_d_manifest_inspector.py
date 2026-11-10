"""WB-D01: read-only, allowlisted, redacted DSH host/package manifest inventory.

Does not read profile config, environment, model settings or API keys.
A manifest observation is NOT proof of DSH API compatibility or bank qualification.
Python 3.8+; Windows Git Bash compatible; no installation or writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


SCHEMA = "dsh-workbench-host-inventory/v1"
MAX_BYTES = 65536
MANIFESTS = (
    "package.json",
    "node_modules/@deepseek-ai/dsh/package.json",
    "node_modules/@nanmicoder/dsh-agent-teams/package.json",
    "node_modules/@deepseek-ai/deepseek-harness/package.json",
)
_NAME = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]{1,100}$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,79}$")
_NODE_RANGE = re.compile(r"^[0-9xX.*<>=|^~ \t-]{1,120}$")


class InventoryError(ValueError):
    pass


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _safe_manifest(root, relative):
    if relative not in MANIFESTS:
        raise InventoryError("MANIFEST_NOT_ALLOWLISTED")
    if root.is_symlink() or not root.is_dir():
        raise InventoryError("ROOT_NOT_LOCAL_DIRECTORY")
    path = root
    for segment in relative.split("/"):
        path = path / segment
        if path.is_symlink():
            raise InventoryError("SYMLINK_NOT_ALLOWED")
    # Reject unusual traversal and differences between path spelling and real target.
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise InventoryError("PATH_OUTSIDE_ROOT") from None
    return path


def _redacted_meta(blob):
    try:
        data = json.loads(blob.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except InventoryError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise InventoryError("INVALID_JSON") from None
    if not isinstance(data, dict):
        raise InventoryError("MANIFEST_NOT_OBJECT")
    name = data.get("name")
    version = data.get("version")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise InventoryError("PACKAGE_NAME_INVALID")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise InventoryError("PACKAGE_VERSION_INVALID")
    engine = (data.get("engines") or {})
    if not isinstance(engine, dict):
        raise InventoryError("ENGINES_INVALID")
    node = engine.get("node")
    # Do not print arbitrary manifest fields or unknown engine strings.
    if node is not None and (
        not isinstance(node, str) or not _NODE_RANGE.fullmatch(node)
    ):
        raise InventoryError("NODE_RANGE_INVALID")
    exports = data.get("exports")
    if exports is not None and not isinstance(exports, (dict, str, list)):
        raise InventoryError("EXPORTS_INVALID")
    client = isinstance(exports, dict) and any(
        key in exports for key in ("./client", "./client.js")
    )
    dsh = data.get("dsh")
    if dsh is not None and not isinstance(dsh, dict):
        raise InventoryError("DSH_METADATA_INVALID")
    return {
        "name": name,
        "version": version,
        "node_engine": node if node is not None else "NOT_DECLARED",
        "exports_declared": exports is not None,
        "client_export_declared": bool(client),
        "dsh_bundle_metadata_declared": bool(isinstance(dsh, dict) and "bundle" in dsh),
        "artifact_sha256": hashlib.sha256(blob).hexdigest(),
    }


def assess_compatibility(inventory, expected_version="1.18.26"):
    """Assess declared host identity only; never infer runtime panel compatibility."""
    if not isinstance(expected_version, str) or not _VERSION.fullmatch(expected_version):
        raise InventoryError("EXPECTED_VERSION_INVALID")
    hosts = [row["metadata"] for row in inventory.get("observations", [])
             if row.get("result") == "METADATA_OBSERVED"
             and row.get("metadata", {}).get("name") == "@deepseek-ai/dsh"]
    versions = {row["version"] for row in hosts}
    if not hosts:
        status = "HOST_IDENTITY_NOT_OBSERVED"
    elif len(versions) != 1:
        status = "HOST_VERSION_CONFLICT"
    elif versions != {expected_version}:
        status = "HOST_VERSION_MISMATCH"
    else:
        status = "DECLARED_VERSION_MATCH_RUNTIME_UNVERIFIED"
    return {"expected_version": expected_version, "host_version_status": status,
            "client_export_declared": any(row["client_export_declared"] for row in hosts),
            "panel_compatibility": "CAPABILITY_UNKNOWN",
            "field_status": "BLOCKED_FIELD", "field_verified": False,
            "bank_final": False}


def inspect(root, relative_paths=MANIFESTS):
    """Pure read-only observation, explicit allowlist. Never returns raw package data."""
    if not isinstance(root, (str, Path)):
        raise InventoryError("ROOT_PATH_REQUIRED")
    base = Path(root)
    if not relative_paths or any(p not in MANIFESTS for p in relative_paths):
        raise InventoryError("MANIFEST_NOT_ALLOWLISTED")
    if len(set(relative_paths)) != len(relative_paths):
        raise InventoryError("DUPLICATE_MANIFEST_REQUEST")
    # Validate root once, even if all manifests are absent.
    if base.is_symlink() or not base.is_dir():
        raise InventoryError("ROOT_NOT_LOCAL_DIRECTORY")
    observations = []
    for relative in relative_paths:
        path = _safe_manifest(base, relative)
        row = {"manifest": relative}
        if not path.exists():
            row["result"] = "NOT_FOUND"
            observations.append(row)
            continue
        if not path.is_file():
            row["result"] = "NOT_REGULAR_FILE"
            observations.append(row)
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                raise InventoryError("MANIFEST_TOO_LARGE")
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise InventoryError("MANIFEST_TOO_LARGE")
            row["metadata"] = _redacted_meta(raw)
            row["result"] = "METADATA_OBSERVED"
        except InventoryError as exc:
            row["result"] = exc.args[0]
        except OSError:
            row["result"] = "MANIFEST_UNREADABLE"
        observations.append(row)
    observed = sum(x["result"] == "METADATA_OBSERVED" for x in observations)
    return {
        "schema": SCHEMA,
        "method": "OFFLINE_READ_ONLY_ALLOWLIST",
        "result": "METADATA_OBSERVED" if observed else "NO_METADATA_OBSERVED",
        "observations": observations,
        "field_verified": False,
        "dsh_1_18_26_compatible": False,
        "bank_final": False,
        "models": "NOT_PROBED",
        "model_credentials": "NOT_READ_OR_STORED",
        "native_panel": "NOT_PROBED",
        "skills": "NOT_PROBED",
        "commands": "NOT_PROBED",
        "attachments": "NOT_PROBED",
        "history": "NOT_PROBED",
        "cancel": "NOT_PROBED",
        "teams_actual_concurrency": "NOT_PROBED",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="DSH read-only allowlisted package metadata audit")
    parser.add_argument("--root", required=True, help="Existing local DSH root; not exported")
    parser.add_argument("--manifest", action="append", choices=MANIFESTS,
                        help="Optional exact allowlisted package.json relative path")
    args = parser.parse_args(argv)
    try:
        output = inspect(args.root, tuple(args.manifest) if args.manifest else MANIFESTS)
        output["compatibility_assessment"] = assess_compatibility(output)
        rc = 0 if output["result"] == "METADATA_OBSERVED" and all(
            x["result"] in ("METADATA_OBSERVED", "NOT_FOUND")
            for x in output["observations"]
        ) else 2
    except InventoryError as exc:
        output = {"schema": SCHEMA, "result": exc.args[0],
                  "field_verified": False, "bank_final": False}
        rc = 2
    print(json.dumps(output, sort_keys=True, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
