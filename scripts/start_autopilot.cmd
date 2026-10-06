@echo off
rem Start the LAB1 autopilot detached (D39). Status: labs\AUTOPILOT_STATUS.txt, log: labs\autopilot.log
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
start "LAB1 autopilot" /min cmd /c ".venv\Scripts\python.exe scripts\autopilot.py >> labs\autopilot-console.log 2>&1"
echo autopilot started; status in labs\AUTOPILOT_STATUS.txt
