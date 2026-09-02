# Independent Windows Package Reality Audit — V3

Run this audit on a clean Windows x64 machine after the package has been transferred. Do not use the bank's Python 3.8.10 as the package runtime.

1. Open a command prompt at the package `workspace-template` directory and confirm the package-local path is being used.
2. Run `runtime\python\python.exe --version` and record the output. It must be Python 3.12.10.
3. Run `runtime\python\python.exe -c "import playwright,greenlet,pyee,typing_extensions; print('imports-pass')"`.
4. Run `set PYTHONPATH=ai-test\runtime` followed by `runtime\python\python.exe -c "import aitest_runtime; import aitest_runtime.r1_5; import aitest_runtime.r2_7; import aitest_runtime.r3_7; import aitest_runtime.r3_e3; import aitest_runtime.r4_1; import aitest_runtime.r4_8; print('r1-r4-imports-pass')"`.
5. Run `field-validation\FV.cmd fv-0 --output ai-test\evidence\field-validation\FV-0-windows.json`.
6. Run `field-validation\FV.cmd fv-1 --input field-validation\bindings\bank-binding.template.json --output ai-test\evidence\field-validation\FV-1-template.json`.
7. Confirm `field-validation\FV.cmd`, `field-validation\FV-0.cmd` through `FV-4.cmd`, `aitest` and `AITEST.cmd` resolve only the package-relative runtime. Temporarily remove or shadow all machine-wide interpreter names and confirm the package path is still selected. No fallback, `pip install`, `npm install`, `playwright install`, internet download or administrator installation is allowed.
8. Bind Chrome through `AITEST_BROWSER_EXECUTABLE` or the package-relative `runtime\browser\chrome-win64\chrome.exe`; alternatively use the approved CDP endpoint. Record the Chrome version and executable digest without recording credentials.
9. Confirm OpenCode and Git/Git Bash are detected as pre-existing bank prerequisites. Do not mark them bundled or available based on this package alone.
10. Preserve command output, package identity, manifest digest, machine/platform facts and evidence references in an external audit receipt.

11. Confirm the package-local `opencode.json` has no active CodeGraph target and record `CODEGRAPH_FIELD_VALIDATION_DISPOSITION=OPTIONAL_DISABLED_IN_FV_PROFILE`. This package profile does not alter any bank OpenCode installation.
12. Confirm the portable Python `Lib\site-packages` file count against the V3 Build Evidence Pack and verify all package manifest hashes.
13. Treat `field-validation\FV.sh` as a development-shell helper only. It is explicitly `NOT_PART_OF_WINDOWS_FIELD_VALIDATION_RUNTIME` and is not a bank startup entry.

The audit must explicitly distinguish static package readiness from Windows execution proof. A successful Mac build or static hash check cannot satisfy this audit. Do not claim Windows execution proof from these instructions alone.
