from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from validate_package import structured_report_from_stdout


class StructuredGateReportTests(unittest.TestCase):
    def test_merges_later_host_gate_reports_instead_of_first_json_wins(self):
        stdout = "\n".join([
            json.dumps({"gates": {"CONTROL_LOOP_BINDING": "PASS"}}),
            "ordinary text with {not-json}",
            json.dumps({
                "status": "PASS",
                "classification": "WINDOWS_INSTALLED_HOST_NATIVE_NO_MODEL",
                "gates": {
                    "HOST_NATIVE_OPENCODE": "PASS",
                    "HOST_PROVIDER_AUTH_PRESERVED": "PASS",
                    "AITEST_WORKSPACE_LOADED": "PASS",
                    "CONTROL_LOOP_BOUND": "PASS",
                },
            }),
            json.dumps({
                "gates": {
                    "OPENCODE_PROCESS_READY": "PASS",
                    "AITEST_WORKSPACE_LOADED": "PASS",
                    "PROVIDER_READY": "AUTH_REQUIRED",
                    "MODEL_READY": "MODEL_SELECTION_REQUIRED",
                    "SESSION_CREATE": "PASS",
                    "CONTROL_LOOP_BINDING": "PASS",
                },
                "operational_only": True,
            }),
        ])
        report = structured_report_from_stdout(stdout)
        self.assertIsNotNone(report)
        self.assertEqual(report["classification"], "WINDOWS_INSTALLED_HOST_NATIVE_NO_MODEL")
        self.assertTrue(report["operational_only"])
        for gate in (
            "HOST_NATIVE_OPENCODE",
            "HOST_PROVIDER_AUTH_PRESERVED",
            "AITEST_WORKSPACE_LOADED",
            "CONTROL_LOOP_BOUND",
            "CONTROL_LOOP_BINDING",
            "OPENCODE_PROCESS_READY",
        ):
            self.assertEqual(report["gates"][gate], "PASS")
        self.assertEqual(report["gates"]["PROVIDER_READY"], "AUTH_REQUIRED")
        self.assertEqual(report["gates"]["MODEL_READY"], "MODEL_SELECTION_REQUIRED")

    def test_returns_none_when_no_gate_report_exists(self):
        self.assertIsNone(structured_report_from_stdout("text only\n{bad json}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
