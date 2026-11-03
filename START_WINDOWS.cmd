@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\Start.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. See the message above and desktop\README.md.
  pause
)
