@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "RC7_HOME=%%~fI"
set "PY=%RC7_HOME%\workspace-template\runtime\python\python.exe"
if not exist "%PY%" (
  echo [RC7.1] package-local Python missing: %PY%
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
if not defined PFC_RC7_DSH_BASE_PROFILE set "PFC_RC7_DSH_BASE_PROFILE=web"
if not defined PFC_RC7_DSH_PROFILE set "PFC_RC7_DSH_PROFILE=rc7-bank"

if not exist "%PFC_AITEST_STATE_DIR%\r1" mkdir "%PFC_AITEST_STATE_DIR%\r1"
if not exist "%RC7_HOME%\state" mkdir "%RC7_HOME%\state"

rem RC7.1 startup truth: trace only RC7-owned prestart work. Model/session
rem readiness belongs to DSH after DSH_HOST_LAUNCH and is never hardcoded READY.
"%PY%" -m rc7_release.startup_trace init --home "%RC7_HOME%" >nul 2>nul

if "%PFC_RC7_SKIP_QUALIFY%"=="1" goto :payload
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PACKAGE_VERIFY --event START >nul 2>nul
"%PY%" -m rc7_release.package verify --package-root "%RC7_HOME%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PACKAGE_VERIFY --event FAIL --detail "exit=%RC%" >nul 2>nul
  exit /b %RC%
)
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PACKAGE_VERIFY --event END >nul 2>nul

:payload
rem Startup rule: NEVER invoke dsh plugin add/install before DSH starts.
rem The protected web profile is read-only. We only verify the package payload,
rem then physically clone web to rc7-bank. Persistent plugin repair is a
rem separate POST-START, NON-BLOCKING action.
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PLUGIN_PAYLOAD --event START >nul 2>nul
"%PY%" -m rc7_release.dsh_plugins --home "%RC7_HOME%" --profile "%PFC_RC7_DSH_BASE_PROFILE%" --dry-run --output "%RC7_HOME%\state\dsh-plugin-payload.json"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PLUGIN_PAYLOAD --event FAIL --detail "exit=%RC%" >nul 2>nul
  exit /b %RC%
)
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PLUGIN_PAYLOAD --event END >nul 2>nul

"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase DSH_HOST_LOOKUP --event START >nul 2>nul
set "PFC_RC7_DSH_BIN="
for /f "delims=" %%D in ('where dsh 2^>nul') do if not defined PFC_RC7_DSH_BIN set "PFC_RC7_DSH_BIN=%%D"
if not defined PFC_RC7_DSH_BIN (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase DSH_HOST_LOOKUP --event FAIL --detail "DSH_NOT_ON_PATH" >nul 2>nul
  echo [RC7.1] Bank DSH host is not on PATH. Package is complete; bind the bank DSH host and rerun AITEST.cmd.
  exit /b 3
)
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase DSH_HOST_LOOKUP --event END >nul 2>nul

if /I "%PFC_RC7_DSH_PROFILE%"=="%PFC_RC7_DSH_BASE_PROFILE%" (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase RUNTIME_PROFILE --event FAIL --detail "PROTECTED_PROFILE_SELECTED" >nul 2>nul
  echo [RC7.1] RC7 runtime profile must not be the protected bank profile: %PFC_RC7_DSH_BASE_PROFILE%
  exit /b 4
)

rem Clone-only preflight. v1 rc7-bank clones are rebuilt automatically so a
rem clone touched by an earlier failed package-manager attempt is not reused.
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase RUNTIME_PROFILE --event START >nul 2>nul
"%PY%" -m rc7_release.dsh_runtime_profile --home "%RC7_HOME%" --base-profile "%PFC_RC7_DSH_BASE_PROFILE%" --runtime-profile "%PFC_RC7_DSH_PROFILE%" --output "%RC7_HOME%\state\rc7-dsh-runtime-profile.json" --require-pass
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase RUNTIME_PROFILE --event FAIL --detail "exit=%RC%" >nul 2>nul
  exit /b %RC%
)
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase RUNTIME_PROFILE --event END >nul 2>nul

"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PATCH_GENERATION --event START >nul 2>nul
"%PY%" -m rc7_release.dsh --output "%RC7_HOME%\state\rc7-dsh.patch.yml" --home "%RC7_HOME%" --python "%PFC_PYTHON%" --require-default-enhancements
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PATCH_GENERATION --event FAIL --detail "exit=%RC%" >nul 2>nul
  exit /b %RC%
)
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase PATCH_GENERATION --event END >nul 2>nul

rem Probe clone readiness only. DEGRADED is intentionally not allowed to block
rem the DSH host; plugin persistence has no startup authority.
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase POST_BOOTSTRAP_PROBE --event START >nul 2>nul
"%PY%" -m rc7_release.dsh_post_bootstrap --home "%RC7_HOME%" --profile "%PFC_RC7_DSH_PROFILE%" --output "%RC7_HOME%\state\dsh-post-bootstrap-probe.json"
set "PROBE_RC=%ERRORLEVEL%"
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase POST_BOOTSTRAP_PROBE --event END --detail "exit=%PROBE_RC%" >nul 2>nul

echo [RC7.1] Protected bank DSH profile: %PFC_RC7_DSH_BASE_PROFILE% ^(read-only source^)
echo [RC7.1] RC7 DSH runtime profile: %PFC_RC7_DSH_PROFILE% ^(clean clone, no pre-start npm/plugin install^)
echo [RC7.1] Vision Router: DEFAULT ON / LOCAL-ONLY / PUBLIC REMOTE FORBIDDEN
echo [RC7.1] Memento: DEFAULT ON / RC7 LOCAL DB / R1 NON-AUTHORITATIVE
echo [RC7.1] Canonical R1: %PFC_AITEST_STATE_DIR%\r1\event-stream.jsonl
echo [RC7.1] Maven repo: %PFC_MAVEN_REPO%
echo [RC7.1] Startup status: %RC7_HOME%\state\rc71-startup-status.json
echo [RC7.1] Startup trace:  %RC7_HOME%\state\rc71-startup-trace.jsonl
echo [RC7.1] Persistent plugin repair is POST-START and NON-BLOCKING: packaging\rc7\DSH-PLUGIN-BOOTSTRAP.cmd --install
echo [RC7] Starting DSH now. Startup will not call dsh plugin add/install.
"%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase DSH_HOST_LAUNCH --event START --detail "RC7_PRESTART_COMPLETE" >nul 2>nul
call "%PFC_RC7_DSH_BIN%" --profile "%PFC_RC7_DSH_PROFILE%" --patch "%RC7_HOME%\state\rc7-dsh.patch.yml"
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase DSH_HOST_LAUNCH --event END --detail "exit=0" >nul 2>nul
) else (
  "%PY%" -m rc7_release.startup_trace mark --home "%RC7_HOME%" --phase DSH_HOST_LAUNCH --event FAIL --detail "exit=%RC%" >nul 2>nul
)
exit /b %RC%
