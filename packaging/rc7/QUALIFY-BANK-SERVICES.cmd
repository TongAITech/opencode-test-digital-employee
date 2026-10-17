@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if not defined PFC_PYTHON if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON set "PFC_PYTHON=python"
if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state\rc7-bank-services"

if not defined PFC_RC7_R1_PATH (
  echo {"status":"HOLD","reason":"PFC_RC7_R1_PATH_REQUIRED"} 1>&2
  exit /b 20
)
if not defined PFC_RC7_MISSION_ID (
  echo {"status":"HOLD","reason":"PFC_RC7_MISSION_ID_REQUIRED"} 1>&2
  exit /b 21
)
if not defined PFC_RC7_BANK_TARGET_ID (
  echo {"status":"HOLD","reason":"PFC_RC7_BANK_TARGET_ID_REQUIRED"} 1>&2
  exit /b 22
)

set "PROVIDER_CONFIG=%PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG%"
if not defined PROVIDER_CONFIG set "PROVIDER_CONFIG=%PFC_RC7_CASE_PROVIDER_CONFIG%"
if not defined PROVIDER_CONFIG set "PROVIDER_CONFIG=%ROOT%\state\bank-field-providers.json"
if not exist "%PROVIDER_CONFIG%" (
  echo {"status":"FIELD_REQUIRED","reason":"BANK_SERVICE_PROVIDER_CONFIG_NOT_FOUND","path":"%PROVIDER_CONFIG%"} 1>&2
  exit /b 2
)
if not exist "%PFC_AITEST_STATE_DIR%" mkdir "%PFC_AITEST_STATE_DIR%"
set "OUTPUT=%PFC_AITEST_STATE_DIR%\rc7-bank-service-probe.json"

call "%PFC_PYTHON%" -m rc7_runtime.bank_field_services probe --r1 "%PFC_RC7_R1_PATH%" --state-root "%PFC_AITEST_STATE_DIR%" --provider-config "%PROVIDER_CONFIG%" --mission-id "%PFC_RC7_MISSION_ID%" --target-id "%PFC_RC7_BANK_TARGET_ID%" --output "%OUTPUT%" --require-pass
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" (
  for /f "usebackq delims=" %%R in (`"%PFC_PYTHON%" -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8')).get('db_write_gate_request_id') or '')" "%OUTPUT%"`) do set "REQUEST_ID=%%R"
  echo RC7 bank services: DB_WRITE Human Gate required. 1>&2
  echo Request: !REQUEST_ID! 1>&2
  echo Approve explicitly, then rerun this script: 1>&2
  echo "%PFC_PYTHON%" -m rc7_runtime.bank_field_services approve-db-write --r1 "%PFC_RC7_R1_PATH%" --state-root "%PFC_AITEST_STATE_DIR%" --mission-id "%PFC_RC7_MISSION_ID%" --target-id "%PFC_RC7_BANK_TARGET_ID%" --request-id "!REQUEST_ID!" --actor-ref YOUR_OPERATOR_REF --reason "YOUR_REASON" 1>&2
  exit /b 3
)
if not "%RC%"=="0" exit /b %RC%

echo RC7 bank service probes: PASS
echo Evidence: %OUTPUT%
exit /b 0
