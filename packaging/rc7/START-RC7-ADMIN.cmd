@echo off
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not defined PFC_PYTHON_BIN if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON_BIN=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON_BIN set "PFC_PYTHON_BIN=python"
if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state"
if not defined PFC_RC7_R1_PATH set "PFC_RC7_R1_PATH=%PFC_AITEST_STATE_DIR%\r1\event-stream.jsonl"
if not defined PFC_RC7_ADMIN_HOST set "PFC_RC7_ADMIN_HOST=127.0.0.1"
if not defined PFC_RC7_ADMIN_PORT set "PFC_RC7_ADMIN_PORT=4097"
if not exist "%PFC_AITEST_STATE_DIR%\r1" mkdir "%PFC_AITEST_STATE_DIR%\r1"
cd /d "%ROOT%"
echo [RC7 ADMIN] Canonical R1: %PFC_RC7_R1_PATH%
"%PFC_PYTHON_BIN%" -m rc7_admin --r1 "%PFC_RC7_R1_PATH%" --host "%PFC_RC7_ADMIN_HOST%" --port %PFC_RC7_ADMIN_PORT%
exit /b %ERRORLEVEL%
