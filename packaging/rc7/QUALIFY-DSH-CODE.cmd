@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"

if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state\rc7-dsh-code-qualification"
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

if not defined PFC_RC7_CODE_REPO (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODE_REPO_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_CODE_BASE_REF (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODE_BASE_REF_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_CODE_HEAD_REF (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODE_HEAD_REF_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_CODE_TARGET_ID (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODE_TARGET_ID_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON (
  echo {"status":"NOT_PROVEN","reason":"PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON_REQUIRED"} 1>&2
  exit /b 2
)
if not defined PFC_CODEGRAPH_BIN if exist "%ROOT%\workspace-template\runtime\code-intelligence\codegraph\codegraph-server-win32-x64.exe" set "PFC_CODEGRAPH_BIN=%ROOT%\workspace-template\runtime\code-intelligence\codegraph\codegraph-server-win32-x64.exe"
if not defined PFC_CODEGRAPH_BIN (
  echo {"status":"NOT_PROVEN","reason":"PFC_CODEGRAPH_BIN_REQUIRED_OR_PACKAGE_LOCAL_CODEGRAPH_MISSING"} 1>&2
  exit /b 2
)
if not exist "%PFC_CODEGRAPH_BIN%" (
  echo {"status":"NOT_PROVEN","reason":"PFC_CODEGRAPH_BIN_NOT_FOUND"} 1>&2
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
  "%PYTHON_BIN%" -m rc7_release.code_qualification_strict --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --repo-path "%PFC_RC7_CODE_REPO%" --base-ref "%PFC_RC7_CODE_BASE_REF%" --head-ref "%PFC_RC7_CODE_HEAD_REF%" --target-id "%PFC_RC7_CODE_TARGET_ID%" --codegraph-args-json "%PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON%" --dsh-bin "%PFC_DSH_BIN%" --timeout-seconds "%RC7_TIMEOUT%"
) else (
  "%PYTHON_BIN%" -m rc7_release.code_qualification_strict --state-root "%PFC_AITEST_STATE_DIR%" --workspace "%PFC_WORKSPACE%" --repo-path "%PFC_RC7_CODE_REPO%" --base-ref "%PFC_RC7_CODE_BASE_REF%" --head-ref "%PFC_RC7_CODE_HEAD_REF%" --target-id "%PFC_RC7_CODE_TARGET_ID%" --codegraph-args-json "%PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON%" --timeout-seconds "%RC7_TIMEOUT%"
)
set "RC=%ERRORLEVEL%"
set "RESULT=%PFC_AITEST_STATE_DIR%\qualification\rc7-dsh-code-result.json"
if not exist "%RESULT%" (
  echo {"status":"FAIL","reason":"CODE_QUALIFICATION_RESULT_FILE_MISSING"} 1>&2
  exit /b 11
)
echo RC7 strict Code qualification evidence: %RESULT% 1>&2
exit /b %RC%