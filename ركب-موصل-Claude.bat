@echo off
rem Bughya: set up the Claude connector (app\mawsil.py) in this folder, then add it to Claude.
rem Double-click to prepare; drag claude_desktop_config.json onto this file to add it to Claude.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Preparing the connector - internet is needed once, this takes a few minutes...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Python is not installed. Install it from python.org, then run this file again.
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import mcp, pymupdf" 2>nul || (
  echo Installing the required packages...
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt mcp
)
.venv\Scripts\python.exe app\mawsil_tarkib.py %1
