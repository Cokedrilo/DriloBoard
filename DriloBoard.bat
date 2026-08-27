@echo off
rem Runs DriloBoard from source, without a console window.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "driloboard.py"
