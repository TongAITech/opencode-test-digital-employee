"""Offline-first FV-0..FV-4 package tooling.

This dispatcher only inspects package-local files and caller-supplied receipts.
It never contacts a bank system, starts a browser, invokes OpenCode, installs a
dependency, or treats a synthetic fixture as field evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True
TOOLS_ROOT = Path(__file__).resolve().parent
FIELD_VALIDATION_ROOT = TOOLS_ROOT.parent
WORKSPACE_ROOT = FIELD_VALIDATION_ROOT.parent
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"
DEFAULT_BINDING = FIELD_VALIDATION_ROOT / "bindings" / "bank-binding.template.json"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def package_file(rel: str) -> dict[str, Any]:
    path = WORKSPACE_ROOT / rel
    return {"path": rel, "present": path.is_file(), "size_bytes": path.stat().st_size if path.is_file() else None}


def binding_summary(payload: dict[str, Any]) -> dict[str, Any]:
    bindings = payload.get("bindings", {})
    result: dict[str, Any] = {}
    for name, spec in bindings.items():
        if not isinstance(spec, dict):
            result[str(name)] = {"status": "INVALID", "configured": False}
            continue
        env_name = str(spec.get("env") or "")
        relative_path = str(spec.get("relative_path") or "")
        default_value = spec.get("default")
        configured_from_env = bool(env_name and os.environ.get(env_name))
        configured_from_relative = bool(relative_path and (WORKSPACE_ROOT / relative_path).exists())
        configured_from_default = bool(default_value)
        result[str(name)] = {
            "status": "BOUND" if (configured_from_env or configured_from_relative or configured_from_default) else "UNBOUND",
            "configured": configured_from_env or configured_from_relative or configured_from_default,
            "binding_class": spec.get("binding_class", "FIELD_VALIDATION_ENVIRONMENT_BINDING"),
            "env": env_name or None,
            "relative_path": relative_path or None,
            "source": "ENVIRONMENT" if configured_from_env else ("PACKAGE_RELATIVE_PATH" if configured_from_relative else ("TEMPLATE_DEFAULT" if configured_from_default else "NONE")),
        }
    return result


def base_result(fv_id: str, status: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "r1-r4.field-validation.output.v1",
        "fv_id": fv_id,
        "generated_at": now(),
        "status": status,
        "execution_class": "PACKAGE_STATIC_OR_RECEIPT_REVIEW",
        "real_field_validation_executed": False,
        "bank_contacted": False,
        "detail": detail,
    }


def fv0(args: argparse.Namespace) -> dict[str, Any]:
    sys.path.insert(0, str(RUNTIME_ROOT))
    try:
        from aitest_runtime import doctor

        report = doctor.run(field_validation_profile=str(args.profile or (FIELD_VALIDATION_ROOT / "runtime-profile.json")))
        status = "PASS" if report.get("required_ok") else "REVIEW_REQUIRED"
        detail = {"doctor": report, "package_files": [
            package_file("runtime/python/python.exe"),
            package_file("runtime/browser/chrome-win64/chrome.exe"),
            package_file("ai-test/config/capabilities.json"),
            package_file("ai-test/config/test-layers.json"),
        ]}
    except Exception as exc:
        status = "REVIEW_REQUIRED"
        detail = {"error": type(exc).__name__, "message": str(exc)}
    return base_result("FV-0", status, detail)


def fv1(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.input).resolve() if args.input else DEFAULT_BINDING
    try:
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise ValueError("binding template must be a JSON object")
        summary = binding_summary(payload)
        detail = {
            "binding_file": path.name,
            "binding_file_present": path.is_file(),
            "bank_prerequisites": payload.get("bank_prerequisites", {}),
            "bindings": summary,
            "configured_binding_count": sum(1 for item in summary.values() if item.get("configured")),
            "unbound_binding_count": sum(1 for item in summary.values() if not item.get("configured")),
        }
        status = "READY_FOR_BINDING" if path.is_file() else "REVIEW_REQUIRED"
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        status = "REVIEW_REQUIRED"
        detail = {"binding_file": path.name, "error": type(exc).__name__, "message": str(exc)}
    return base_result("FV-1", status, detail)


def receipt_review(fv_id: str, args: argparse.Namespace, required: tuple[str, ...], kind: str) -> dict[str, Any]:
    if not args.input:
        return base_result(fv_id, "PENDING_EXTERNAL_RECEIPT", {"receipt_kind": kind, "required_fields": list(required), "input_present": False})
    path = Path(args.input).resolve()
    try:
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise ValueError("receipt must be a JSON object")
        present = {field: field in payload and payload[field] not in (None, "", []) for field in required}
        ok = all(present.values())
        return base_result(fv_id, "PASS" if ok else "REVIEW_REQUIRED", {
            "receipt_kind": kind,
            "receipt_file": path.name,
            "required_fields_present": present,
            "input_digest_required": True,
            "synthetic_or_fixture": bool(payload.get("synthetic_or_fixture", False)),
            "real_runtime_claim": bool(payload.get("real_runtime", False)),
        })
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return base_result(fv_id, "REVIEW_REQUIRED", {"receipt_kind": kind, "receipt_file": path.name, "error": type(exc).__name__, "message": str(exc)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R1-R4 Field Validation offline-first tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("fv-0", aliases=["fv0", "doctor"])
    doctor_parser.add_argument("--profile")
    init_parser = sub.add_parser("fv-1", aliases=["fv1", "project-init"])
    init_parser.add_argument("--input")
    coverage_parser = sub.add_parser("fv-2", aliases=["fv2", "coverage"])
    coverage_parser.add_argument("--input")
    execution_parser = sub.add_parser("fv-3", aliases=["fv3", "execution"])
    execution_parser.add_argument("--input")
    quality_parser = sub.add_parser("fv-4", aliases=["fv4", "quality"])
    quality_parser.add_argument("--input")
    for item in (coverage_parser, execution_parser, quality_parser):
        item.add_argument("--output")
    init_parser.add_argument("--output")
    doctor_parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    if command in {"fv-0", "fv0", "doctor"}:
        result = fv0(args)
    elif command in {"fv-1", "fv1", "project-init"}:
        result = fv1(args)
    elif command in {"fv-2", "fv2", "coverage"}:
        result = receipt_review("FV-2", args, ("requirement_refs", "coverage_snapshot_ref", "standard_test_case_refs"), "REQUIREMENT_COVERAGE_STANDARD_CASE")
    elif command in {"fv-3", "fv3", "execution"}:
        result = receipt_review("FV-3", args, ("mission_id", "attempt_refs", "execution_evidence_refs", "real_runtime"), "REAL_EXECUTION")
    else:
        result = receipt_review("FV-4", args, ("finding_refs", "defect_refs", "continuous_quality_refs"), "DEFECT_CONTINUOUS_QUALITY")
    output = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destination = getattr(args, "output", None)
    if destination:
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
