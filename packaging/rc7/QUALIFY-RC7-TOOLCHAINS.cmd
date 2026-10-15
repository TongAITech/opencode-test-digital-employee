@echo off
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not defined PFC_PYTHON_BIN if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON_BIN=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON_BIN set "PFC_PYTHON_BIN=python"
if not defined PFC_CODEGRAPH_BIN if exist "%ROOT%\workspace-template\runtime\code-intelligence\codegraph\codegraph-server-win32-x64.exe" set "PFC_CODEGRAPH_BIN=%ROOT%\workspace-template\runtime\code-intelligence\codegraph\codegraph-server-win32-x64.exe"
if not exist "%ROOT%\state\qualification" mkdir "%ROOT%\state\qualification"
cd /d "%ROOT%"
"%PFC_PYTHON_BIN%" -m rc7_release.toolchain_qualification --output "%ROOT%\state\qualification\rc7-toolchains.json"
exit /b %ERRORLEVEL%
