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
set "PFC_AITEST_HOME=%RC7_HOME%"
set "PFC_PYTHON=%PY%"
set "PFC_CODEGRAPH_BIN=%RC7_HOME%\workspace-template\runtime\code-intelligence\codegraph\codegraph-server-win32-x64.exe"
set "PFC_CHROMIUM_BIN=%RC7_HOME%\workspace-template\runtime\browser\chrome-win64\chrome.exe"
set "PFC_JAVA_BIN=%RC7_HOME%\workspace-template\runtime\java\bin\java.exe"
set "PFC_MAVEN_BIN=%RC7_HOME%\workspace-template\runtime\maven\bin\mvn.cmd"
set "PFC_K6_BIN=%RC7_HOME%\workspace-template\runtime\k6\k6.exe"
if "%PFC_RC7_SKIP_QUALIFY%"=="1" goto :plugins
"%PY%" -m rc7_release.final_unified_qualification --home "%RC7_HOME%" --require-pass
if errorlevel 1 exit /b %errorlevel%
:plugins
"%PY%" -m rc7_release.dsh_plugins --home "%RC7_HOME%" --profile web --output "%RC7_HOME%\state\dsh-plugin-install.json"
if errorlevel 1 exit /b %errorlevel%
where dsh >nul 2>nul
if errorlevel 1 (
  echo [RC7] Bank DSH host is not on PATH. Package is complete; bind the bank DSH host and rerun AITEST.cmd.
  exit /b 3
)
if not exist "%RC7_HOME%\state" mkdir "%RC7_HOME%\state"
"%PY%" -m rc7_release.dsh --output "%RC7_HOME%\state\rc7-dsh.patch.yml" --home "%RC7_HOME%" --python "%PY%"
if errorlevel 1 exit /b %errorlevel%
dsh --profile web --patch "%RC7_HOME%\state\rc7-dsh.patch.yml"
exit /b %errorlevel%
