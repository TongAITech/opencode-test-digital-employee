@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "RC7_HOME=%%~fI"
set "PY=%RC7_HOME%\workspace-template\runtime\python\python.exe"
if not exist "%RC7_HOME%\state" mkdir "%RC7_HOME%\state"
"%PY%" -m rc7_release.final_unified_qualification --home "%RC7_HOME%" --output "%RC7_HOME%\state\final-unified-qualification.json" --require-pass
exit /b %errorlevel%
