"""Use subprocesses and disposable native R1 files to probe POSIX locking."""

import json
import os
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission
from rc7_runtime.truth_overlay import append_entity


OWNER = Path(__file__).parent / "fixtures" / "workbench_physical_ledger" / "owner.py"


@unittest.skipUnless(os.name == "posix", "physical-file flock proof requires POSIX; Windows is unqualified")
class PhysicalLedgerWriterTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "ledger.jsonl"
        self.row = self.root / "prepared-row.jsonl"
        append_entity(TruthRuntime(self.row), Mission("M1", "release", "fixture"), release_id="release")
        self.path.touch()
        stat = self.path.stat()
        self.identity = (stat.st_dev, stat.st_ino)

    def args(self, path, epoch):
        device, inode = self.identity
        return [sys.executable, str(OWNER), str(path), str(device), str(inode), str(epoch)]

    def read_reply(self, child):
        ready, _, _ = select.select([child.stdout], [], [], 10)
        self.assertTrue(ready, "physical writer fixture did not reply")
        response = child.stdout.readline().strip()
        self.assertTrue(response, "physical writer fixture exited without replying")
        return response

    def owner(self, path, epoch):
        child = subprocess.Popen(self.args(path, epoch), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.close_owner, child)
        self.assertEqual(self.read_reply(child), "LOCK_HELD")
        return child

    @staticmethod
    def close_owner(child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        child.stdin.close()
        child.stdout.close()

    def candidate(self, path, epoch):
        result = subprocess.run(self.args(path, epoch), input="", text=True, capture_output=True,
                                check=True, timeout=10)
        return result.stdout.splitlines()

    def request(self, child, epoch):
        command = {"epoch": epoch, "row": self.row.read_bytes().hex()}
        child.stdin.write(json.dumps(command) + "\n")
        child.stdin.flush()
        return self.read_reply(child)

    def test_physical_lock_covers_hard_links_and_releases_after_owner_death(self):
        alias = self.root / "alias.jsonl"
        os.link(self.path, alias)
        current = self.owner(self.path, 1)
        for path in (self.path, alias):
            self.assertEqual(self.candidate(path, 2), ["LOCK_BUSY"])
        self.assertEqual(self.path.read_bytes(), b"")

        current.kill()
        self.assertNotEqual(current.wait(timeout=10), 0)
        recovered = self.owner(alias, 2)
        self.assertEqual(self.request(recovered, 1), "STALE_EPOCH")
        self.assertEqual(self.path.read_bytes(), b"")
        self.assertEqual(self.request(recovered, 2), "SYNCED")
        self.assertEqual(self.path.read_bytes(), self.row.read_bytes())
        cold = TruthRuntime(self.path)
        self.assertEqual(len(cold.query("rc7_mission", mission_id="M1")), 1)

    def test_replaced_path_does_not_rebind_the_expected_inode(self):
        current = self.owner(self.path, 1)
        original = self.root / "original.jsonl"
        self.path.rename(original)
        self.path.touch()
        self.assertEqual(self.candidate(self.path, 2), ["FILE_IDENTITY_CHANGED"])
        self.assertEqual(self.request(current, 1), "FILE_IDENTITY_CHANGED")
        self.assertEqual(self.candidate(original, 2), ["LOCK_BUSY"])
        self.assertEqual(self.path.read_bytes(), b"")
        self.assertEqual(original.read_bytes(), b"")

    def test_existing_direct_writer_does_not_participate_in_posix_flock(self):
        self.owner(self.path, 1)
        direct = """
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission
from rc7_runtime.truth_overlay import append_entity
import sys
append_entity(TruthRuntime(sys.argv[1]), Mission("DIRECT", "release", "fixture"), release_id="release")
"""
        subprocess.run([sys.executable, "-c", direct, str(self.path)], check=True, timeout=10)
        cold = TruthRuntime(self.path)
        self.assertEqual(len(cold.query("rc7_mission", mission_id="DIRECT")), 1)
        self.assertEqual(self.candidate(self.path, 2), ["LOCK_BUSY"])
