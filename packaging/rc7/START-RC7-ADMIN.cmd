@echo off
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not defined PFC_PYTHON_BIN set "PFC_PYTHON_BIN=python"
if not defined PFC_RC7_R1_PATH set "PFC_RC7_R1_PATH=%ROOT%\state\rc7-r1.jsonl"
if not defined PFC_RC7_ADMIN_HOST set "PFC_RC7_ADMIN_HOST=127.0.0.1"
if not defined PFC_RC7_ADMIN_PORT set "PFC_RC7_ADMIN_PORT=4097"
if not exist "%ROOT%\state" mkdir "%ROOT%\state"
cd /d "%ROOT%"
"%PFC_PYTHON_BIN%" -m rc7_admin --r1 "%PFC_RC7_R1_PATH%" --host "%PFC_RC7_ADMIN_HOST%" --port %PFC_RC7_ADMIN_PORT%
exit /b %ERRORLEVEL%
