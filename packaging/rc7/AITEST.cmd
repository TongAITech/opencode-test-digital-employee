@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "RC7_HOME=%%~fI"
set "PY=%RC7_HOME%\workspace-template\runtime\python\python.exe"
if not exist "%PY%" (
  echo [RC7] package-local Python missing: %PY%
  exit /b 2
)

set "PATH=%RC7_HOME%\workspace-template\runtime\node;%RC7_HOME%\workspace-template\runtime\maven\bin;%RC7_HOME%\workspace-template\runtime\java\bin;%RC7_HOME%\workspace-template\runtime\allure\bin;%RC7_HOME%\workspace-template\runtime\k6;%PATH%"
for /r "%RC7_HOME%\workspace-template\runtime\browser\browserskill" %%F in (bsk.exe) do set "PATH=%%~dpF;%PATH%"
for /r "%RC7_HOME%\workspace-template\runtime\ripgrep" %%F in (rg.exe) do set "PATH=%%~dpF;%PATH%"

set "PYTHONUTF8=1"
set "PFC_AITEST_HOME=%RC7_HOME%"
set "PFC_AITEST_STATE_DIR=%RC7_HOME%\runtime-state"
set "PFC_PYTHON=%PY%"
set "PFC_CODEGRAPH_BIN=%RC7_HOME%\workspace-template\runtime\code-intelligence\codegraph\codegraph-server-win32-x64.exe"
set "PFC_CHROMIUM_BIN=%RC7_HOME%\workspace-template\runtime\browser\chrome-win64\chrome.exe"
set "PFC_JAVA_BIN=%RC7_HOME%\workspace-template\runtime\java\bin\java.exe"
set "PFC_MAVEN_BIN=%RC7_HOME%\workspace-template\runtime\maven\bin\mvn.cmd"
set "PFC_MAVEN_REPO=%RC7_HOME%\workspace-template\runtime\maven-repository"
set "PFC_MAVEN_SETTINGS=%RC7_HOME%\packaging\rc7\maven-offline-settings.xml"
set "MAVEN_ARGS=-o -s "%PFC_MAVEN_SETTINGS%" -Dmaven.legacyLocalRepo=true -Dmaven.repo.local="%PFC_MAVEN_REPO%""
set "PFC_K6_BIN=%RC7_HOME%\workspace-template\runtime\k6\k6.exe"
if not defined PFC_RC7_DSH_PROFILE set "PFC_RC7_DSH_PROFILE=web"

if not exist "%PFC_AITEST_STATE_DIR%\r1" mkdir "%PFC_AITEST_STATE_DIR%\r1"
if not exist "%RC7_HOME%\state" mkdir "%RC7_HOME%\state"

if "%PFC_RC7_SKIP_QUALIFY%"=="1" goto :payload
"%PY%" -m rc7_release.final_unified_qualification --home "%RC7_HOME%" --require-pass
if errorlevel 1 exit /b %errorlevel%

:payload
rem Normal startup is intentionally read-only with respect to the bank DSH
rem profile. Field validation proved that plugin install/add on the existing
rem web profile can remove private provider/auth plugins. Runtime plugin
rem qualification is performed separately in an isolated profile.
"%PY%" -m rc7_release.dsh_plugins --home "%RC7_HOME%" --profile "%PFC_RC7_DSH_PROFILE%" --dry-run --output "%RC7_HOME%\state\dsh-plugin-payload.json"
if errorlevel 1 exit /b %errorlevel%

where dsh >nul 2>nul
if errorlevel 1 (
  echo [RC7] Bank DSH host is not on PATH. Package is complete; bind the bank DSH host and rerun AITEST.cmd.
  exit /b 3
)

"%PY%" -m rc7_release.dsh --output "%RC7_HOME%\state\rc7-dsh.patch.yml" --home "%RC7_HOME%" --python "%PFC_PYTHON%"
if errorlevel 1 exit /b %errorlevel%

echo [RC7] Protected bank DSH profile: %PFC_RC7_DSH_PROFILE%
echo [RC7] Canonical R1: %PFC_AITEST_STATE_DIR%\r1\event-stream.jsonl
echo [RC7] Maven repo: %PFC_MAVEN_REPO%
echo [RC7] Starting DSH with runtime-only RC7 MCP patch; bank profile files will not be modified.
dsh --profile "%PFC_RC7_DSH_PROFILE%" --patch "%RC7_HOME%\state\rc7-dsh.patch.yml"
exit /b %errorlevel%
