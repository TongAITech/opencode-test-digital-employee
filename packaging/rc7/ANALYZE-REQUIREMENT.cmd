@echo off
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not defined PFC_PYTHON_BIN if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON_BIN=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON_BIN set "PFC_PYTHON_BIN=python"
cd /d "%ROOT%"
"%PFC_PYTHON_BIN%" -m rc7_release.requirement_cli %*
exit /b %ERRORLEVEL%
