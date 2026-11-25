@echo off
rem Installs the Bughya extension in Claude Desktop: runs install.ps1 next to this file.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0install.ps1"
