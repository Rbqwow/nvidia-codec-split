@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0Install.ps1" -Action Restore %*
set "restoreExit=%errorlevel%"
if not "%restoreExit%"=="0" echo Restore failed. Read the error above before retrying.
pause
exit /b %restoreExit%
