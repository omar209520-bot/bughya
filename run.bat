@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run: preparing the program environment - internet is needed once...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" "Bughya.pyw"
