@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"

if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state\rc7-dsh-test-design-qualification"
if not exist "%PFC_AITEST_STATE_DIR%" mkdir "%PFC_AITEST_STATE_DIR%" >nul 2>&1

set "PYTHON_BIN=%PFC_PYTHON%"
if not defined PYTHON_BIN (
  for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_BIN set "PYTHON_BIN=%%P"
)
if not defined PYTHON_BIN (
  echo {"status":"NOT_PROVEN","reason":"PYTHON_NOT_FOUND"} 1>&2
  exit /b 10
)

if not defined PFC_RC7_REQUIREMENT_RESULT (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_REQUIREMENT_RESULT_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_CODE_RESULT (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODE_RESULT_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_CODE_REPO (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODE_REPO_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_CODEGRAPH_BIN (
  echo {"status":"NOT_PROVEN","reason":"PFC_CODEGRAPH_BIN_REQUIRED"} 1>&2
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

if defined PFC_DSH_BIN (
  "%PYTHON_BIN%" -m rc7_release.test_design_qualification --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --requirement-result "%PFC_RC7_REQUIREMENT_RESULT%" --code-result "%PFC_RC7_CODE_RESULT%" --repo-path "%PFC_RC7_CODE_REPO%" --codegraph-args-json "%PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON%" --dsh-bin "%PFC_DSH_BIN%" --timeout-seconds "%RC7_TIMEOUT%"
) else (
  "%PYTHON_BIN%" -m rc7_release.test_design_qualification --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --requirement-result "%PFC_RC7_REQUIREMENT_RESULT%" --code-result "%PFC_RC7_CODE_RESULT%" --repo-path "%PFC_RC7_CODE_REPO%" --codegraph-args-json "%PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON%" --timeout-seconds "%RC7_TIMEOUT%"
)
set "RC=%ERRORLEVEL%"
set "RESULT=%PFC_AITEST_STATE_DIR%\qualification\rc7-dsh-test-design-result.json"
if not exist "%RESULT%" (
  echo {"status":"FAIL","reason":"TEST_DESIGN_QUALIFICATION_RESULT_FILE_MISSING"} 1>&2
  exit /b 11
)
echo RC7 Test Design qualification evidence: %RESULT% 1>&2
exit /b %RC%
