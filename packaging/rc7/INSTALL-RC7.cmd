@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "RC7_HOME=%%~fI"
set "PY=%RC7_HOME%\workspace-template\runtime\python\python.exe"
if "%~1"=="" (set "TARGET=D:\PFC\AITest-RC7") else (set "TARGET=%~1")
set "MODE="
if exist "%TARGET%" set "MODE=--upgrade"
"%PY%" -m rc7_release.workspace_install --source "%RC7_HOME%" --target "%TARGET%" %MODE%
if errorlevel 1 exit /b %errorlevel%
echo [RC7] Installed at %TARGET%
echo [RC7] Start with: "%TARGET%\packaging\rc7\AITEST.cmd"
exit /b 0
