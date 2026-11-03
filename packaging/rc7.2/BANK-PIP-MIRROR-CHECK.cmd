@echo off
setlocal
for %%I in ("%~dp0\..\..") do set "RC72_ROOT=%%~fI"
set "RC72_PYTHON=%RC72_ROOT%\workspace-template\runtime\python\python.exe"
if not exist "%RC72_PYTHON%" (
  echo Package Python is required. Host Python or pip cannot qualify this package.
  exit /b 2
)
set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONNOUSERSITE=1"
pushd "%RC72_ROOT%"
"%RC72_PYTHON%" -s -m rc7_release.rc72_windows_clean_qualification %* --package-root "%RC72_ROOT%" --bank-field --require-pass
set "RC72_RESULT=%ERRORLEVEL%"
popd
exit /b %RC72_RESULT%
