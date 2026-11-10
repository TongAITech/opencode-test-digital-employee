@echo off
setlocal
set "RC72_CANDIDATE="
set "RC72_AMBIGUOUS="

call :consider "%~dp0"
if not defined RC72_CANDIDATE (
  for /d %%D in ("%~dp0*") do call :consider "%%~fD"
)
if not defined RC72_CANDIDATE (
  for /d %%D in ("%~dp0*") do for /d %%E in ("%%~fD\*") do call :consider "%%~fE"
)
if defined RC72_AMBIGUOUS (
  echo Multiple nested RC7.2 package roots found. Open the intended package folder directly.
  exit /b 4
)
if not defined RC72_CANDIDATE (
  echo RC7.2 package root not found. Check the ZIP extraction folder and package identity files.
  exit /b 2
)

cd /d "%RC72_CANDIDATE%"
set "RC72_BASH="
for %%G in ("%ProgramFiles%\Git\bin\bash.exe" "%ProgramFiles(x86)%\Git\bin\bash.exe" "%LocalAppData%\Programs\Git\bin\bash.exe") do if exist "%%~G" set "RC72_BASH=%%~G"
if defined RC72_BASH goto launch
where bash.exe >nul 2>nul
if errorlevel 1 (
  echo Git Bash is required. Bind the approved bank Git Bash installation.
  pause
  exit /b 2
)
set "RC72_BASH=bash.exe"
:launch
"%RC72_BASH%" --noprofile --norc ./packaging/rc7.2/AITEST.sh
set "RC72_RESULT=%ERRORLEVEL%"
if not "%RC72_RESULT%"=="0" pause
exit /b %RC72_RESULT%

:consider
if not exist "%~1\SOURCE_COMMIT" exit /b 0
if not exist "%~1\PACKAGE_MANIFEST.json" exit /b 0
if not exist "%~1\RC72_RELEASE_IDENTITY.json" exit /b 0
if not exist "%~1\workspace-template\runtime\python\python.exe" exit /b 0
if not exist "%~1\packaging\rc7.2\AITEST.sh" exit /b 0
if defined RC72_CANDIDATE (
  set "RC72_AMBIGUOUS=1"
  exit /b 0
)
for %%I in ("%~1") do set "RC72_CANDIDATE=%%~fI"
exit /b 0
