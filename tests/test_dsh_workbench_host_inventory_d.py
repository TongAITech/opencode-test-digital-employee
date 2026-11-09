"""WB-D01 package manifest source inspection: no profile reads, no field QA."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "dsh_workbench"))
from wb_d_manifest_inspector import (
    MANIFESTS, InventoryError, inspect, main
)


class TestDHostManifestInventory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def manifest(self, body, relative="package.json"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        return path

    def test_known_manifest_returns_only_allowlisted_fields_and_no_secrets(self):
        self.manifest(dict(name="@deepseek-ai/dsh", version="1.18.26",
                           engines={"node": ">=20.0.0"}, exports={"./client": "./secret"},
                           dsh={"bundle": {"patch": "secret"}},
                           private_access_key="DONT_LOG_THIS_TOKEN",
                           config={"model_key": "sk-proj-fake-private"}))
        report = inspect(self.root, ["package.json"])
        row = report["observations"][0]
        self.assertEqual(row["result"], "METADATA_OBSERVED")
        self.assertEqual(row["metadata"]["version"], "1.18.26")
        self.assertTrue(row["metadata"]["client_export_declared"])
        self.assertTrue(row["metadata"]["dsh_bundle_metadata_declared"])
        text = json.dumps(report)
        for secret in ("DONT_LOG_THIS_TOKEN", "sk-proj-fake-private", "./secret", str(self.root)):
            self.assertNotIn(secret, text)
        self.assertFalse(report["field_verified"])
        self.assertFalse(report["dsh_1_18_26_compatible"])
        self.assertEqual(report["model_credentials"], "NOT_READ_OR_STORED")

    def test_no_package_is_observed_not_compatible(self):
        report = inspect(self.root)
        self.assertEqual(report["result"], "NO_METADATA_OBSERVED")
        self.assertEqual(len(report["observations"]), len(MANIFESTS))
        self.assertTrue(all(x["result"] == "NOT_FOUND" for x in report["observations"]))
        self.assertFalse(report["bank_final"])

    def test_non_allowlisted_manifest_cannot_read_config(self):
        self.manifest({"name": "secret", "version": "1.0.0"}, relative="profile/secret/package.json")
        with self.assertRaisesRegex(InventoryError, "MANIFEST_NOT_ALLOWLISTED"):
            inspect(self.root, ["profile/secret/package.json"])
        for p in ("/etc/passwd", "../package.json", "node_modules/../../../secret.json"):
            with self.assertRaisesRegex(InventoryError, "MANIFEST_NOT_ALLOWLISTED"):
                inspect(self.root, [p])

    def test_duplicate_manifest_request_rejected(self):
        with self.assertRaisesRegex(InventoryError, "DUPLICATE_MANIFEST_REQUEST"):
            inspect(self.root, ["package.json", "package.json"])

    def test_nested_symlink_to_outside_never_read(self):
        self.manifest({"name": "outside", "version": "1.0.0"})
        path = self.root / "node_modules"
        try:
            path.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink denied on this filesystem")
        with self.assertRaisesRegex(InventoryError, "SYMLINK_NOT_ALLOWED"):
            inspect(self.root, ["node_modules/@deepseek-ai/dsh/package.json"])

    def test_root_symlink_rejected(self):
        link = self.root.parent / (self.root.name + "-link")
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink denied on this filesystem")
        self.addCleanup(lambda: link.unlink(missing_ok=True))
        with self.assertRaisesRegex(InventoryError, "ROOT_NOT_LOCAL_DIRECTORY"):
            inspect(link, ["package.json"])

    def test_duplicate_json_keys_rejected_without_payload(self):
        self.manifest('{"name":"a","version":"1.0.0","version":"2.0.0"}')
        report = inspect(self.root, ["package.json"])
        self.assertEqual(report["observations"][0]["result"], "DUPLICATE_JSON_KEY")
        self.assertNotIn('"2.0.0"', json.dumps(report))

    def test_malformed_manifest_and_secret_engine_are_redacted(self):
        self.manifest('{"name":"dsh","version":"1.0.0","engines":{"node":"SECRET"}}')
        report = inspect(self.root, ["package.json"])
        self.assertEqual(report["observations"][0]["result"], "NODE_RANGE_INVALID")
        self.assertNotIn("SECRET", json.dumps(report))
        self.manifest("{broken")
        self.assertEqual(inspect(self.root, ["package.json"])["observations"][0]["result"], "INVALID_JSON")

    def test_oversized_manifest_rejected(self):
        self.manifest('{"name":"a","version":"1.0.0","x":"' + "a" * 65536 + '"}')
        result = inspect(self.root, ["package.json"])
        self.assertEqual(result["observations"][0]["result"], "MANIFEST_TOO_LARGE")

    def test_invalid_package_identity_rejected(self):
        for name in ("../../evil", "https://evil.invalid", "a\nb", "a b"):
            with self.subTest(name=name):
                self.manifest({"name": name, "version": "1.0.0"})
                self.assertEqual(inspect(self.root, ["package.json"])["observations"][0]["result"],
                                 "PACKAGE_NAME_INVALID")

    def test_cli_outputs_redacted_and_nonzero_for_absent(self):
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            result = main(["--root", str(self.root), "--manifest", "package.json"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(capture.getvalue())["result"], "NO_METADATA_OBSERVED")
        self.manifest({"name": "dsh", "version": "1.18.26"})
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            result = main(["--root", str(self.root), "--manifest", "package.json"])
        self.assertEqual(result, 0)
        self.assertFalse(json.loads(capture.getvalue())["field_verified"])

    def test_no_host_environment_or_model_secret_access_in_inspector(self):
        code = (Path(__file__).resolve().parents[1]
                / "tools/dsh_workbench/wb_d_manifest_inspector.py").read_text(encoding="utf-8")
        for forbidden in ("os.environ", "getenv(", ".opencode", "profiles/", "write_text(", "write_bytes(",
                          "subprocess", "method=\"POST\"", "keyring"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)


if __name__ == "__main__":
    unittest.main()
