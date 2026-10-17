@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if not defined PFC_PYTHON if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON set "PFC_PYTHON=python"
if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state\rc7-final-qualification"

set "SOURCE_COMMIT=%PFC_RC7_SOURCE_COMMIT%"
if not defined SOURCE_COMMIT if exist "%ROOT%\SOURCE_COMMIT" set /p SOURCE_COMMIT=<"%ROOT%\SOURCE_COMMIT"
if not defined SOURCE_COMMIT for /f "usebackq delims=" %%S in (`git -C "%ROOT%" rev-parse HEAD 2^>nul`) do set "SOURCE_COMMIT=%%S"
if not defined SOURCE_COMMIT (
  echo {"status":"HOLD","reason":"SOURCE_COMMIT_NOT_RESOLVED"} 1>&2
  exit /b 11
)

if not exist "%PFC_AITEST_STATE_DIR%" mkdir "%PFC_AITEST_STATE_DIR%"
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"

if "%PFC_RC7_REQUIRE_BANK_FIELD_CONFORMANCE%"=="1" (
  if not defined PFC_RC7_R1_PATH (
    echo {"status":"HOLD","reason":"PFC_RC7_R1_PATH_REQUIRED_FOR_BANK_FIELD"} 1>&2
    exit /b 20
  )
  if not defined PFC_RC7_MISSION_ID (
    echo {"status":"HOLD","reason":"PFC_RC7_MISSION_ID_REQUIRED_FOR_BANK_FIELD"} 1>&2
    exit /b 21
  )
  if not defined PFC_RC7_BANK_TARGET_ID (
    echo {"status":"HOLD","reason":"PFC_RC7_BANK_TARGET_ID_REQUIRED_FOR_BANK_FIELD"} 1>&2
    exit /b 22
  )

  if not defined PFC_RC7_BANK_SERVICE_EVIDENCE set "PFC_RC7_BANK_SERVICE_EVIDENCE=%PFC_AITEST_STATE_DIR%\rc7-bank-service-qualification.json"
  call "%PFC_PYTHON%" -m rc7_runtime.bank_field_services qualify --r1 "%PFC_RC7_R1_PATH%" --mission-id "%PFC_RC7_MISSION_ID%" --target-id "%PFC_RC7_BANK_TARGET_ID%" --output "%PFC_RC7_BANK_SERVICE_EVIDENCE%" --require-pass
  if errorlevel 1 exit /b !ERRORLEVEL!
  echo RC7 Bank Field service evidence: %PFC_RC7_BANK_SERVICE_EVIDENCE% 1>&2

  if not defined PFC_RC7_DSH_RUNTIME_PROFILE_EVIDENCE set "PFC_RC7_DSH_RUNTIME_PROFILE_EVIDENCE=%ROOT%\state\rc7-dsh-runtime-profile.json"
  if not defined PFC_RC7_PLUGIN_EFFECT_EVIDENCE set "PFC_RC7_PLUGIN_EFFECT_EVIDENCE=%PFC_AITEST_STATE_DIR%\rc7-plugin-effect-qualification.json"
  call "%PFC_PYTHON%" -m rc7_release.plugin_effect_qualification --r1 "%PFC_RC7_R1_PATH%" --mission-id "%PFC_RC7_MISSION_ID%" --runtime-profile-evidence "%PFC_RC7_DSH_RUNTIME_PROFILE_EVIDENCE%" --output "%PFC_RC7_PLUGIN_EFFECT_EVIDENCE%" --require-pass
  if errorlevel 1 exit /b !ERRORLEVEL!
  echo RC7 Bank Field plugin effect evidence: %PFC_RC7_PLUGIN_EFFECT_EVIDENCE% 1>&2
)

set "REAL_MISSION_EVIDENCE=%PFC_RC7_REAL_MISSION_EVIDENCE%"
if not defined REAL_MISSION_EVIDENCE if defined PFC_RC7_R1_PATH if defined PFC_RC7_MISSION_ID (
  set "REAL_MISSION_EVIDENCE=%PFC_AITEST_STATE_DIR%\rc7-real-mission-result.json"
  set "STRICT_ARGS=--r1 "%PFC_RC7_R1_PATH%" --mission-id "%PFC_RC7_MISSION_ID%" --source-commit "%SOURCE_COMMIT%" --output "!REAL_MISSION_EVIDENCE!""
  if "%PFC_RC7_REQUIRE_BANK_FIELD_CONFORMANCE%"=="1" set "STRICT_ARGS=!STRICT_ARGS! --require-bank-field-conformance"
  call "%PFC_PYTHON%" -m rc7_release.real_mission_qualification_strict !STRICT_ARGS!
  if errorlevel 1 exit /b !ERRORLEVEL!
  echo RC7 strict real Mission qualification evidence: !REAL_MISSION_EVIDENCE! 1>&2
)

set "ARGS=--source-commit "%SOURCE_COMMIT%" --output "%PFC_AITEST_STATE_DIR%\rc7-final-qualification.json""
if defined PFC_RC7_ENGINEERING_EVIDENCE set "ARGS=!ARGS! --engineering "%PFC_RC7_ENGINEERING_EVIDENCE%""
if defined PFC_RC7_ADMIN_EVIDENCE set "ARGS=!ARGS! --admin "%PFC_RC7_ADMIN_EVIDENCE%""
if defined REAL_MISSION_EVIDENCE set "ARGS=!ARGS! --real-mission "!REAL_MISSION_EVIDENCE!""
if defined PFC_RC7_DELIVERY_EVIDENCE set "ARGS=!ARGS! --delivery "%PFC_RC7_DELIVERY_EVIDENCE%""
if "%PFC_RC7_REQUIRE_FINAL_PASS%"=="1" set "ARGS=!ARGS! --require-pass"

call "%PFC_PYTHON%" -m rc7_release.final_qualification !ARGS!
set "RC=%ERRORLEVEL%"
if exist "%PFC_AITEST_STATE_DIR%\rc7-final-qualification.json" (
  echo RC7 final qualification evidence: %PFC_AITEST_STATE_DIR%\rc7-final-qualification.json 1>&2
) else (
  echo {"status":"HOLD","reason":"FINAL_QUALIFICATION_RESULT_MISSING"} 1>&2
  exit /b 12
)
exit /b %RC%