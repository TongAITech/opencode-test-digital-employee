@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if not defined PFC_PYTHON if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON set "PFC_PYTHON=python"

rem Single-entry Bank Field qualification. Mission/Target/R1 may be supplied as
rem normal CLI arguments. When omitted, the launcher auto-resolves only a unique
rem graph-v2 Mission and a unique formal-execution target; ambiguity is HOLD.
"%PFC_PYTHON%" -m rc7_release.bank_field_launcher run --package-root "%ROOT%" %*
exit /b %ERRORLEVEL%
