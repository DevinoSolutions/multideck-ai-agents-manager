@echo off
REM Re-tile EVERY open project window (and launch any that are missing) into the grid.
powershell -ExecutionPolicy Bypass -File "%~dp0multideck.ps1" -RetileAll
