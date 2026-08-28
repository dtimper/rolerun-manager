@echo off
setlocal
cd /d "%~dp0"
title Que copia del guardado lee HeartGold
python tools_hgss_cual_lee_el_juego.py
if errorlevel 1 pause
endlocal
