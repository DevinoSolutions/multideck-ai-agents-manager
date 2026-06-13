@echo off
REM Double-click to remove multideck shortcuts and PATH entry.
powershell -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
pause
