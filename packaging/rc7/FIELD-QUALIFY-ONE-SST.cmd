@echo off
setlocal EnableExtensions DisableDelayedExpansion
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
set "PY=%PFC_PYTHON_BIN%"
if not defined PY (
  if exist "%ROOT%\workspace-template\runtime\python\python.exe" (
    set "PY=%ROOT%\workspace-template\runtime\python\python.exe"
  ) else (
    set "PY=python"
  )
)
set "PYTHONUTF8=1"
if not defined PFC_AITEST_HOME set "PFC_AITEST_HOME=%ROOT%"
if not defined PFC_AITEST_STATE_DIR set "PFC_AITEST_STATE_DIR=%ROOT%\runtime-state"
if not defined PFC_RC7_SOURCE_COMMIT if exist "%ROOT%\SOURCE_COMMIT" set /p PFC_RC7_SOURCE_COMMIT=<"%ROOT%\SOURCE_COMMIT"
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
pushd "%ROOT%" >nul
"%PY%" -m rc7_release.one_sst_field_qualification %*
set "RC=%ERRORLEVEL%"
popd >nul
exit /b %RC%
