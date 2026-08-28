@echo off
setlocal
cd /d "%~dp0"
title Cuando se puede escribir en HeartGold
python tools_hgss_ventana_de_escritura.py
if errorlevel 1 pause
endlocal
