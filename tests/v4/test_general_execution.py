"""Actual R1 and disk effects with a labeled Host protocol fixture, not L4."""
import copy
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-template/ai-test/runtime"))
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import ActorRef, RuntimeError
from aitest_runtime.general_work.execution import GeneralExecutionService
from aitest_runtime.general_work.execution_contract import execution_transition
from aitest_runtime.general_work.scoped_files import ScopedFiles, sha
from aitest_runtime.hosted_intake import actual_host_user_turn
from aitest_runtime.interaction_admission import decide, parse_proposal
from aitest_runtime.interaction_receipts import R1InteractionOwner
from test_interaction_admission import HostFixture, proposal


class Host(FakeOpenCodeSessionProvider):
    def __init__(self, root, text):
        super().__init__(root)
        self.host = HostFixture(text)
        self.host.messages["u1"]["info"]["time"]["created"] = int(time.time() * 1000)
    def _directory_query(self): return "directory=fixture"
    def _request(self, method, path): return copy.deepcopy(self.host.messages[path.split("/message/")[1].split("?")[0]])
    def call(self, job, action, payload, mid="tool-1", cid="call-1", agent=None):
        e = job.execution; s = e["sessions"][str(e["epoch"])]; sid = s["session_id"]
        self.host.messages[mid] = {"info": {"id": mid, "sessionID": sid, "role": "assistant", "agent": agent or s["agent"]},
            "parts": [{"type": "tool", "tool": "aitest_general_worker", "messageID": mid, "sessionID": sid, "callID": cid,
                       "state": {"status": "running", "input": {"action": action, "payload": payload}}}]}
        return patch.dict(os.environ, {"AITEST_HOST_SESSION_ID": sid, "AITEST_HOST_MESSAGE_ID": mid, "AITEST_HOST_CALL_ID": cid})


