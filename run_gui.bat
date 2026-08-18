@echo off
REM Double-click launcher for the Matrix G2 Performance dashboard.
cd /d "%~dp0"
python run_gui.py %*
pause
