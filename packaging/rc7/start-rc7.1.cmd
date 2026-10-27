@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
where bash >nul 2>nul
if errorlevel 1 (
  echo RC7.1_START_GIT_BASH_NOT_FOUND: bash must be available on PATH 1>&2
  exit /b 31
)
bash "%SCRIPT_DIR%start-rc7.1.sh" %*
exit /b %ERRORLEVEL%
