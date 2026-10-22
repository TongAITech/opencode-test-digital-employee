#!/usr/bin/env python3
"""Corrected Requirement Repair Reality fixture.

The first fake DSH answer must pass REQUIREMENT_ANALYSIS structural truth gates
before REQUIREMENT_SUFFICIENCY can judge it insufficient.  It therefore keeps
source assertions / atomic statements / traceability / evidence valid and
omits only the normal path.  The second answer adds the normal path.

This wrapper intentionally changes only CI's deterministic model fixture.  It
does not weaken RequirementAnalysisWorker or DshJsonRunner.
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
        # Deliberately malicious/advisory field: the deterministic sufficiency
        # worker must ignore it and still return INSUFFICIENT on round 1.
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


def main() -> int:
    reality._fake_dsh = _analysis_valid_but_insufficient_dsh
    return reality.main()


if __name__ == "__main__":
    raise SystemExit(main())
