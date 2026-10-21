@echo off
cd /d "%~dp0"
python run.py --open-browser
if errorlevel 1 pause
