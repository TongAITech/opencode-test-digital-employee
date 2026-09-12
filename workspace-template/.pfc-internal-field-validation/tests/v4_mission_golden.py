"""Capture baseline Mission bytes/results with deterministic clock/event UUIDs.

This is a fixture generator. Never regenerate its committed golden to make a
changed implementation pass; compare against exact 240573e runtime instead.
"""
from pathlib import Path
import itertools
import json
from contextlib import closing
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import ActorRef, CommandEnvelope


class Clock:
    def now(self): return "2026-09-10T00:00:00.000000Z"


def capture(db):
    runtime = create_canonical_runtime(Path(db).parent, db_path=db, clock=Clock())
    actions = [
        ("CREATE_MISSION", {"purpose": "frozen compatibility fixture"}, None),
        ("CREATE_GOAL", {"goal_id": "goal-golden", "goal": {"intent": "compatibility", "title": "Golden"}}, None),
        ("ACTIVATE_MISSION", {}, None),
        ("CREATE_PLAN", {"plan_id": "plan-golden"}, None),
        ("OPEN_SESSION", {"purpose": "fixture"}, "session-golden"),
        ("CLOSE_SESSION", {}, "session-golden"),
    ]
    commands=[];results=[]
    counter=itertools.count(1)
    with patch("aitest_runtime.durable_core.command_bus.uuid.uuid4", side_effect=lambda: SimpleNamespace(hex=f"{next(counter):032x}")):
        for index,(kind,payload,sid) in enumerate(actions):
            c=CommandEnvelope(f"golden-{index}",kind,"mission-golden",runtime.get_head_seq("mission-golden"),ActorRef("USER","golden-owner"),payload,session_id=sid,idempotency_key=f"golden-key-{index}")
            commands.append(c);r=runtime.execute(c)
            if not r.ok:raise r.error
            results.append(r.to_dict())
    repeated=[runtime.execute(c).to_dict() for c in commands]
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.row_factory=sqlite3.Row
        events=[dict(v) for v in conn.execute("SELECT * FROM events ORDER BY seq")]
        command_rows=[dict(v) for v in conn.execute("SELECT * FROM commands ORDER BY command_id")]
    replay=runtime.replay_composed("mission-golden").to_dict()
    verification=runtime.verify_projection("mission-golden")
    return {"commands":command_rows,"events":events,"results":results,"repeated_results":repeated,"replay":replay,"verification":verification}


if __name__=="__main__":
    import sys
    with tempfile.TemporaryDirectory() as root:
        result=capture(Path(root)/"golden.db")
    Path(sys.argv[1]).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
