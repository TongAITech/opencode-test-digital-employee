# R1-R4 Field Validation Package

This directory is the offline-first field-validation surface for the R1-R4 runtime. It is a package tool, not a bank execution record.

`FV.cmd fv-0` runs the local Environment Doctor. `FV.cmd fv-1` summarizes project and bank-binding configuration without contacting external systems. `FV.cmd fv-2`, `FV.cmd fv-3`, and `FV.cmd fv-4` review caller-supplied receipts for requirement/coverage/case reality, real execution reality, and defect/continuous-quality reality.

The default binding file contains placeholders only. OpenCode and Git/Git Bash remain pre-existing bank prerequisites. Starlink, 4A, target URL/API/DB/CAT and target repositories are field-validation environment bindings. Do not put secrets in the package, in a receipt, or in evidence.

The package includes a Windows x64 portable Python runtime and a reusable Chrome payload. Windows execution proof is still required before this package can be moved to a bank environment.
