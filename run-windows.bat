@echo off
REM Video Download - one double-click launcher for Windows.
REM
REM Team usage: clone/open the repo, then DOUBLE-CLICK this file.
REM   - First run: creates a local .venv and installs dependencies (needs internet).
REM   - Every run after: just launches the app instantly.
REM   - First time the app opens, it downloads Chromium (~150 MB, one-time).
REM
REM Requires Python 3.10+ installed from https://www.python.org/downloads/windows/
REM (tick "Add python.exe to PATH" in the installer).

setlocal
cd /d "%~dp0"

REM Pick a Python that is 3.10+ AND has tkinter (the window needs Tk).
REM Kept as top-level lines (not a parenthesized block) so each guard is
REM re-evaluated live — %errorlevel% inside a block expands at parse time.
set "PYCMD="
py -3.13 -c "import tkinter" >nul 2>nul && set "PYCMD=py -3.13"
if not defined PYCMD py -3.12 -c "import tkinter" >nul 2>nul && set "PYCMD=py -3.12"
if not defined PYCMD py -3.11 -c "import tkinter" >nul 2>nul && set "PYCMD=py -3.11"
if not defined PYCMD py -3.10 -c "import tkinter" >nul 2>nul && set "PYCMD=py -3.10"
if not defined PYCMD py -3 -c "import sys,tkinter; sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD python -c "import sys,tkinter; sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>nul && set "PYCMD=python"
if not defined PYCMD (
  echo ERROR: no suitable Python found ^(need 3.10+ WITH tkinter^).
  echo Install Python 3.10+ from https://www.python.org/downloads/windows/
  echo Tick "Add python.exe to PATH" during install, then re-run this file.
  pause
  exit /b 1
)

REM Check the actual entry point, not just the .venv dir — a half-finished
REM first install would otherwise be skipped and then crash on launch.
if not exist ".venv\Scripts\tiktok-music-dl-gui.exe" (
  echo === First-time setup ^(one-time, ~1-2 min^) ===
  echo [1/3] Creating virtual environment...
  %PYCMD% -m venv .venv
  echo [2/3] Upgrading pip...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  echo [3/3] Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install -e .
  echo Setup done.
)

echo Launching Video Download...
".venv\Scripts\tiktok-music-dl-gui.exe"
if %errorlevel% neq 0 pause
