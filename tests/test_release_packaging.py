from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rc6_release.mcp_server import handle
from rc6_release.package import BUILD_STATUS, PACKAGE_NAME, build_package, verify_package


class ReleasePackagingTests(unittest.TestCase):
    def test_mcp_handshake_and_governed_mission_tools(self):
        init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "pfc-aitest-rc6")
        listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertTrue({"runtime_status", "mission_create", "mission_status", "mission_checkpoint"}.issubset(names))

    def test_build_and_verify_engineering_candidate(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_package(repo, tmp, "a" * 40, make_zip=True)
            result = verify_package(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["release_status"], BUILD_STATUS)
            manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["bank_field_pass"])
            self.assertEqual(manifest["durable_truth"], "R1_EVENT_STREAM")
            self.assertTrue((Path(tmp) / f"{PACKAGE_NAME}-{'a' * 12}.zip").is_file())

    def test_package_contains_git_bash_entrypoints_and_skill(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_package(repo, tmp, "b" * 40, make_zip=False)
            for name in ("AITEST.sh", "START-AITEST.sh", "STOP-AITEST.sh", "STATUS.sh", "VERIFY.sh"):
                text = (root / name).read_text(encoding="utf-8")
                self.assertTrue(text.startswith("#!/usr/bin/env bash"))
            self.assertTrue((root / ".dsh/skills/pfc-full-chain-test/SKILL.md").is_file())
            self.assertTrue((root / "rc6_release/mcp_server.py").is_file())

    def test_package_excludes_obvious_secret_files(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_package(repo, tmp, "c" * 40, make_zip=False)
            names = {p.name.lower() for p in root.rglob("*") if p.is_file()}
            self.assertNotIn(".env", names)
            self.assertNotIn("credentials.json", names)
            self.assertNotIn("secrets.json", names)


if __name__ == "__main__":
    unittest.main()
