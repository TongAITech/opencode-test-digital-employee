@echo off
setlocal
cd /d "%~dp0"
if exist "packaging\rc7.2\AITEST.sh" goto findbash
cd /d "%~dp0\..\.."
:findbash
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
