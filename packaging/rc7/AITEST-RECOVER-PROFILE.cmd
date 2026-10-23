@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "RC7_HOME=%%~fI"
set "RECOVERY_PROFILE=rc7-bank-recovery"
if defined PFC_RC7_RECOVERY_PROFILE set "RECOVERY_PROFILE=%PFC_RC7_RECOVERY_PROFILE%"

rem This is intentionally non-destructive. It does not delete R1, Evidence,
rem Mission/Task/Attempt state, the protected web profile, or old DSH sessions.
rem It only starts RC7 with a fresh isolated runtime profile cloned from web.
set "PFC_RC7_DSH_PROFILE=%RECOVERY_PROFILE%"
echo [RC7.1] Recovery mode: fresh DSH runtime profile = %PFC_RC7_DSH_PROFILE%
echo [RC7.1] Canonical R1 is preserved at %RC7_HOME%\runtime-state\r1\event-stream.jsonl
echo [RC7.1] Old DSH session/history is not deleted. This entry avoids reusing the normal rc7-bank runtime profile.
call "%~dp0AITEST.cmd"
exit /b %ERRORLEVEL%
