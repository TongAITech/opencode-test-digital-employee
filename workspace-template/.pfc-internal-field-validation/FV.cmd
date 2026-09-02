@echo off
setlocal
set "PACKAGE_ROOT=%~dp0.."
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONPATH=%PACKAGE_ROOT%\ai-test\runtime;%PYTHONPATH%"
set "PORTABLE_PYTHON=%PACKAGE_ROOT%\runtime\python\python.exe"
if not exist "%PORTABLE_PYTHON%" (
  echo PORTABLE_PYTHON_NOT_FOUND: "%PORTABLE_PYTHON%" 1>&2
  exit /b 86
)
"%PORTABLE_PYTHON%" "%~dp0tools\fv_tool.py" %*
exit /b %ERRORLEVEL%
