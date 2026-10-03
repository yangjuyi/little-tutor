@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_little_tutor.ps1"
if errorlevel 1 (
  echo.
  echo little-tutor failed to stop cleanly.
  pause
)
endlocal
