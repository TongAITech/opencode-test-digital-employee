@echo off
setlocal EnableExtensions
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not defined PFC_PYTHON_BIN if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON_BIN=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON_BIN set "PFC_PYTHON_BIN=python"
if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state"
if not defined PFC_RC7_R1_PATH set "PFC_RC7_R1_PATH=%PFC_AITEST_STATE_DIR%\r1\event-stream.jsonl"
if not defined PFC_RC7_SOURCE_COMMIT if exist "%ROOT%\SOURCE_COMMIT" set /p PFC_RC7_SOURCE_COMMIT=<"%ROOT%\SOURCE_COMMIT"
if not defined PFC_RC7_SOURCE_REVISION if defined PFC_RC7_SOURCE_COMMIT set "PFC_RC7_SOURCE_REVISION=%PFC_RC7_SOURCE_COMMIT%"
set "PFC_RC7_CASE_PROVIDER_CANONICAL=%ROOT%\state\bank-field-providers.json"
if defined PFC_RC7_CASE_PROVIDER_CONFIG (
  if not exist "%PFC_RC7_CASE_PROVIDER_CONFIG%" (
    echo [RC7.1] CASE_PROVIDER_CONFIG_NOT_FOUND: %PFC_RC7_CASE_PROVIDER_CONFIG%
    exit /b 5
  )
) else if exist "%PFC_RC7_CASE_PROVIDER_CANONICAL%" (
  set "PFC_RC7_CASE_PROVIDER_CONFIG=%PFC_RC7_CASE_PROVIDER_CANONICAL%"
)
if defined PFC_RC7_CASE_PROVIDER_CONFIG (
  echo [RC7.1] Case provider config: %PFC_RC7_CASE_PROVIDER_CONFIG%
) else (
  echo [RC7.1] Case provider config: FIELD_REQUIRED. Create state\bank-field-providers.json from packaging\rc7\bank-field-providers.example.json or set PFC_RC7_CASE_PROVIDER_CONFIG explicitly.
)
if not exist "%PFC_AITEST_STATE_DIR%\r1" mkdir "%PFC_AITEST_STATE_DIR%\r1"
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
cd /d "%ROOT%"
echo [RC7.1] Mission Autopilot R1: %PFC_RC7_R1_PATH%

rem Backward-compatible environment mode. The Mission is bootstrapped/resumed
rem and then immediately driven by the same R1-native Autopilot. No follow-up
rem "continue" message is required.
if defined PFC_RC7_MISSION_ID if defined PFC_RC7_RELEASE_ID if defined PFC_RC7_MISSION_GOAL goto ENV_MODE

rem Turnkey CLI mode preserves the historical --graph-version and repeatable
rem --input NODE=REF arguments while adding Autopilot runtime options.
"%PFC_PYTHON_BIN%" -m rc7_runtime.bank_mission_start --r1 "%PFC_RC7_R1_PATH%" --package-root "%ROOT%" %*
exit /b %ERRORLEVEL%

:ENV_MODE
"%PFC_PYTHON_BIN%" -m rc7_runtime.bank_mission_start --r1 "%PFC_RC7_R1_PATH%" --package-root "%ROOT%" --mission-id "%PFC_RC7_MISSION_ID%" --release-id "%PFC_RC7_RELEASE_ID%" --goal "%PFC_RC7_MISSION_GOAL%" %*
exit /b %ERRORLEVEL%
