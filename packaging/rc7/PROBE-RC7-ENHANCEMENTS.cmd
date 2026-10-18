@echo off
setlocal
set "ROOT=%~dp0\..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PY=%ROOT%\workspace-template\runtime\python\python.exe"
if not exist "%PY%" (
  echo [RC7] package-local Python missing: %PY%
  exit /b 2
)
pushd "%ROOT%"
"%PY%" -m rc7_release.optional_enhancements --home "%ROOT%" probe
if errorlevel 2 goto :fail
"%PY%" -m rc7_release.vision_capability --home "%ROOT%"
if errorlevel 2 goto :fail
"%PY%" -m rc7_release.bank_binding probe
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
:fail
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
