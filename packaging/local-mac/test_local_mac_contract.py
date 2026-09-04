from __future__ import annotations

import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
BASELINE = "4edd78536633d4258705c6083fe55b44e51f54bb"
ARM_CHROME_SHA = "01a23ef9501b2745e0c2944c2e583207e6f6132d8d91c3a87ff65b5079e438ef"
X64_CHROME_SHA = "69bcc853db975a2380767e9ff36da17f1d7b782fbbe191a210f676d2d5967d3e"
PROTECTED = (
    "packaging/INSTALL-PFC-AITEST.sh",
    "packaging/start-pfc-ai-r1r4.sh",
    "packaging/status-pfc-ai-r1r4.sh",
    "packaging/stop-pfc-ai-r1r4.sh",
    "runtime-lock.json",
)


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def unchanged(*paths: str) -> bool:
    return (
        subprocess.run(
            ["git", "diff", "--quiet", BASELINE, "--", *paths],
            cwd=REPO_ROOT,
            check=False,
        ).returncode
        == 0
    )


def main() -> int:
    script = (HERE / "local-mac.sh").read_text(encoding="utf-8")
    pinned = (HERE / "pinned-build.sh").read_text(encoding="utf-8")
    runtime_shell = (HERE / "runtime-shell-bash").read_text(encoding="utf-8")
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github/workflows/local-mac-validation.yml").read_text(encoding="utf-8")
    arm = load("runtime-lock.mac-arm64.json")
    x64 = load("runtime-lock.mac-x64.json")
    profiles = (arm, x64)

    checks = {
        "bank_windows_source_unchanged": unchanged(*PROTECTED),
        "product_workspace_source_unchanged": unchanged("workspace-template"),
        "both_mac_profiles_present": (
            arm.get("profile") == "local-mac-arm64"
            and x64.get("profile") == "local-mac-x64"
        ),
        "opencode_1_18_3": all(
            p["payloads"]["opencode"]["version"] == "1.18.3" for p in profiles
        ),
        "python_3_12_10": all(
            p["payloads"]["python"]["version"] == "3.12.10" for p in profiles
        ),
        "playwright_1_62_0": all(
            p["payloads"]["playwright_python"]["version"] == "1.62.0"
            for p in profiles
        ),
        "chrome_151_0_7922_34": all(
            p["payloads"]["chromium"]["version"] == "151.0.7922.34"
            for p in profiles
        ),
        "chrome_digests_pinned_in_locks": (
            arm["payloads"]["chromium"].get("archive_sha256") == ARM_CHROME_SHA
            and x64["payloads"]["chromium"].get("archive_sha256") == X64_CHROME_SHA
        ),
        "canonical_build_wrapper_pins_chrome": (
            ARM_CHROME_SHA in pinned
            and X64_CHROME_SHA in pinned
            and 'export PFC_MAC_CHROME_SHA256=' in pinned
            and '"$HERE/local-mac.sh" build "$@" | tee' in pinned
        ),
        "owned_pid_wrapper_is_packaged": (
            "runtime-shell-bash" in pinned
            and "POSIX_EXEC_OWNED_PID" in pinned
            and 'exec /bin/bash -c "exec $CMD"' in runtime_shell
        ),
        "canonical_build_repins_runtime_identity": (
            'payload["runtime_tree_sha256"] = sys.argv[2]' in pinned
            and "offline runtime tree identity" in script
            and "installed runtime tree identity" in script
        ),
        "official_build_surfaces_use_pinned_wrapper": (
            "./pinned-build.sh" in readme
            and "./packaging/local-mac/pinned-build.sh" in workflow
            and "./packaging/local-mac/local-mac.sh build" not in workflow
        ),
        "codegraph_0_20_1": all(
            p["payloads"]["codegraph"]["version"] == "0.20.1" for p in profiles
        ),
        "ripgrep_15_1_0": all(
            p["payloads"]["ripgrep"]["version"] == "15.1.0" for p in profiles
        ),
        "target_commands_offline": (
            "Build is the only command that requires internet/dependency installation."
            in script
        ),
        "assembly_only_pip": script.count("pip install") == 1 and "cmd_build()" in script,
        "no_system_python_resolution": (
            "command -v python" not in script and "command -v python3" not in script
        ),
        "package_runtime_tree_identity": (
            "runtime_tree_sha256" in script
            and "offline runtime tree identity mismatch" in script
            and "installed runtime tree identity mismatch" in script
        ),
        "r1_truth_guard": (
            "R1_EVENT_STREAM" in script
            and "conversation_is_not_truth" in script
            and "legacy_store" in script
        ),
        "browser_package_binding": "AITEST_BROWSER_EXECUTABLE" in script,
        "codegraph_package_binding": (
            "AITEST_CODEGRAPH_BINARY" in script and "AITEST_RUNTIME_LOCK" in script
        ),
        "local_target_binding_separate": "local-pfc.env" in script and "cmd_bind()" in script,
        "no_credentials_persisted": (
            "CREDENTIALS_PERSISTED=NO" in script
            and "Credentials are not persisted." in readme
        ),
        "archive_checksum_required_by_runbook": "shasum -a 256 -c" in readme,
    }

    status = "PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status": status, "checks": checks}, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
