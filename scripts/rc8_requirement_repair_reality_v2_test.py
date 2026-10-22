#!/usr/bin/env python3
"""Corrected Requirement Repair Reality fixture and semantic history view.

The first fake DSH answer must pass REQUIREMENT_ANALYSIS structural truth gates
before REQUIREMENT_SUFFICIENCY can judge it insufficient.  It therefore keeps
source assertions / atomic statements / traceability / evidence valid and
omits only the normal path.  The second answer adds the normal path.

SufficiencyEvaluation rows do not carry R1 sequence and two evaluations can be
projected in the same second, so repository list position is not a chronology
contract.  For this Reality assertion we order Stage-level evaluations by the
attempt number of their subject Stage.  That proves attempt 1 is INSUFFICIENT
and attempt 2 is SUFFICIENT without inventing temporal truth from UUID order.
"""
from __future__ import annotations

import stat
from pathlib import Path

import rc8_requirement_repair_reality_test as reality


def _analysis_valid_but_insufficient_dsh(path: Path, state_path: Path) -> None:
    incomplete = {
        "source_assertions": ["SRC-ASSERT-1"],
        "atomic_statements": ["A1"],
        "trace_links": [{"statement_ref": "A1", "evidence_ref": "source:reqdoc#1"}],
        "evidence_refs": ["source:reqdoc#1"],
        "business_rules": [],
        "roles": ["客户"],
        "preconditions": [],
        "normal_paths": [],
        "negative_paths": [],
        "boundaries": [],
        "states": [],
        "data_constraints": [],
        "dependencies": [],
        "side_effects": [],
        # Deliberately advisory/malicious field: deterministic sufficiency must
        # ignore it and still return INSUFFICIENT on round 1.
        "is_sufficient": True,
    }
    complete = dict(incomplete)
    complete["normal_paths"] = ["客户提交 -> 系统校验 -> 成功"]
    program = '''#!/usr/bin/env python3
import json, pathlib, uuid
state = pathlib.Path(%r)
try:
    count = int(state.read_text(encoding="utf-8").strip())
except Exception:
    count = 0
count += 1
state.write_text(str(count), encoding="utf-8")
candidate = %r if count == 1 else %r
session = "session-ci-%%s" %% uuid.uuid4().hex
print(json.dumps({"type":"session","session_id":session}, ensure_ascii=False))
print(json.dumps({"type":"tool_call","tool_name":"read_requirement_source"}, ensure_ascii=False))
print(json.dumps({"type":"final","text":json.dumps(candidate, ensure_ascii=False)}, ensure_ascii=False))
''' % (str(state_path), incomplete, complete)
    path.write_text(program, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _governance_by_stage_attempt(client, test_run_id):
    body = _ORIGINAL_GOVERNANCE(client, test_run_id)
    stage_order = {
        stage["stage_instance_id"]: (
            int(stage.get("attempt_no") or 0),
            str(stage.get("stage_type") or ""),
            str(stage.get("stage_instance_id") or ""),
        )
        for stage in body.get("stages") or []
        if stage.get("stage_instance_id")
    }
    evaluations = list(body.get("evaluations") or [])
    evaluations.sort(
        key=lambda value: stage_order.get(
            value.get("subject_id"),
            (10**9, "", str(value.get("subject_id") or "")),
        )
    )
    body["evaluations"] = evaluations
    return body


_ORIGINAL_GOVERNANCE = reality._governance


def main() -> int:
    reality._fake_dsh = _analysis_valid_but_insufficient_dsh
    reality._governance = _governance_by_stage_attempt
    return reality.main()


if __name__ == "__main__":
    raise SystemExit(main())
