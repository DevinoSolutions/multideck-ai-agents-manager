@echo off
REM multideck - launch + tile your project windows. Pass -RetileAll / -DryRun / -Config <path>.
powershell -ExecutionPolicy Bypass -File "%~dp0multideck.ps1" %*
