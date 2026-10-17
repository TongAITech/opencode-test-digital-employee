@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if not defined PFC_PYTHON if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON set "PFC_PYTHON=python"

if not defined PFC_RC7_R1_PATH (
  echo {"status":"HOLD","reason":"PFC_RC7_R1_PATH_REQUIRED"} 1>&2
  exit /b 20
)
if not defined PFC_RC7_MISSION_ID (
  echo {"status":"HOLD","reason":"PFC_RC7_MISSION_ID_REQUIRED"} 1>&2
  exit /b 21
)
if not exist "%PFC_RC7_R1_PATH%" (
  echo {"status":"HOLD","reason":"R1_EVENT_STREAM_NOT_FOUND"} 1>&2
  exit /b 22
)

set "QUAL_DIR=%PFC_RC7_QUALIFICATION_DIR%"
if not defined QUAL_DIR if exist "%ROOT%\qualification" set "QUAL_DIR=%ROOT%\qualification"
if not defined QUAL_DIR if exist "%ROOT%\..\qualification" for %%I in ("%ROOT%\..\qualification") do set "QUAL_DIR=%%~fI"
if not defined QUAL_DIR (
  echo {"status":"HOLD","reason":"DELIVERY_QUALIFICATION_DIRECTORY_NOT_FOUND"} 1>&2
  echo Expected qualification next to the extracted RC7 package or set PFC_RC7_QUALIFICATION_DIR. 1>&2
  exit /b 23
)

if not defined PFC_RC7_ENGINEERING_EVIDENCE set "PFC_RC7_ENGINEERING_EVIDENCE=%QUAL_DIR%\engineering.json"
if not defined PFC_RC7_ADMIN_EVIDENCE set "PFC_RC7_ADMIN_EVIDENCE=%QUAL_DIR%\admin.json"
if not defined PFC_RC7_DELIVERY_EVIDENCE set "PFC_RC7_DELIVERY_EVIDENCE=%QUAL_DIR%\delivery.json"

for %%F in ("%PFC_RC7_ENGINEERING_EVIDENCE%" "%PFC_RC7_ADMIN_EVIDENCE%" "%PFC_RC7_DELIVERY_EVIDENCE%") do (
  if not exist "%%~F" (
    echo {"status":"HOLD","reason":"REQUIRED_PRE_FIELD_EVIDENCE_MISSING","path":"%%~F"} 1>&2
    exit /b 24
  )
)

if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state\rc7-bank-final"
set "PFC_RC7_REQUIRE_FINAL_PASS=1"
set "PFC_RC7_REQUIRE_BANK_FIELD_CONFORMANCE=1"

echo RC7 BANK FINAL qualification
echo Package root: %ROOT%
echo Qualification evidence: %QUAL_DIR%
echo R1 Event Stream: %PFC_RC7_R1_PATH%
echo Mission: %PFC_RC7_MISSION_ID%

call "%SCRIPT_DIR%QUALIFY-FINAL.cmd"
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo RC7 BANK FINAL: PASS
  echo Final evidence: %PFC_AITEST_STATE_DIR%\rc7-final-qualification.json
  echo Real Mission evidence: %PFC_AITEST_STATE_DIR%\rc7-real-mission-result.json
) else (
  echo RC7 BANK FINAL: HOLD/FAIL 1>&2
  if exist "%PFC_AITEST_STATE_DIR%\rc7-real-mission-result.json" echo Real Mission evidence: %PFC_AITEST_STATE_DIR%\rc7-real-mission-result.json 1>&2
  if exist "%PFC_AITEST_STATE_DIR%\rc7-final-qualification.json" echo Final evidence: %PFC_AITEST_STATE_DIR%\rc7-final-qualification.json 1>&2
)
exit /b %RC%