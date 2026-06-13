@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python -m collector.run_all --open-browser --enrich-limit 300 --enrich-interval 180
pause