def process_call(db, root, sessions, host_messages, payload, barrier, output, crash):
    runtime=create_canonical_runtime(Path(root),db_path=Path(db));host=Host(Path(root),"fixture")
    host.sessions=sessions;host.host.messages=host_messages
    service=GeneralExecutionService(runtime,Path(root),host)
    part=host_messages["parallel"]["parts"][0]
    os.environ.update(AITEST_HOST_SESSION_ID=part["sessionID"],AITEST_HOST_MESSAGE_ID="parallel",AITEST_HOST_CALL_ID="parallel-call")
    if crash: service._write_receipt=lambda *a,**kw:os._exit(73)
    if barrier: barrier.wait(timeout=15)
    result=service.worker_command("write_file",payload)
    if output: output.put(result)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / "workspace"; self.root.mkdir()
        (self.root / "notes").mkdir(); (self.root / "notes/input.txt").write_text("ordinary input")
        self.runtime = create_canonical_runtime(self.root, db_path=Path(self.temp.name) / "private/spine.db")
        self.host = Host(self.root, "把说明写到 notes/result.txt")
        self.service = GeneralExecutionService(self.runtime, self.root, self.host)
        self.owner = R1InteractionOwner(self.runtime)
        self.env = patch.dict(os.environ, {"AITEST_HOST_SESSION_ID": "s1", "AITEST_HOST_MESSAGE_ID": "a1", "AITEST_HOST_CALL_ID": "primary-call"})
        self.env.start()
    def tearDown(self): self.env.stop(); self.temp.cleanup()
    def start(self, intent="GENERAL_WORK", action="write"):
        turn = actual_host_user_turn(self.host)
        op = decide(turn, parse_proposal(proposal(turn.text, intent, action), turn)[0], [], now_ms=int(time.time() * 1000))
        op["operation_text"] = turn.text
        result = self.service.start(op, self.owner)
        self.subject = self.service._subject(result["job_id"]); self.op = op
        return result
    def invoke(self, action, data=None, mid="tool-1", cid="call-1", agent=None):
        payload = {"job_id": self.subject.subject_id, **(data or {})}
        with self.host.call(self.service._job(self.subject), action, payload, mid, cid, agent):
            return self.service.worker_command(action, payload)
    def count(self, table):
        with sqlite3.connect(self.runtime.db_path) as c: return c.execute("SELECT count(*) FROM " + table).fetchone()[0]
    def test_delegation_real_file_read_write_complete_no_mission(self):
        result = self.start(); self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(self.count("mission_projection"), 0); self.assertEqual(len(self.host.sessions), 1)
        read = self.invoke("read_file", {"path": "notes/input.txt"})
        self.assertEqual(read["content"], "ordinary input")
        write = self.invoke("write_file", {"path": "notes/result.txt", "expected_sha256": "MISSING", "content": "真实工程结果"}, "tool-2", "call-2")
        self.assertEqual(write["status"], "COMPLETED"); self.assertEqual((self.root / "notes/result.txt").read_text(), "真实工程结果")
        finish = self.invoke("complete", {"summary": "已生成说明", "result_refs": [{"path": "notes/result.txt", "sha256": write["sha256"]}]}, "tool-3", "call-3")
        self.assertEqual(finish["result_type"], "ENGINEERING_RESULT"); self.assertEqual(self.service._job(self.subject).status, "COMPLETED")
        self.assertEqual(self.count("mission_projection"), 0); self.assertEqual(self.runtime.rebuild_projections()["rebuilt"], 2)
        self.assertTrue(self.runtime.verify_projection(self.subject.subject_id)["ok"])
    def test_duplicate_start_and_tool_do_not_spawn_or_write_again(self):
        self.start(); before = len(self.host.messages)
        self.service.start(self.op, self.owner)
        self.assertEqual(len(self.host.sessions), 1); self.assertEqual(len(self.host.messages), before)
        data = {"path": "notes/a.txt", "expected_sha256": "MISSING", "content": "one"}
        first = self.invoke("write_file", data); seq = self.runtime.get_head_seq(self.subject.subject_id)
        second = self.invoke("write_file", data)
        self.assertEqual(first, second); self.assertEqual(self.runtime.get_head_seq(self.subject.subject_id), seq)
    def test_fake_primary_old_session_agent_call_and_payload_are_fenced(self):
        self.start(); seq = self.runtime.get_head_seq(self.subject.subject_id)
        payload = {"job_id": self.subject.subject_id, "path": "notes/input.txt"}
        with self.assertRaisesRegex(RuntimeError, "STALE_CALLER"): self.service.worker_command("read_file", payload)
        with self.assertRaisesRegex(RuntimeError, "HOST_AGENT_MISMATCH"): self.invoke("read_file", {"path": "notes/input.txt"}, agent="aitest-director")
        with self.host.call(self.service._job(self.subject), "read_file", payload):
            with self.assertRaisesRegex(RuntimeError, "ACTUAL_TOOL_CALL_REQUIRED"):
                self.service.worker_command("read_file", {**payload, "offset": 0})
        self.assertEqual(self.runtime.get_head_seq(self.subject.subject_id), seq)
    def test_read_only_lease_cannot_write_and_terminal_has_no_fallback(self):
        self.start(action="read")
        with self.assertRaisesRegex(RuntimeError, "CAPABILITY_DENIED"):
            self.invoke("write_file", {"path": "notes/a", "expected_sha256": "MISSING", "content": "x"})
        self.assertFalse((self.root / "notes/a").exists())
    def test_diagnosis_is_distinct_and_process_missing_is_technical_failure(self):
        self.start("AITEST_DIAGNOSIS", "diagnose")
        result = self.invoke("terminal", {"argv": ["python", "-c", "open('should-not-exist','w').write('x')"], "cwd": "."})
        self.assertEqual(result["status"], "FAILED"); self.assertEqual(result["reason"], "GENERAL_OS_CONFINEMENT_UNAVAILABLE")
        self.assertEqual(result["result_type"], "RUNTIME_DIAGNOSIS_RESULT"); self.assertFalse((self.root / "should-not-exist").exists())
        self.assertEqual(self.count("mission_projection"), 0)
    def test_scope_escape_protected_and_expected_hash_negative(self):
        self.start()
        for i, path in enumerate(["../outside", "notes/../../outside", "ai-test/state/r1.db", ".opencode/config.json", "notes/.env", "notes/name:stream"]):
            result = self.invoke("write_file", {"path": path, "expected_sha256": "MISSING", "content": "x"}, "t"+str(i), "c"+str(i))
            self.assertEqual(result["status"], "FAILED")
        result = self.invoke("write_file", {"path": "notes/input.txt", "expected_sha256": "f"*64, "content": "bad"}, "last", "last")
        self.assertEqual(result["reason"], "GENERAL_WRITE_CONFLICT"); self.assertEqual((self.root / "notes/input.txt").read_text(), "ordinary input")
    def test_symlink_hardlink_and_search_start_escape_denied(self):
        self.start(); outside = Path(self.temp.name) / "outside"; outside.mkdir(); (outside / "a").write_text("private sentinel")
        (self.root / "notes/link").symlink_to(outside, target_is_directory=True)
        os.link(outside / "a", self.root / "notes/hard")
        for i, path in enumerate(["notes/link/a", "notes/hard"]):
            result = self.invoke("read_file", {"path": path}, "t"+str(i), "c"+str(i)); self.assertEqual(result["status"], "FAILED")
        result = self.invoke("search_files", {"path": "notes/link", "pattern": "sentinel"}, "search", "search")
        self.assertEqual(result["status"], "FAILED"); self.assertNotIn("private sentinel", json.dumps(result))
    def test_old_lifecycle_completion_shortcut_rejected(self):
        self.start()
        with self.assertRaisesRegex(RuntimeError, "COMPLETION_RECEIPT_REQUIRED"):
            self.service.jobs.transition(self.subject, expected_seq=self.runtime.get_head_seq(self.subject.subject_id), request_id="bypass",
                target_status="COMPLETED", actor=ActorRef("SYSTEM", "tester"), summary="fake done")
    def test_pending_prompt_reconciles_actual_host_readback_once(self):
        original = self.host.send_context
        def delivered_then_error(**kwargs): original(**kwargs); raise OSError("lost acknowledgment")
        with patch.object(self.host, "send_context", delivered_then_error):
            with self.assertRaises(OSError): self.start()
        result = self.start(); self.assertEqual(result["status"], "ACTIVE"); self.assertEqual(len(self.host.messages), 1)
    def test_receipt_crash_gap_rebuild_restores_without_another_write(self):
        self.start(); original = self.service._record
        def fail(subject, operation, data):
            if operation == "CALL_RECEIPT": raise KeyboardInterrupt("receipt boundary")
            return original(subject, operation, data)
        with patch.object(self.service, "_record", fail):
            with self.assertRaises(KeyboardInterrupt):
                self.invoke("write_file", {"path": "notes/gap", "expected_sha256": "MISSING", "content": "one"})
        self.runtime.rebuild_projections()
        service = GeneralExecutionService(create_canonical_runtime(self.root, db_path=self.runtime.db_path), self.root, self.host)
        service.supervise_once()
        call = next(iter(service._job(self.subject).execution["calls"].values()))
        self.assertEqual(call["state"], "RECEIPTED"); self.assertEqual((self.root / "notes/gap").read_text(), "one")
    def test_call_digest_inconsistency_rejected_in_replay_transition(self):
        self.start(); self.invoke("read_file", {"path": "notes/input.txt"})
        state = self.service._job(self.subject); call = copy.deepcopy(next(iter(state.execution["calls"].values())))
        for key in ("state", "receipt"): call.pop(key)
        call["request_digest"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "CALL_DIGEST_MISMATCH"):
            execution_transition(state, {"subject": self.subject.to_dict(), "operation": "CALL_CLAIM", "data": call})
    def test_actual_user_named_config_can_change_but_protected_config_cannot(self):
        self.host.host.messages["u1"]["parts"][0]["text"] = "修改 settings.json"
        (self.root / "settings.json").write_text('{"theme":"light"}')
        self.start()
        prior = sha((self.root / "settings.json").read_bytes())
        result = self.invoke("write_file", {"path": "settings.json", "expected_sha256": prior, "content": '{"theme":"dark"}'})
        self.assertEqual(result["status"], "COMPLETED"); self.assertEqual(json.loads((self.root / "settings.json").read_text())["theme"], "dark")
        broker = ScopedFiles(self.root, ["notes"], Path(self.temp.name), ["opencode.json", "ai-test/runtime/a.py"])
        for target in ["opencode.json", "ai-test/runtime/a.py"]:
            with self.assertRaisesRegex(RuntimeError, "PROTECTED_OBJECT"):
                broker.write(target, "MISSING", "overwrite", "protected-test")
    def test_file_effect_before_cache_recovers_by_postimage_without_rewrite(self):
        self.start()
        with patch.object(self.service, "_write_receipt", side_effect=KeyboardInterrupt("after disk write")):
            with self.assertRaises(KeyboardInterrupt): self.invoke("write_file", {"path": "notes/no-cache", "expected_sha256": "MISSING", "content": "one"})
        before = (self.root / "notes/no-cache").stat().st_mtime_ns
        self.service.supervise_once()
        call = next(iter(self.service._job(self.subject).execution["calls"].values()))
        self.assertEqual(call["receipt"]["status"], "RECONCILED")
        self.assertEqual((self.root / "notes/no-cache").stat().st_mtime_ns, before)
    def test_complete_receipt_before_lifecycle_recovers_without_user_turn(self):
        self.start(); original = self.service._record
        written = self.invoke("write_file", {"path": "notes/result.txt", "expected_sha256": "MISSING", "content": "done"}, "w", "w")
        def fail(subject, operation, data):
            if operation == "COMPLETE": raise KeyboardInterrupt("after complete receipt")
            return original(subject, operation, data)
        with patch.object(self.service, "_record", fail):
            with self.assertRaises(KeyboardInterrupt): self.invoke("complete", {"summary": "工程解释完成", "result_refs": [{"path": "notes/result.txt", "sha256": written["sha256"]}]})
        self.assertEqual(self.service._job(self.subject).status, "ACTIVE")
        self.service.supervise_once()
        self.assertEqual(self.service._job(self.subject).status, "COMPLETED")
    def test_empty_write_or_run_completion_cannot_claim_work_done(self):
        self.start()
        result = self.invoke("complete", {"summary": "全部完成"})
        self.assertEqual(result["status"], "FAILED"); self.assertEqual(result["reason"], "GENERAL_COMPLETION_EFFECT_REQUIRED")
        self.assertEqual(self.service._job(self.subject).status, "ACTIVE"); self.assertFalse((self.root / "notes/result.txt").exists())
    def test_read_without_cache_crash_gets_fresh_read_receipt(self):
        self.start()
        with patch.object(self.service, "_write_receipt", side_effect=KeyboardInterrupt("after read")):
            with self.assertRaises(KeyboardInterrupt): self.invoke("read_file", {"path": "notes/input.txt"})
        self.service.supervise_once()
        call = next(iter(self.service._job(self.subject).execution["calls"].values()))
        self.assertEqual(call["state"], "RECEIPTED"); self.assertEqual(call["receipt"]["status"], "RECONCILED")
        self.assertEqual(self.service._read_receipt(call)["content"], "ordinary input")
    def test_created_before_prepare_crash_restores_from_r1_only(self):
        with patch.object(self.service, "_prepare_created", side_effect=KeyboardInterrupt("before prepare")):
            with self.assertRaises(KeyboardInterrupt): self.start()
        with sqlite3.connect(self.runtime.db_path) as c: job_id = c.execute("SELECT job_id FROM general_work_projection").fetchone()[0]
        self.subject = self.service._subject(job_id)
        self.assertEqual(self.service._job(self.subject).status, "CREATED")
        self.host.host.messages.clear()  # original conversation is unavailable
        self.service.supervise_once()
        self.assertEqual(self.service._job(self.subject).status, "ACTIVE"); self.assertEqual(len(self.host.sessions), 1)
        self.assertEqual(len(self.host.messages), 1)
    def test_old_event_owner_rejects_write_and_rebuild_without_database_changes(self):
        from dataclasses import replace
        from aitest_runtime.canonical_runtime import canonical_extension_manifests
        from aitest_runtime.durable_core import CommandEnvelope
        from aitest_runtime.interaction_receipts import EXTENSION_ID, GENERAL_INTENT_EVENT
        self.start()
        manifests = []
        for m in canonical_extension_manifests():
            if m.extension_id == EXTENSION_ID:
                m = replace(m, extension_version="1.0.0", event_types=m.event_types - {GENERAL_INTENT_EVENT},
                    roots=tuple(replace(r, event_types=r.event_types - {GENERAL_INTENT_EVENT}) for r in m.roots))
            manifests.append(m)
        old = create_canonical_runtime(self.root, db_path=self.runtime.db_path, extensions=manifests)
        def snapshot():
            with sqlite3.connect(self.runtime.db_path) as c: return list(c.iterdump())
        before = snapshot()
        with self.assertRaisesRegex(RuntimeError, "ROOT_EVENT_UNSUPPORTED"): old.assert_writable_compatible()
        with self.assertRaisesRegex(RuntimeError, "ROOT_EVENT_UNSUPPORTED"): old.rebuild_projections()
        result = old.execute(CommandEnvelope("old-create", "CREATE_MISSION", "old-mission", 0, ActorRef("SYSTEM", "fixture"), {}))
        self.assertEqual(result.error_code, "ROOT_EVENT_UNSUPPORTED")
        self.assertEqual(snapshot(), before)
    def test_general_intent_and_claim_commit_atomically(self):
        from aitest_runtime.interaction_receipts import ReducerContribution, GENERAL_INTENT_EVENT
        original = ReducerContribution.reduce
        def fail(reducer, state, event, core):
            if event.event_type == GENERAL_INTENT_EVENT: raise KeyboardInterrupt("before second event reduce")
            return original(reducer, state, event, core)
        with patch.object(ReducerContribution, "reduce", fail):
            with self.assertRaises(KeyboardInterrupt): self.start()
        self.assertEqual(self.count("events"), 0); self.assertEqual(self.count("commands"), 0)
        self.assertEqual(self.count("interaction_operation_projection"), 0)
        def inject(point):
            if point == "after_event_insert": raise KeyboardInterrupt("after both inserts before commit")
        broken = create_canonical_runtime(self.root, db_path=self.runtime.db_path, failure_injector=inject)
        service = GeneralExecutionService(broken, self.root, self.host)
        with patch.object(self, "service", service), patch.object(self, "owner", R1InteractionOwner(broken)):
            with self.assertRaises(KeyboardInterrupt): self.start()
        self.assertEqual(self.count("events"), 0); self.assertEqual(self.count("commands"), 0)
        self.start(); self.assertEqual(self.count("interaction_operation_projection"), 1)
        with sqlite3.connect(self.runtime.db_path) as c:
            rows = c.execute("SELECT command_id FROM events WHERE event_type IN ('interaction.operation_claimed.v1','interaction.general_intent_recorded.v1')").fetchall()
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0], rows[1])
    def test_postinstall_validation_error_with_residual_never_releases_effect_fence(self):
        # Actual R1/files, injected broker boundary; not a Windows kernel proof.
        self.start()
        def unknown(broker, path, expected, content, call_key):
            folder=broker.private/"general-backups"/call_key;folder.mkdir(parents=True)
            (folder/"transaction.json").write_text(json.dumps({"temporary_name":".aitest-injected.tmp"}))
            (self.root/"notes/.aitest-injected.tmp.displaced").write_text("human edit")
            (self.root/path).write_text(content)
            raise RuntimeError("GENERAL_FILE_BYTE_BUDGET","post-install validation failed")
        with patch.object(ScopedFiles,"write",unknown):
            with self.assertRaisesRegex(RuntimeError,"EFFECT_RECONCILIATION_REQUIRED"):
                self.invoke("write_file",{"path":"notes/input.txt","expected_sha256":sha(b"ordinary input"),"content":"worker"})
        for _ in range(2):self.service.supervise_once()
        call=next(iter(self.service._job(self.subject).execution["calls"].values()))
        self.assertEqual(call["state"],"CLAIMED");self.assertIsNone(call["receipt"])
        with self.assertRaisesRegex(RuntimeError,"EFFECT_RECONCILIATION_REQUIRED"):
            self.invoke("read_file",{"path":"notes/input.txt"},"later","later")
        self.assertEqual((self.root/"notes/.aitest-injected.tmp.displaced").read_text(),"human edit")
    @unittest.skipUnless(os.name == "nt", "actual Windows ReplaceFileW required")
    def test_windows_postswap_runtime_error_remains_unresolved(self):
        from aitest_runtime.general_work import scoped_files
        self.start();target=self.root/"notes/input.txt";original=scoped_files.windows_replace
        human=b"H"*(scoped_files.MAX_FILE+1)
        def race(*args):
            target.write_bytes(human)
            return original(*args)
        with patch.object(scoped_files,"windows_replace",race):
            with self.assertRaisesRegex(RuntimeError,"EFFECT_RECONCILIATION_REQUIRED"):
                self.invoke("write_file",{"path":"notes/input.txt","expected_sha256":sha(b"ordinary input"),"content":"worker"})
        for _ in range(2):
            self.service.supervise_once()
            call=next(iter(self.service._job(self.subject).execution["calls"].values()))
            self.assertEqual(call["state"],"CLAIMED");self.assertIsNone(call["receipt"])
        with self.assertRaisesRegex(RuntimeError,"EFFECT_RECONCILIATION_REQUIRED"):
            self.invoke("read_file",{"path":"notes/input.txt"},"next","next")
        self.assertEqual(list((self.root/"notes").glob(".aitest-*.displaced"))[0].read_bytes(),human)
    def test_claim_before_create_recovers_without_host_history(self):
        with patch.object(self.service.jobs, "create", side_effect=KeyboardInterrupt("after admission claim")):
            with self.assertRaises(KeyboardInterrupt): self.start()
        self.assertEqual(self.count("interaction_operation_projection"), 1)
        self.assertEqual(self.count("general_work_projection"), 0)
        self.host.host.messages.clear()
        self.runtime.rebuild_projections()
        restarted = GeneralExecutionService(create_canonical_runtime(self.root, db_path=self.runtime.db_path), self.root, self.host)
        result = restarted.supervise_once()
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["status"], "ACTIVE")
        subject = restarted._subject(result["jobs"][0]["job_id"])
        job = restarted._job(subject)
        self.assertEqual(job.operation_text, "把说明写到 notes/result.txt")
        self.assertEqual(self.owner.receipt(job.operation_id)["state"], "COMPLETED")
        restarted.supervise_once()
        self.assertEqual(self.count("general_work_projection"), 1)
        self.assertEqual(self.count("mission_projection"), 0)
        self.assertEqual(len(self.host.sessions), 1); self.assertEqual(len(self.host.messages), 1)
    def test_claim_recovery_does_not_renew_expired_user_authority(self):
        from datetime import timedelta
        with patch.object(self.service.jobs, "create", side_effect=KeyboardInterrupt("after claim")):
            with self.assertRaises(KeyboardInterrupt): self.start()
        future = (datetime.now(timezone.utc) + timedelta(hours=9)).isoformat()
        with patch("aitest_runtime.general_work.execution.now", return_value=future):
            result = self.service.supervise_once()
        self.assertEqual(result["admission_recovery_errors"][0]["reason"], "GENERAL_EXECUTION_LEASE_EXPIRED")
        self.assertEqual(self.count("general_work_projection"), 0); self.assertEqual(len(self.host.sessions), 0)
    def test_completion_before_cache_recovers_and_rechecks_changed_reference(self):
        for action, change in [("checkpoint", False), ("complete", True), ("complete", False)]:
            with self.subTest(action=action, changed=change):
                if not hasattr(self, "subject"): self.start()
                if not (self.root / "notes/result.txt").exists():
                    written = self.invoke("write_file", {"path":"notes/result.txt", "expected_sha256":"MISSING", "content":"done"}, "write", "write")
                refs = [{"path":"notes/result.txt", "sha256":written["sha256"]}]
                data = {"summary":"已完成验证", "result_refs" if action == "complete" else "artifact_refs":refs}
                key = action + str(change)
                with patch.object(self.service, "_write_receipt", side_effect=KeyboardInterrupt("before result cache")):
                    with self.assertRaises(KeyboardInterrupt): self.invoke(action, data, key, key)
                if change: (self.root / "notes/result.txt").write_text("human edit")
                mtime = (self.root / "notes/result.txt").stat().st_mtime_ns
                self.service.supervise_once()
                call = list(self.service._job(self.subject).execution["calls"].values())[-1]
                self.assertEqual(call["state"], "RECEIPTED")
                if change:
                    self.assertEqual(call["receipt"]["status"], "FAILED")
                    self.assertEqual(self.service._read_receipt(call)["reason"], "GENERAL_RESULT_REFERENCE_CHANGED")
                    self.assertEqual(self.service._job(self.subject).status, "ACTIVE")
                else:
                    self.assertEqual(call["receipt"]["status"], "COMPLETED")
                    self.assertEqual(self.service._job(self.subject).status, "COMPLETED" if action == "complete" else "ACTIVE")
                self.assertEqual((self.root / "notes/result.txt").stat().st_mtime_ns, mtime)
                if change: (self.root / "notes/result.txt").write_text("done")
    def test_two_real_processes_produce_one_file_effect_and_one_call(self):
        self.start();payload={"job_id":self.subject.subject_id,"path":"notes/parallel","expected_sha256":"MISSING","content":"one"}
        self.host.call(self.service._job(self.subject),"write_file",payload,"parallel","parallel-call")
        ctx=multiprocessing.get_context("spawn");barrier=ctx.Barrier(2);output=ctx.Queue()
        children=[ctx.Process(target=process_call,args=(str(self.runtime.db_path),str(self.root),self.host.sessions,self.host.host.messages,payload,barrier,output,False)) for _ in range(2)]
        try:
            for child in children:child.start()
            results=[output.get(timeout=25) for _ in children]
            for child in children:child.join(timeout=10);self.assertEqual(child.exitcode,0)
            self.assertEqual(results[0],results[1]);self.assertEqual(len(self.service._job(self.subject).execution["calls"]),1)
            self.assertEqual((self.root/"notes/parallel").read_text(),"one")
        finally:
            for child in children:
                if child.is_alive():child.terminate();child.join()
    def test_real_process_death_after_disk_effect_recovers_without_rewrite(self):
        self.start();payload={"job_id":self.subject.subject_id,"path":"notes/parallel","expected_sha256":"MISSING","content":"one"}
        self.host.call(self.service._job(self.subject),"write_file",payload,"parallel","parallel-call")
        ctx=multiprocessing.get_context("spawn")
        child=ctx.Process(target=process_call,args=(str(self.runtime.db_path),str(self.root),self.host.sessions,self.host.host.messages,payload,None,None,True))
        child.start();child.join(timeout=25)
        if child.is_alive():child.terminate();child.join();self.fail("worker failed to reach crash boundary")
        self.assertEqual(child.exitcode,73);before=(self.root/"notes/parallel").stat().st_mtime_ns
        restarted=GeneralExecutionService(create_canonical_runtime(self.root,db_path=self.runtime.db_path),self.root,self.host)
        restarted.supervise_once()
        call=next(iter(restarted._job(self.subject).execution["calls"].values()))
        self.assertEqual(call["receipt"]["status"],"RECONCILED");self.assertEqual((self.root/"notes/parallel").stat().st_mtime_ns,before)
    def test_idle_has_one_bounded_wake_after_grace_and_busy_never_wakes(self):
        from datetime import timedelta
        self.start();sid=next(iter(self.host.sessions))
        self.service.supervise_once();self.assertEqual(len(self.host.messages),1)
        future=(datetime.now(timezone.utc)+timedelta(seconds=4)).isoformat()
        with patch("aitest_runtime.general_work.execution.now",return_value=future):
            self.host.set_observation(sid,activity_state="busy")
            self.service.supervise_once();self.assertEqual(len(self.host.messages),1)
            self.host.set_observation(sid,activity_state="idle")
            self.service.supervise_once();self.assertEqual(len(self.host.messages),2)
            result=self.service.supervise_once();self.assertEqual(len(self.host.messages),2)
            self.assertEqual(result["jobs"][0]["reason"],"DIAGNOSIS_REQUIRED_NO_PROGRESS")
    def test_receipt_cache_corruption_does_not_replay_or_repeat_write(self):
        self.start();data={"path":"notes/a","expected_sha256":"MISSING","content":"one"}
        self.invoke("write_file",data);call=next(iter(self.service._job(self.subject).execution["calls"].values()))
        self.service._cache(call["call_key"]).write_text('{"status":"COMPLETED","fake":true}')
        before=(self.root/"notes/a").stat().st_mtime_ns
        with self.assertRaisesRegex(RuntimeError,"CACHE_CORRUPTED"):self.invoke("write_file",data)
        self.assertEqual((self.root/"notes/a").stat().st_mtime_ns,before)


