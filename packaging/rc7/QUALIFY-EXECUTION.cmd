@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"

if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state\rc7-execution-qualification"
if not exist "%PFC_AITEST_STATE_DIR%" mkdir "%PFC_AITEST_STATE_DIR%" >nul 2>&1

set "PYTHON_BIN=%PFC_PYTHON%"
if not defined PYTHON_BIN if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PYTHON_BIN=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PYTHON_BIN (
  for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_BIN set "PYTHON_BIN=%%P"
)
if not defined PYTHON_BIN (
  echo {"status":"NOT_PROVEN","reason":"PYTHON_NOT_FOUND"} 1>&2
  exit /b 10
)
if not defined PFC_BROWSER_BIN if exist "%ROOT%\workspace-template\runtime\browser\chrome-win64\chrome.exe" set "PFC_BROWSER_BIN=%ROOT%\workspace-template\runtime\browser\chrome-win64\chrome.exe"
if not defined PFC_CHROME_BIN if defined PFC_BROWSER_BIN set "PFC_CHROME_BIN=%PFC_BROWSER_BIN%"
if not defined PFC_RC7_SCRIPT_RESULT (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_SCRIPT_RESULT_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_EXECUTION_ENV_MODULE (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_EXECUTION_ENV_MODULE_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_EXECUTION_TARGET_ID (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_EXECUTION_TARGET_ID_REQUIRED"} 1>&2
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
if defined PFC_RC7_EXECUTION_TIMEOUT set "RC7_TIMEOUT=%PFC_RC7_EXECUTION_TIMEOUT%"
set "RC7_MAX_CYCLES=4"
if defined PFC_RC7_EXECUTION_MAX_CYCLES set "RC7_MAX_CYCLES=%PFC_RC7_EXECUTION_MAX_CYCLES%"
set "RC7_MAX_RETRIES=2"
if defined PFC_RC7_EXECUTION_MAX_TRANSIENT_RETRIES set "RC7_MAX_RETRIES=%PFC_RC7_EXECUTION_MAX_TRANSIENT_RETRIES%"

"%PYTHON_BIN%" -m rc7_release.execution_qualification_strict --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --script-result "%PFC_RC7_SCRIPT_RESULT%" --environment-module "%PFC_RC7_EXECUTION_ENV_MODULE%" --target-id "%PFC_RC7_EXECUTION_TARGET_ID%" --timeout-seconds "%RC7_TIMEOUT%" --max-cycles "%RC7_MAX_CYCLES%" --max-transient-retries "%RC7_MAX_RETRIES%"
set "RC=%ERRORLEVEL%"
set "RESULT=%PFC_AITEST_STATE_DIR%\qualification\rc7-execution-result.json"
if not exist "%RESULT%" (
  echo {"status":"FAIL","reason":"EXECUTION_QUALIFICATION_RESULT_FILE_MISSING"} 1>&2
  exit /b 11
)
echo RC7 strict Execution qualification evidence: %RESULT% 1>&2
exit /b %RC%