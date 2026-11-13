@echo off
cd /d "%~dp0"
python historiatesti.py --vertaa-kulut
start "" "raportit\historiatesti.html"
pause
