@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"

if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state\rc7-dsh-script-qualification"
if not exist "%PFC_AITEST_STATE_DIR%" mkdir "%PFC_AITEST_STATE_DIR%" >nul 2>&1

set "PYTHON_BIN=%PFC_PYTHON%"
if not defined PYTHON_BIN (
  for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_BIN set "PYTHON_BIN=%%P"
)
if not defined PYTHON_BIN (
  echo {"status":"NOT_PROVEN","reason":"PYTHON_NOT_FOUND"} 1>&2
  exit /b 10
)
if not defined PFC_RC7_TEST_DESIGN_RESULT (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_TEST_DESIGN_RESULT_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_SCRIPT_TC_ID (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_SCRIPT_TC_ID_REQUIRED"} 1>&2
  exit /b 2
)

set "PFC_AITEST_HOME=%ROOT%"
if not defined PFC_WORKSPACE set "PFC_WORKSPACE=%ROOT%"
if defined PYTHONPATH (
  set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%ROOT%"
)
set "RC7_TIMEOUT=300"
if defined PFC_RC7_DSH_TIMEOUT set "RC7_TIMEOUT=%PFC_RC7_DSH_TIMEOUT%"

if defined PFC_RC7_SCRIPT_CWD (
  if defined PFC_DSH_BIN (
    "%PYTHON_BIN%" -m rc7_release.script_qualification --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --test-design-result "%PFC_RC7_TEST_DESIGN_RESULT%" --tc-id "%PFC_RC7_SCRIPT_TC_ID%" --execution-cwd "%PFC_RC7_SCRIPT_CWD%" --dsh-bin "%PFC_DSH_BIN%" --timeout-seconds "%RC7_TIMEOUT%"
  ) else (
    "%PYTHON_BIN%" -m rc7_release.script_qualification --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --test-design-result "%PFC_RC7_TEST_DESIGN_RESULT%" --tc-id "%PFC_RC7_SCRIPT_TC_ID%" --execution-cwd "%PFC_RC7_SCRIPT_CWD%" --timeout-seconds "%RC7_TIMEOUT%"
  )
) else (
  if defined PFC_DSH_BIN (
    "%PYTHON_BIN%" -m rc7_release.script_qualification --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --test-design-result "%PFC_RC7_TEST_DESIGN_RESULT%" --tc-id "%PFC_RC7_SCRIPT_TC_ID%" --dsh-bin "%PFC_DSH_BIN%" --timeout-seconds "%RC7_TIMEOUT%"
  ) else (
    "%PYTHON_BIN%" -m rc7_release.script_qualification --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --test-design-result "%PFC_RC7_TEST_DESIGN_RESULT%" --tc-id "%PFC_RC7_SCRIPT_TC_ID%" --timeout-seconds "%RC7_TIMEOUT%"
  )
)
set "RC=%ERRORLEVEL%"
set "RESULT=%PFC_AITEST_STATE_DIR%\qualification\rc7-dsh-script-result.json"
if not exist "%RESULT%" (
  echo {"status":"FAIL","reason":"SCRIPT_QUALIFICATION_RESULT_FILE_MISSING"} 1>&2
  exit /b 11
)
echo RC7 Script readiness qualification evidence: %RESULT% 1>&2
exit /b %RC%
