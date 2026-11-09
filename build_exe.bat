@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
.venv\Scripts\python.exe -m pip install -q pyinstaller
.venv\Scripts\pyinstaller.exe --noconfirm --clean --noconsole --onedir --name Bughya --paths app ^
  --hidden-import maktaba --hidden-import bahth --hidden-import nass --hidden-import sura --hidden-import mustalah ^
  --hidden-import tadqiq --hidden-import bawwaba --hidden-import wajiha --hidden-import musawwada --icon assets\bughya.ico --splash assets\splash.png --version-file assets\version.txt --collect-all webview --hidden-import clr --hidden-import tkinter_dialog --hidden-import ayat --add-data "app\data;data" ^
  --hidden-import readers.pdf --hidden-import readers.office --hidden-import readers.text --hidden-import readers.ocr ^
  --hidden-import readers.layout --hidden-import readers.arabic_pdf ^
  --collect-all winrt.windows.media.ocr --collect-all winrt.windows.graphics.imaging --collect-all winrt.windows.globalization ^
  --collect-all winrt.windows.storage.streams --collect-all winrt.windows.foundation --collect-all winrt.runtime ^
  --collect-submodules winrt --collect-submodules openpyxl ^
  Bughya.pyw
echo Done: dist\Bughya\Bughya.exe
