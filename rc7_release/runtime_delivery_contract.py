"""Fail-closed RC7 turnkey runtime delivery contract.

The package is only a transport candidate when every payload declared
``required_for_delivery=true`` by ``runtime-lock.json`` is physically present
in the clean package.  This validator deliberately treats the lock file as the
release authority; CI/package code must not silently downgrade required
payloads to optional because build inputs were omitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


SCHEMA_VERSION = "pfc.aitest.rc7.runtime-delivery-contract.v1"
LOCK_FILE = "runtime-lock.json"
OCR_CV_MARKER = Path("workspace-template/runtime/python/.rc7-capabilities/local_ocr_cv.json")


class RuntimeDeliveryContractError(RuntimeError):
    pass


def _safe_target(raw: object) -> Path:
    value = str(raw or "").strip().replace("\\", "/")
    if not value:
        raise RuntimeDeliveryContractError("RUNTIME_TARGET_REQUIRED")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeDeliveryContractError("UNSAFE_RUNTIME_TARGET:%s" % value)
    return path


def _meaningful_files(path: Path) -> List[Path]:
    if path.is_file():
        return [path] if path.stat().st_size > 0 else []
    if not path.is_dir():
        return []
    rows: List[Path] = []
    for item in path.rglob("*"):
        if item.is_file() and item.stat().st_size > 0:
            rows.append(item)
            if len(rows) >= 2:
                break
    return rows


def _load_json(path: Path, error: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise RuntimeDeliveryContractError(error)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeDeliveryContractError("%s:%s" % (error, exc))
    if not isinstance(payload, Mapping):
        raise RuntimeDeliveryContractError(error)
    return payload


def _manifest_bundled(manifest: Mapping[str, Any], payload_name: str) -> Optional[bool]:
    field = {
        "codegraph": "package_local_codegraph",
        "controlled_browser": "package_local_browser",
    }.get(payload_name)
    if not field:
        return None
    row = manifest.get(field)
    if not isinstance(row, Mapping):
        return False
    return bool(row.get("bundled"))


def verify_runtime_delivery(package_root: Path | str) -> Dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeDeliveryContractError("PACKAGE_ROOT_NOT_FOUND:%s" % root)

    lock = _load_json(root / LOCK_FILE, "RUNTIME_LOCK_REQUIRED")
    payloads = lock.get("payloads")
    if not isinstance(payloads, Mapping) or not payloads:
        raise RuntimeDeliveryContractError("RUNTIME_LOCK_PAYLOADS_INVALID")

    manifest_path = root / "PACKAGE_MANIFEST.json"
    manifest: Mapping[str, Any] = {}
    if manifest_path.is_file():
        manifest = _load_json(manifest_path, "PACKAGE_MANIFEST_INVALID")

    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    marker_missing: List[str] = []
    manifest_mismatch: List[str] = []

    for name in sorted(payloads):
        spec = payloads[name]
        if not isinstance(spec, Mapping):
            raise RuntimeDeliveryContractError("RUNTIME_PAYLOAD_SPEC_INVALID:%s" % name)
        required = bool(spec.get("required_for_delivery"))
        target = _safe_target(spec.get("relative_target"))
        absolute = root / target
        present = bool(_meaningful_files(absolute))
        marker_status: Optional[bool] = None

        # local_ocr_cv shares the Python target.  Python's presence must never
        # masquerade as OCR/CV capability; acquisition writes this marker only
        # after package-local import/smoke probes succeed.
        if name == "local_ocr_cv" and required:
            marker_status = bool(_meaningful_files(root / OCR_CV_MARKER))
            if not marker_status:
                marker_missing.append(name)

        bundled = _manifest_bundled(manifest, name) if manifest else None
        if required and not present:
            missing.append(name)
        if required and bundled is False:
            manifest_mismatch.append(name)

        rows.append(
            {
                "payload": name,
                "required_for_delivery": required,
                "relative_target": target.as_posix(),
                "present": present,
                "marker_present": marker_status,
                "manifest_bundled": bundled,
            }
        )

    blockers: List[str] = []
    if missing:
        blockers.append("REQUIRED_PAYLOAD_MISSING:" + ",".join(missing))
    if marker_missing:
        blockers.append("REQUIRED_CAPABILITY_MARKER_MISSING:" + ",".join(marker_missing))
    if manifest_mismatch:
        blockers.append("REQUIRED_PAYLOAD_MANIFEST_FALSE:" + ",".join(manifest_mismatch))

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not blockers else "FAIL",
        "delivery_runtime_complete": not blockers,
        "required_payload_count": sum(1 for row in rows if row["required_for_delivery"]),
        "payloads": rows,
        "blocking_reasons": blockers,
    }
    if blockers:
        raise RuntimeDeliveryContractError("DELIVERY_RUNTIME_INCOMPLETE:" + "|".join(blockers))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.runtime_delivery_contract")
    parser.add_argument("--package-root", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_runtime_delivery(args.package_root)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "FAIL",
                    "delivery_runtime_complete": False,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
