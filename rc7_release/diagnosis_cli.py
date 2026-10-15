from __future__ import annotations

import argparse
import json
from pathlib import Path

from rc7_runtime.diagnosis_providers import MultiToolLogDiagnoser


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Classify RC7 execution failure logs offline")
    parser.add_argument("--log", required=True)
    parser.add_argument("--provider", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    log_path = Path(args.log).expanduser().resolve()
    if not log_path.is_file():
        raise SystemExit("LOG_NOT_FOUND:%s" % log_path)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result = MultiToolLogDiagnoser().analyze(text, args.provider)
    payload = {
        "schema_version": "pfc.aitest.rc7.diagnosis-tool.v1",
        "status": "PASS",
        "gate": "DIAGNOSIS_TOOLCHAIN_PASS",
        "log_ref": "file://" + str(log_path),
        "result": result,
    }
    target = Path(args.output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "gate": "DIAGNOSIS_TOOLCHAIN_PASS", "output": str(target), "failure_class": result["failure_class"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
