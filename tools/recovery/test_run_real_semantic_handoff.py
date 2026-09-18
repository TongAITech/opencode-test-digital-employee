from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_real_semantic_handoff import (
    find_payload_workspace,
    payload_candidate_ok,
    repository_slug,
    semantic_asset_name,
    workflow_dispatch_command,
)


class RealSemanticHandoffTests(unittest.TestCase):
    def test_repository_slug_accepts_standard_github_origins(self):
        expected = "TongAITech/opencode-test-digital-employee"
        self.assertEqual(repository_slug("https://github.com/TongAITech/opencode-test-digital-employee.git"), expected)
        self.assertEqual(repository_slug("git@github.com:TongAITech/opencode-test-digital-employee.git"), expected)
        self.assertEqual(repository_slug("ssh://git@github.com/TongAITech/opencode-test-digital-employee.git"), expected)

    def test_semantic_asset_name_is_exact_head_and_digest_bound(self):
        head = "a" * 40
        digest = "b" * 64
        self.assertEqual(
            semantic_asset_name(head, digest),
            "REC3-REAL-SEMANTIC-aaaaaaaaaaaa-bbbbbbbbbbbb.json",
        )

    def test_dispatch_carries_exact_semantic_identity_without_credentials(self):
        config = {
            "draft_release_tag": "v1.12.0-recovery-validation-ci",
            "asset_name": "carrier.zip",
            "expected_sha256": "c" * 64,
        }
        command = workflow_dispatch_command(
            "TongAITech/opencode-test-digital-employee",
            "work/v1.13.0-recovery-turnkey-validation",
            config,
            "REC3-REAL-SEMANTIC-aaaaaaaaaaaa-bbbbbbbbbbbb.json",
            "b" * 64,
        )
        joined = " ".join(command)
        self.assertIn("semantic_asset=REC3-REAL-SEMANTIC-aaaaaaaaaaaa-bbbbbbbbbbbb.json", joined)
        self.assertIn("semantic_sha256=" + "b" * 64, joined)
        self.assertIn("expected_sha256=" + "c" * 64, joined)
        for forbidden in ("TOKEN=", "API_KEY=", "PASSWORD=", "AUTH_JSON"):
            self.assertNotIn(forbidden, joined.upper())

    def test_finds_workspace_template_inside_downloaded_carrier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "carrier" / "AITest" / "workspace-template"
            (workspace / ".opencode" / "node_modules").mkdir(parents=True)
            if os.name == "nt":
                (workspace / "runtime" / "python").mkdir(parents=True)
                (workspace / "runtime" / "python" / "python.exe").write_bytes(b"fixture")
            self.assertEqual(find_payload_workspace(root), workspace.resolve())

    def test_payload_candidate_requires_host_tool_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".opencode" / "node_modules").mkdir(parents=True)
            if os.name == "nt":
                (root / "runtime" / "python").mkdir(parents=True)
                self.assertFalse(payload_candidate_ok(root))
                (root / "runtime" / "python" / "python.exe").write_bytes(b"fixture")
            self.assertTrue(payload_candidate_ok(root))

    def test_missing_dispatch_config_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "CI_PACKAGE_CONFIG_MISSING"):
            workflow_dispatch_command("o/r", "branch", {}, "proof.json", "d" * 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
