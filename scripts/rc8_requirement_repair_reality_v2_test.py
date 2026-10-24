#!/usr/bin/env python3
"""Corrected Requirement Repair Reality fixture and semantic history view.

The first fake DSH answer must pass REQUIREMENT_ANALYSIS structural truth gates
before REQUIREMENT_SUFFICIENCY can judge it insufficient. It therefore keeps
source assertions / atomic statements / traceability / evidence valid and
omits only the normal path. The second answer adds the normal path.

The governance endpoint can contain other stage/mission evaluations added by
newer RC8 adoption slices. Requirement repair history is one verdict per
REQUIREMENT_SUFFICIENCY stage attempt. A green attempt may contain both the
Worker observation and the Center authoritative green receipt; those are two
projections of one attempt, not two repair rounds. This semantic view groups by
stage subject and, for green results, prefers the Center authoritative receipt.
"""
from __future__ import annotations

import stat
from pathlib import Path

import rc8_requirement_repair_reality_test as reality


_CENTER_EVALUATOR_ID = "RC8_CENTER_SUFFICIENCY_LEDGER"
_CENTER_POLICY_PREFIX = "center-ledger:"


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


def _is_center_authoritative_green(value):
    return (
        value.get("result") == "SUFFICIENT"
        and value.get("evaluator_id") == _CENTER_EVALUATOR_ID
        and str(value.get("policy_version") or "").startswith(_CENTER_POLICY_PREFIX)
    )


def _final_attempt_evaluation(values):
    if not values:
        return None
    authoritative_green = [value for value in values if _is_center_authoritative_green(value)]
    if authoritative_green:
        return authoritative_green[-1]
    # Negative Worker evaluations are valid fail-closed attempt outcomes and do
    # not require Center green authority. Preserve their repository order only
    # within the same stage subject; this is not used as cross-attempt chronology.
    return values[-1]


def _governance_by_stage_attempt(client, test_run_id):
    body = _ORIGINAL_GOVERNANCE(client, test_run_id)
    stage_order = {
        stage["stage_instance_id"]: (
            int(stage.get("attempt_no") or 0),
            str(stage.get("stage_instance_id") or ""),
        )
        for stage in body.get("stages") or []
        if stage.get("stage_instance_id")
        and stage.get("stage_type") == "REQUIREMENT_SUFFICIENCY"
    }
    by_subject = {}
    for value in body.get("evaluations") or []:
        subject_id = value.get("subject_id")
        if subject_id in stage_order:
            by_subject.setdefault(subject_id, []).append(value)

    final_evaluations = []
    for subject_id, _order in sorted(stage_order.items(), key=lambda item: item[1]):
        selected = _final_attempt_evaluation(by_subject.get(subject_id, []))
        if selected is not None:
            final_evaluations.append(selected)
    body["evaluations"] = final_evaluations
    return body


_ORIGINAL_GOVERNANCE = reality._governance


def main() -> int:
    reality._fake_dsh = _analysis_valid_but_insufficient_dsh
    reality._governance = _governance_by_stage_attempt
    return reality.main()


if __name__ == "__main__":
    raise SystemExit(main())
