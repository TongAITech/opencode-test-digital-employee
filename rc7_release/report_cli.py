from __future__ import annotations

import argparse
import json

from rc7_runtime.reporting import MissionReportBuilder, ReportRenderer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate RC7 mission report from R1 Event Stream")
    parser.add_argument("--r1-path", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--output", default="state/reports")
    args = parser.parse_args(argv)

    builder = MissionReportBuilder.from_r1_path(args.r1_path)
    report = builder.build(args.mission_id)
    paths = ReportRenderer().write_all(report, args.output)
    print(json.dumps({
        "status": "PASS",
        "gate": "REPORT_TOOLCHAIN_PASS",
        "mission_id": args.mission_id,
        "truth_source": "R1_EVENT_STREAM",
        "outputs": paths,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
