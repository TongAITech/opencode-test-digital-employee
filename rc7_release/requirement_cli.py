from __future__ import annotations

import argparse
import json
from pathlib import Path

from rc7_runtime.requirement_toolchain import RequirementDiffEngine, RequirementDocumentParser, source_map


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Parse and diff RC7 requirement source documents offline")
    parser.add_argument("--input", action="append", default=[], help="Requirement source file; repeatable")
    parser.add_argument("--before", help="Previous requirement source for change analysis")
    parser.add_argument("--after", help="Current requirement source for change analysis")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    document_parser = RequirementDocumentParser()
    payload = {
        "schema_version": "pfc.aitest.rc7.requirement-source.v1",
        "status": "PASS",
        "gate": "REQUIREMENT_TOOLCHAIN_PASS",
        "sources": [],
        "diff": [],
    }
    for raw in args.input:
        fragments = document_parser.parse(raw)
        payload["sources"].append(source_map(fragments))
    if bool(args.before) != bool(args.after):
        raise SystemExit("--before and --after must be supplied together")
    if args.before and args.after:
        before = document_parser.parse(args.before)
        after = document_parser.parse(args.after)
        payload["diff"] = [item.to_dict() for item in RequirementDiffEngine().diff(before, after)]
        payload["before"] = source_map(before)
        payload["after"] = source_map(after)

    target = Path(args.output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "gate": "REQUIREMENT_TOOLCHAIN_PASS", "output": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
