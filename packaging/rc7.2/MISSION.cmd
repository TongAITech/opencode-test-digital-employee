@echo off
setlocal
for %%I in ("%~dp0\..\..") do set "RC72_ROOT=%%~fI"
set "RC72_PYTHON=%RC72_ROOT%\workspace-template\runtime\python\python.exe"
if not exist "%RC72_PYTHON%" exit /b 2
if not exist "%RC72_ROOT%\SOURCE_COMMIT" exit /b 2
set "RC72_SOURCE="
set /p "RC72_SOURCE="<"%RC72_ROOT%\SOURCE_COMMIT"
if not defined RC72_SOURCE exit /b 2
set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONNOUSERSITE=1"
pushd "%RC72_ROOT%"
"%RC72_PYTHON%" -s -m rc7_release.rc72_mission_cli %* --source-commit "%RC72_SOURCE%" --package-root "%RC72_ROOT%"
set "RC72_RESULT=%ERRORLEVEL%"
popd
exit /b %RC72_RESULT%
