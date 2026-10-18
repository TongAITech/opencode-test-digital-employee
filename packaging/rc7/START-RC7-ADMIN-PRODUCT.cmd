@echo off
setlocal
set "ROOT=%~dp0\..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PY=%ROOT%\workspace-template\runtime\python\python.exe"
if not exist "%PY%" (
  echo [RC7] package-local Python missing: %PY%
  exit /b 2
)
if not defined PFC_RC7_R1_PATH set "PFC_RC7_R1_PATH=%ROOT%\runtime-state\r1\event-stream.jsonl"
pushd "%ROOT%"
"%PY%" -m rc7_admin.product_server
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
