@echo off
cd /d "%~dp0"
python paivittainen.py
start "" "raportit\viimeisin.html"
pause
