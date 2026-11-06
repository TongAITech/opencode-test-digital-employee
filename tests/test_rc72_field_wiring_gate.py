"""RC7.2 field launch is blocked when the generated DSH patch is RC7-only."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rc7_release.rc72_field_wiring_gate import evaluate_wiring, main


SHA = "a" * 40


class RC72FieldWiringGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "SOURCE_COMMIT").write_text(SHA + "\n", encoding="utf-8")
        self.patch = self.root / "state" / "rc7-dsh.patch.yml"
        self.patch.parent.mkdir()

    def _patch(self, server_name, module):
        self.patch.write_text(
            "plugins:\n"
            "  - id: pfc-mcp\n"
            "    config:\n"
            "      serverName: %s\n" % server_name
            + "      command: 'python.exe'\n"
            + "      args: ['-m', '%s']\n" % module,
            encoding="utf-8",
        )

    def test_legacy_rc7_mcp_is_blocked(self):
        self._patch("pfc_aitest_rc7", "rc7_release.mcp_server_authorized")
        before = self.patch.read_bytes()
        result = evaluate_wiring(package_root=self.root, patch_path=self.patch)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("RC72_NATIVE_MISSION_HOST_NOT_WIRED", result["reasons"])
        self.assertIn("RC7_ONLY_MCP_ROUTE_ACTIVE", result["reasons"])
        self.assertFalse(result["field_verified"])
        self.assertFalse(result["mission_started"])
        self.assertEqual(before, self.patch.read_bytes())

    def test_native_route_is_not_field_pass(self):
        self._patch("pfc_aitest_rc72", "rc7_release.mcp_server_rc72_authorized")
        native = self.root / "rc7_release" / "mcp_server_rc72_authorized.py"
        native.parent.mkdir()
        native.write_text("# synthetic payload presence only; not field evidence\n", encoding="utf-8")
        result = evaluate_wiring(package_root=self.root, patch_path=self.patch)
        self.assertEqual("NATIVE_ROUTE_PRESENT_NOT_FIELD_VERIFIED", result["status"])
        self.assertEqual([], result["reasons"])
        self.assertFalse(result["bank_final"])
        self.assertFalse(result["field_verified"])

    def test_fake_route_without_implementation_is_blocked(self):
        self._patch("pfc_aitest_rc72", "rc7_release.mcp_server_rc72_authorized")
        result = evaluate_wiring(package_root=self.root, patch_path=self.patch)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("RC72_NATIVE_MCP_IMPLEMENTATION_MISSING", result["reasons"])

    def test_naming_only_cannot_replace_real_entrypoint(self):
        self._patch("pfc_aitest_rc72", "rc7_release.mcp_server_authorized")
        result = evaluate_wiring(package_root=self.root, patch_path=self.patch)
        self.assertEqual("BLOCKED", result["status"])

    def test_missing_source_and_patch_are_blocked(self):
        (self.root / "SOURCE_COMMIT").unlink()
        result = evaluate_wiring(package_root=self.root, patch_path=self.patch)
        self.assertIn("RC72_SOURCE_COMMIT_MISSING_OR_INVALID", result["reasons"])
        self.assertIn("RC72_GENERATED_DSH_MCP_PATCH_MISSING", result["reasons"])

    def test_rc72_launcher_enforces_gate_without_changing_rc7_default(self):
        repo = Path(__file__).resolve().parents[1]
        field = (repo / "packaging" / "rc7.2" / "AITEST.sh").read_text(encoding="utf-8")
        legacy = (repo / "packaging" / "rc7" / "AITEST.sh").read_text(encoding="utf-8")
        self.assertIn("export PFC_RC72_REQUIRE_NATIVE_HOST=1", field)
        self.assertIn('if [[ "${PFC_RC72_REQUIRE_NATIVE_HOST:-0}" == "1" ]]', legacy)
        self.assertIn("rc7_release.rc72_field_wiring_gate", legacy)
        self.assertIn("--require-native", legacy)
        self.assertLess(legacy.index("--require-native"), legacy.index("exec dsh"))

    def test_cli_requires_native_and_saves_only_diagnostic(self):
        self._patch("pfc_aitest_rc7", "rc7_release.mcp_server_authorized")
        out = self.root / "state" / "field-wiring.json"
        self.assertEqual(
            3, main([
                "--package-root", str(self.root), "--patch", str(self.patch),
                "--output", str(out), "--require-native",
            ])
        )
        recorded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual("BLOCKED", recorded["status"])
        self.assertFalse((self.root / "runtime-state" / "r1" / "event-stream.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
