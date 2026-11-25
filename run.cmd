@echo off
setlocal enabledelayedexpansion
rem  Domingo - start the UI on the machine that runs the model.
rem  Put options in domingo.json next to this file, or pass them here:
rem      run.cmd --token secret --port 8899
cd /d "%~dp0"

set "PY=%DOMINGO_PY%"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
   echo Domingo needs Python 3.9 or newer, and none was found.
   echo   Install it from https://www.python.org/downloads/windows/
   echo   and tick "Add python.exe to PATH" during setup.
   echo   Then open a new window and run this again.
   echo.
   echo   If you already have a Python you want this to use, point at it:
   echo     setx DOMINGO_PY "C:\path\to\python.exe"
   echo   then open a new window and run this again.
   pause
   exit /b 1
)

%PY% -u domingo.py %*
if errorlevel 1 pause
