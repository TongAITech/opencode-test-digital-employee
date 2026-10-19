@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "RC7_HOME=%%~fI"
set "PY=%RC7_HOME%\workspace-template\runtime\python\python.exe"
if not exist "%PY%" (
  echo [RC7] package-local Python missing: %PY%
  exit /b 2
)

set "PYTHONUTF8=1"
set "PFC_AITEST_HOME=%RC7_HOME%"
set "PFC_AITEST_STATE_DIR=%RC7_HOME%\runtime-state"
if not defined PFC_RC7_DSH_PROFILE set "PFC_RC7_DSH_PROFILE=rc7-bank"
if not exist "%RC7_HOME%\state" mkdir "%RC7_HOME%\state"

set "MODE=probe"
if /I "%~1"=="--install" set "MODE=install"

if /I "%MODE%"=="install" (
  echo [RC7] POST-START persistent plugin repair requested for %PFC_RC7_DSH_PROFILE%.
  echo [RC7] This may use the bank DSH package manager, but failure is NON-BLOCKING and never touches web.
  "%PY%" -m rc7_release.dsh_post_bootstrap --home "%RC7_HOME%" --profile "%PFC_RC7_DSH_PROFILE%" --attempt-persistent-install --output "%RC7_HOME%\state\dsh-post-bootstrap-install.json"
  set "RC=%ERRORLEVEL%"
) else (
  echo [RC7] Probing cloned DSH plugin readiness only; no install will run.
  "%PY%" -m rc7_release.dsh_post_bootstrap --home "%RC7_HOME%" --profile "%PFC_RC7_DSH_PROFILE%" --output "%RC7_HOME%\state\dsh-post-bootstrap-probe.json"
  set "RC=%ERRORLEVEL%"
)

if not "%RC%"=="0" (
  echo [RC7] Bootstrap command rejected. Check state output. DSH startup remains independent.
  exit /b %RC%
)
echo [RC7] Post-start plugin bootstrap completed. PASS or DEGRADED is recorded under state\.
exit /b 0
