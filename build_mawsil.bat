@echo off
rem Build the Bughya Claude extension: the connector as a standalone program (dist\BughyaClaude),
rem then packed with mcpb\manifest.json into dist\bughya.mcpb. Needs Node.js for the packing step.
rem Not part of the Bughya release: build_exe.bat does not include it.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
.venv\Scripts\python.exe -m pip install -q pyinstaller mcp
.venv\Scripts\pyinstaller.exe --noconfirm --clean --console --onedir --name BughyaClaude --paths app ^
  --hidden-import mawsil --hidden-import bahth --hidden-import nass --hidden-import bawwaba --hidden-import maktaba --hidden-import sura ^
  --hidden-import mcp.server.mcpserver --hidden-import mcp.server.mcpserver.exceptions ^
  --icon assets\bughya.ico --add-data "app\data;data" app\mawsil_exe.py || exit /b 1
if exist dist\mcpb-bundle rmdir /s /q dist\mcpb-bundle
mkdir dist\mcpb-bundle
xcopy /e /i /q dist\BughyaClaude dist\mcpb-bundle\server >nul
copy /y mcpb\manifest.json dist\mcpb-bundle\ >nul
copy /y assets\bughya.png dist\mcpb-bundle\icon.png >nul
call npx -y @anthropic-ai/mcpb pack dist\mcpb-bundle dist\bughya.mcpb
echo Done: dist\bughya.mcpb  (send it with mcpb\install.ps1 and the .bat installer next to it)