class FileConflictTests(unittest.TestCase):
    def test_oversized_concurrent_displaced_file_is_never_deleted(self):
        if os.name == "nt": self.skipTest("POSIX exchange oracle")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"root";root.mkdir();(root/"notes").mkdir();target=root/"notes/a";target.write_text("before")
            broker=ScopedFiles(root,["notes"],Path(tmp)/"private")
            from aitest_runtime.general_work import scoped_files
            original=scoped_files.exchange
            injected=False
            def race(*args):
                nonlocal injected
                if not injected: target.write_bytes(b"H"*(scoped_files.MAX_FILE+1));injected=True
                return original(*args)
            with patch.object(scoped_files,"exchange",race):
                with self.assertRaisesRegex(RuntimeError,"WRITE_CONFLICT"):broker.write("notes/a",sha(b"before"),"worker","large-edit")
            self.assertEqual(target.stat().st_size,scoped_files.MAX_FILE+1)
            self.assertEqual(target.read_bytes(),b"H"*(scoped_files.MAX_FILE+1))
            with self.assertRaisesRegex(RuntimeError,"PROTECTED_OBJECT"):broker.read("notes/.aitest-private.tmp")
    @unittest.skipUnless(os.name == "nt", "actual Windows ReplaceFileW required")
    def test_windows_displaced_survives_oversize_or_backup_failure(self):
        from aitest_runtime.general_work import scoped_files
        for large in (False, True):
            with self.subTest(oversized=large), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/"root";root.mkdir();(root/"notes").mkdir();target=root/"notes/a";target.write_text("before")
                broker=ScopedFiles(root,["notes"],Path(tmp)/"private")
                original=scoped_files.windows_replace; private_write=scoped_files._private_write
                human=b"H"*(scoped_files.MAX_FILE+1) if large else b"human edit"
                def race(*args):
                    target.write_bytes(human)
                    return original(*args)
                def fail_backup(path, data):
                    if path.name == "concurrent-edit.bin": raise OSError("injected backup failure")
                    return private_write(path, data)
                with patch.object(scoped_files, "windows_replace", race), patch.object(scoped_files, "_private_write", fail_backup):
                    with self.assertRaises((RuntimeError,OSError)): broker.write("notes/a",sha(b"before"),"worker","windows-race")
                retained=list((root/"notes").glob(".aitest-*.displaced"))
                self.assertEqual(len(retained),1);self.assertEqual(retained[0].read_bytes(),human)
    def test_atomic_displacement_detects_last_window_external_edit(self):
        if os.name == "nt": self.skipTest("POSIX atomic exchange fault injection; Windows has a separate CI oracle")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"; root.mkdir(); (root / "notes").mkdir(); target = root / "notes/a"; target.write_text("before")
            broker = ScopedFiles(root, ["notes"], Path(tmp) / "private")
            from aitest_runtime.general_work import scoped_files
            original = scoped_files.exchange; first = True
            def race(*args):
                nonlocal first
                if first: target.write_text("human edit"); first = False
                return original(*args)
            with patch.object(scoped_files, "exchange", race):
                with self.assertRaisesRegex(RuntimeError, "WRITE_CONFLICT"): broker.write("notes/a", sha(b"before"), "worker", "fixture-call")
            self.assertEqual(target.read_text(), "human edit")
            self.assertEqual((Path(tmp) / "private/general-backups/fixture-call/concurrent-edit.bin").read_text(), "human edit")


if __name__ == "__main__": unittest.main()
