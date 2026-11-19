@echo off
REM Builds a standalone PhoneCam.exe (dist\PhoneCam.exe)
cd /d "%~dp0"
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --onefile --name PhoneCam --add-data "static;static" phonecam.py
