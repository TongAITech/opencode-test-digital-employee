"""CC-01 real R1 transactions/replay, frozen Mission golden and hostile roots.

No model/Host/worker-I/O qualification is claimed by these component tests.
"""
from __future__ import annotations
import concurrent.futures
from dataclasses import replace
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / "ai-test/runtime"))
from aitest_runtime.canonical_runtime import create_canonical_runtime, canonical_extension_manifests
from aitest_runtime.durable_core import ActorRef, CommandEnvelope, ExtensionRegistry, RuntimeError as CoreError, RuntimeService, SubjectRef, canonical_sha256, initial_composed_state, reduce_composed
from aitest_runtime.general_work import GeneralWorkService, general_work_extension
from aitest_runtime.general_work.contracts import EXTENSION_ID, ROOTS, job_subject
from v4_mission_golden import capture

ACTOR = ActorRef("SYSTEM", "verified-admission-test")
HOST = {"schema_version":1,"host_session_id":"host-s","host_message_id":"host-m","host_tool_message_id":"tool-m","parent_message_id":None,
        "source_ref":"host:host-s/host-m","source_digest":"a"*64,"observed_at":"2026-09-10T00:00:00Z","valid_until":"2026-09-12T00:00:00Z"}


class TypedRoots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v4-typed-root-")
        self.root = Path(self.temp.name)
        self.db = self.root / "r1.db"
        self.runtime = self.new_runtime()
        self.jobs = GeneralWorkService(self.runtime)

    def tearDown(self): self.temp.cleanup()

    def new_runtime(self, **kwargs): return create_canonical_runtime(self.root, db_path=self.db, **kwargs)

    def create(self, operation="operation-a", kind="GENERAL_WORK", **kwargs):
        return self.jobs.create(subject_kind=kind, operation_id=operation, host_turn_ref=HOST,
                                intent="Process one bounded note", actor=ACTOR, **kwargs)

    def sql(self, query, args=()):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(query, args).fetchall()

    def durable(self):
        return {"events":self.sql("SELECT * FROM events ORDER BY mission_id,seq"),
                "commands":self.sql("SELECT * FROM commands ORDER BY command_id"),
                "mission":self.sql("SELECT * FROM mission_projection ORDER BY mission_id"),
                "jobs":self.sql("SELECT * FROM general_work_projection ORDER BY job_id"),
                "all_projections":{name:sorted(self.sql(f"SELECT * FROM {name}"),key=repr)
                                   for (name,) in self.sql("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%projection' ORDER BY name")}}

    def transition(self, state, target, request, **kwargs):
        return self.jobs.transition(state.subject, expected_seq=state.seq, target_status=target, request_id=request, actor=ACTOR, **kwargs)

    def raw_create(self, kind, operation, *, payload_changes=None, **changes):
        definition = next(r for r in ROOTS if r.subject_kind == kind)
        subject = job_subject(kind, operation)
        identity = "r1:job:create:" + canonical_sha256(operation)
        payload = {"subject":subject.to_dict(),"root_version":definition.version,"creation_command":definition.creation_command,
                   "operation_id":operation,"host_turn_ref":HOST,"intent":"Raw contract negative"}
        payload.update(payload_changes or {})
        return replace(CommandEnvelope(identity, definition.creation_command, subject.subject_id, 0, ACTOR, payload, idempotency_key=identity), **changes)

    def test_frozen_mission_bytes_results_fingerprints_hashes(self):
        golden = json.loads((Path(__file__).parent / "fixtures/v4_mission_240573e_golden.json").read_text())
        current = capture(self.root / "current-golden.db")
        self.assertEqual(current, golden)

    def test_both_work_roots_have_no_fake_mission_or_mission_extensions(self):
        for kind in ("GENERAL_WORK", "RUNTIME_DIAGNOSIS"):
            state = self.create(kind, kind)
            self.assertEqual(state.subject.subject_kind, kind)
            self.assertEqual(state.root_state.status, "CREATED")
            self.assertEqual(set(state.extension_states), {EXTENSION_ID})
            self.assertNotIn('"mission_id"', json.dumps(state.to_dict()))
            self.assertTrue(self.runtime.verify_projection(state.subject.subject_id)["ok"])
            with self.assertRaises(CoreError): self.runtime.get_state(state.subject.subject_id)
            with self.assertRaises(CoreError): self.runtime.get_composed_state(state.subject.subject_id)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM mission_projection")[0][0], 0)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM events WHERE event_type LIKE 'mission.%' OR event_type LIKE 'session.%'")[0][0], 0)

    def test_duplicate_creation_after_completion_consumes_one_operation(self):
        first = self.create()
        active = self.transition(first, "ACTIVE", "activate-a")
        completed = self.transition(active, "COMPLETED", "finish-a", summary="Actual work receipt supplied separately")
        before = self.durable()
        again = self.create()
        self.assertEqual(again.subject, first.subject)
        self.assertEqual(again.root_state.status, "COMPLETED")
        self.assertEqual(self.durable(), before)
        # Retrying an identical lifecycle receipt reconstructs its original cursor.
        self.jobs.transition(active.subject, expected_seq=active.seq, target_status="COMPLETED", request_id="finish-a", actor=ACTOR, summary="Actual work receipt supplied separately")
        self.assertEqual(self.durable(), before)
        with self.assertRaises(CoreError): self.transition(completed, "ACTIVE", "reopen-a")

    def test_same_operation_changed_intent_or_kind_conflicts(self):
        first = self.create()
        for kind, intent in (("GENERAL_WORK", "Different work"), ("RUNTIME_DIAGNOSIS", "Process one bounded note")):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(CoreError, "COMMAND_ID_CONFLICT"):
                    self.jobs.create(subject_kind=kind, operation_id="operation-a", host_turn_ref=HOST, intent=intent, actor=ACTOR)
        self.assertEqual(self.runtime.get_head_seq(first.subject.subject_id), 1)
        self.assertEqual(self.sql("SELECT COUNT(DISTINCT mission_id) FROM events")[0][0], 1)

    def test_concurrent_same_operation_creates_one_root_event(self):
        def create_once(_):
            return GeneralWorkService(self.new_runtime()).create(subject_kind="GENERAL_WORK",operation_id="raced",host_turn_ref=HOST,intent="same immutable request",actor=ACTOR).subject
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(create_once, range(4)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(self.runtime.get_head_seq(results[0].subject_id), 1)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM commands WHERE status='APPLIED'")[0][0], 1)

    def test_stale_cas_and_cross_job_cursors_cannot_transition(self):
        a = self.create("a"); b = self.create("b")
        self.transition(a, "ACTIVE", "a-active")
        with self.assertRaisesRegex(CoreError, "EXPECTED_SEQ_MISMATCH"):
            self.transition(a, "CANCELLED", "stale-cancel")
        bad = CommandEnvelope("cross-job", "TRANSITION_GENERAL_WORK", a.subject.subject_id, 2, ACTOR,
                              {"subject":b.subject.to_dict(),"from_status":"ACTIVE","target_status":"COMPLETED","summary":"forged","evidence_ref":None})
        result = self.runtime.execute(bad)
        self.assertEqual(result.error_code, "ROOT_REFERENCE_MISMATCH")
        self.assertEqual(self.runtime.get_head_seq(a.subject.subject_id), 2)
        self.assertEqual(self.runtime.get_head_seq(b.subject.subject_id), 1)

    def test_wrong_subject_kind_and_core_mission_commands_are_rejected(self):
        a = self.create()
        with self.assertRaisesRegex(CoreError, "ROOT_REFERENCE_MISMATCH"):
            self.runtime.get_subject_state(SubjectRef("MISSION", a.subject.subject_id))
        for kind in ("CREATE_MISSION", "OPEN_SESSION", "CREATE_PLAN", "CREATE_RUNTIME_DIAGNOSIS"):
            with self.subTest(kind=kind):
                c = CommandEnvelope("cross-"+kind,kind,a.subject.subject_id,1,ACTOR,{"subject":a.subject.to_dict()})
                self.assertFalse(self.runtime.execute(c).ok)
        self.assertEqual(self.runtime.get_head_seq(a.subject.subject_id), 1)
        # Reserved namespace remains unavailable even before a job is created.
        c=CommandEnvelope("fake-mission","CREATE_MISSION","general-work:v1:forged",0,ACTOR,{})
        self.assertEqual(self.runtime.execute(c).error_code,"ROOT_IDENTITY_INVALID")

    def test_mission_stream_cannot_be_claimed_as_job(self):
        self.assertTrue(self.runtime.execute(CommandEnvelope("mission","CREATE_MISSION","real-mission",0,ACTOR,{})).ok)
        c=self.raw_create("GENERAL_WORK","claim-mission",mission_id="real-mission")
        self.assertEqual(self.runtime.execute(c).error_code,"ROOT_ALREADY_EXISTS")
        self.assertEqual(self.runtime.get_head_seq("real-mission"),1)

    def test_root_creation_and_unsupported_reference_payloads_fail_closed(self):
        cases=[{"root_version":2},{"root_version":True},{"creation_command":"CREATE_MISSION"},
               {"subject":{"subject_kind":"MISSION","subject_id":"forged"}},
               {"task_id":"another-job-task"},{"lease_id":"another-job-lease"}]
        for i,changes in enumerate(cases):
            with self.subTest(changes=changes):
                c=self.raw_create("GENERAL_WORK",f"bad-{i}",payload_changes=changes)
                try: result=self.runtime.execute(c); self.assertFalse(result.ok)
                except CoreError: pass
                self.assertEqual(self.runtime.get_head_seq(c.mission_id),0)
        c=self.raw_create("GENERAL_WORK","unowned",command_id="invented",idempotency_key="invented")
        self.assertEqual(self.runtime.execute(c).error_code,"JOB_IDEMPOTENCY_REQUIRED")

    def test_replay_rejects_repeat_forged_and_precreation_root_events(self):
        a=self.create(); event=self.runtime.list_events(a.subject.subject_id)[0]
        state=self.runtime.replay_composed(a.subject.subject_id)
        with self.assertRaisesRegex(CoreError,"ROOT_ALREADY_EXISTS"):
            reduce_composed(state,replace(event,seq=2),self.runtime.extension_registry)
        for altered in (replace(event,entity_id="another-root"),replace(event,payload={**event.payload,"root_version":999}),
                        replace(event,payload={**event.payload,"creation_command":"CREATE_MISSION"})):
            with self.assertRaises(CoreError):
                reduce_composed(initial_composed_state(a.subject.subject_id,self.runtime.extension_registry),altered,self.runtime.extension_registry)
        active=self.transition(a,"ACTIVE","active")
        changed=self.runtime.list_events(a.subject.subject_id)[1]
        with self.assertRaises(CoreError):
            reduce_composed(initial_composed_state(a.subject.subject_id,self.runtime.extension_registry),replace(changed,seq=1),self.runtime.extension_registry)
        b=self.create("other")
        with self.assertRaisesRegex(CoreError,"ROOT_REFERENCE_MISMATCH"):
            reduce_composed(state,replace(changed,payload={**changed.payload,"subject":b.subject.to_dict()}),self.runtime.extension_registry)

    def test_replay_validates_actual_creation_command_row(self):
        a=self.create(); first=self.runtime.list_events(a.subject.subject_id)[0]
        self.sql("UPDATE commands SET command_type='CREATE_MISSION' WHERE command_id=?",(first.command_id,))
        with self.assertRaisesRegex(CoreError,"ROOT_CREATION_PAIR_INVALID"): self.runtime.replay_composed(a.subject.subject_id)
        with self.assertRaises(CoreError): self.runtime.assert_writable_compatible()

    def test_mixed_restart_rebuild_preserves_events_commands_and_hashes(self):
        self.runtime.execute(CommandEnvelope("mission","CREATE_MISSION","real-mission",0,ACTOR,{}))
        a=self.create(); b=self.create("diagnose","RUNTIME_DIAGNOSIS")
        self.transition(a,"ACTIVE","activate")
        before=self.durable(); restarted=self.new_runtime()
        hashes={s:canonical_sha256(restarted.replay_composed(s).to_dict()) for s in ("real-mission",a.subject.subject_id,b.subject.subject_id)}
        self.sql("DELETE FROM general_work_projection")
        with self.assertRaises(CoreError): restarted.verify_projection(a.subject.subject_id)
        rebuilt=restarted.rebuild_projections()
        self.assertEqual(rebuilt["rebuilt"],3)
        self.assertEqual(rebuilt["state_hashes"],hashes)
        self.assertEqual(self.durable(),before)
        for subject in hashes: self.assertTrue(restarted.verify_projection(subject)["ok"])

    def test_transaction_faults_leave_no_partial_root(self):
        for i,point in enumerate(("after_command_insert","after_event_insert","after_projection_apply","before_commit")):
            with self.subTest(point=point):
                def inject(at):
                    if at==point: raise ValueError("intentional transaction fault")
                bad=self.new_runtime(failure_injector=inject); before=self.durable()
                with self.assertRaises(ValueError):
                    GeneralWorkService(bad).create(subject_kind="GENERAL_WORK",operation_id=f"fault-{i}",host_turn_ref=HOST,intent="fault control",actor=ACTOR)
                self.assertEqual(self.durable(),before)

    def test_rebuild_fault_after_clear_or_apply_rolls_back_projections(self):
        capture(self.db)  # mixed old Mission/Goal/Session/Plan state must also survive
        self.create(); self.create("diagnose","RUNTIME_DIAGNOSIS")
        for point in ("after_projection_clear","after_rebuild_projection_apply"):
            with self.subTest(point=point):
                def inject(at):
                    if at==point: raise ValueError("intentional rebuild fault")
                bad=self.new_runtime(failure_injector=inject); before=self.durable()
                with self.assertRaises(ValueError): bad.rebuild_projections()
                self.assertEqual(self.durable(),before)

    def test_omitted_root_owner_fences_writes_and_rebuild_but_allows_scoped_mission_read(self):
        self.runtime.execute(CommandEnvelope("mission","CREATE_MISSION","real-mission",0,ACTOR,{})); a=self.create()
        old_manifests=tuple(m for m in canonical_extension_manifests() if m.extension_id!=EXTENSION_ID)
        old=self.new_runtime(extensions=old_manifests); before=self.durable()
        self.assertEqual(old.get_state("real-mission").mission.mission_id,"real-mission")
        with self.assertRaisesRegex(CoreError,"ROOT_OWNER_UNSUPPORTED"): old.rebuild_projections()
        result=old.execute(CommandEnvelope("other","CREATE_MISSION","new-mission",0,ACTOR,{}))
        self.assertEqual(result.error_code,"ROOT_OWNER_UNSUPPORTED")
        self.assertEqual(self.durable(),before)
        bare=RuntimeService(self.db)
        with self.assertRaises(CoreError): bare.rebuild_projections()

    def test_future_root_version_fences_dispatch_and_preserves_state(self):
        future=replace(general_work_extension(),roots=tuple(replace(r,version=2) for r in ROOTS))
        manifests=tuple(future if m.extension_id==EXTENSION_ID else m for m in canonical_extension_manifests())
        runtime=self.new_runtime(extensions=manifests)
        c=self.raw_create("GENERAL_WORK","future",payload_changes={"root_version":2})
        self.assertTrue(runtime.execute(c).ok)
        current=self.new_runtime(); before=self.durable()
        with self.assertRaisesRegex(CoreError,"ROOT_VERSION_UNSUPPORTED"): current.rebuild_projections()
        self.assertEqual(current.execute(CommandEnvelope("stop","CREATE_MISSION","new",0,ACTOR,{})).error_code,"ROOT_VERSION_UNSUPPORTED")
        self.assertEqual(self.durable(),before)

    def test_registered_applicability_cannot_gain_other_roots(self):
        manifest=general_work_extension()
        with self.assertRaises(CoreError): ExtensionRegistry((replace(manifest,subject_kinds=frozenset({"GENERAL_WORK"})),))
        with self.assertRaises(CoreError): ExtensionRegistry((replace(manifest,roots=(ROOTS[0],replace(ROOTS[0],subject_kind="OTHER",id_prefix="other:")),subject_kinds=frozenset({"GENERAL_WORK","OTHER"})),))

    def test_counterfeit_core_projection_is_detected_and_rebuild_repairs_from_truth(self):
        a=self.create(); before=self.durable()
        self.sql("INSERT INTO goal_projection VALUES(?,?,?)",(a.subject.subject_id,"fake-goal","{}"))
        with self.assertRaisesRegex(CoreError,"ROOT_PROJECTION_CONFLICT"):
            self.runtime.verify_projection(a.subject.subject_id)
        self.runtime.rebuild_projections()
        self.assertEqual(self.durable(),before)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM goal_projection")[0][0],0)

    def test_shared_pure_selection_accepts_typed_subject_without_a_mission(self):
        from aitest_runtime.general_work.scheduling import SubjectReadiness
        from aitest_runtime.r2_4.contracts import TaskReadiness, SchedulingPolicy, LoopBudget, LoopProgress
        from aitest_runtime.r2_4.readiness import select_ready_tasks
        a=self.create(); before=self.durable()
        candidates=(TaskReadiness("local-task-a","READY"),TaskReadiness("local-task-b","READY"))
        view=SubjectReadiness(a.subject,a.seq,candidates)
        policy=SchedulingPolicy("shared-policy",1,2)
        budget=LoopBudget("budget",2,1,"2026-09-12T00:00:00Z",10)
        progress=LoopProgress("loop","budget",0,0,0,"2026-09-10T00:00:00Z","receipt","a"*64)
        self.assertEqual(select_ready_tasks(view,policy,budget,progress),candidates[:1])
        self.assertEqual(select_ready_tasks(view,policy,budget,replace(progress,dispatches_used=1)),())
        self.assertEqual(self.durable(),before)

    def test_unknown_future_event_fences_writes_before_rebuild_clear(self):
        from aitest_runtime.durable_core.event_store import _insert_events
        from aitest_runtime.durable_core.schema import connect
        a=self.create(); first=self.runtime.list_events(a.subject.subject_id)[0]
        # Corruption/newer-writer fixture appends a fact; it never rewrites history.
        conn=connect(self.db)
        try:
            _insert_events(conn,[replace(first,event_id="fixture-future-event",seq=2,event_type="general_work.future.v2")])
        finally:conn.close()
        before=self.durable()
        with self.assertRaisesRegex(CoreError,"ROOT_EVENT_UNSUPPORTED"): self.runtime.rebuild_projections()
        result=self.runtime.execute(CommandEnvelope("unrelated-new","CREATE_MISSION","new",0,ACTOR,{}))
        self.assertEqual(result.error_code,"ROOT_EVENT_UNSUPPORTED")
        self.assertEqual(self.durable(),before)


if __name__=="__main__": unittest.main(verbosity=2)
