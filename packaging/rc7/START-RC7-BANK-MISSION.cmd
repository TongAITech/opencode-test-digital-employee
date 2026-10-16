@echo off
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
if not defined PFC_PYTHON_BIN if exist "%ROOT%\workspace-template\runtime\python\python.exe" set "PFC_PYTHON_BIN=%ROOT%\workspace-template\runtime\python\python.exe"
if not defined PFC_PYTHON_BIN set "PFC_PYTHON_BIN=python"
if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state"
if not defined PFC_RC7_R1_PATH set "PFC_RC7_R1_PATH=%PFC_AITEST_STATE_DIR%\r1\event-stream.jsonl"
if not defined PFC_RC7_SOURCE_COMMIT if exist "%ROOT%\SOURCE_COMMIT" set /p PFC_RC7_SOURCE_COMMIT=<"%ROOT%\SOURCE_COMMIT"
if not defined PFC_RC7_MISSION_ID (
  echo [RC7] HOLD: PFC_RC7_MISSION_ID is required.
  exit /b 2
)
if not defined PFC_RC7_RELEASE_ID (
  echo [RC7] HOLD: PFC_RC7_RELEASE_ID is required.
  exit /b 2
)
if not defined PFC_RC7_MISSION_GOAL (
  echo [RC7] HOLD: PFC_RC7_MISSION_GOAL is required.
  exit /b 2
)
if not exist "%PFC_AITEST_STATE_DIR%\r1" mkdir "%PFC_AITEST_STATE_DIR%\r1"
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
cd /d "%ROOT%"
echo [RC7] Mission R1: %PFC_RC7_R1_PATH%
"%PFC_PYTHON_BIN%" -m rc7_runtime.bank_mission --r1 "%PFC_RC7_R1_PATH%" --mission-id "%PFC_RC7_MISSION_ID%" --release-id "%PFC_RC7_RELEASE_ID%" --goal "%PFC_RC7_MISSION_GOAL%" %*
exit /b %ERRORLEVEL%
