@echo off
setlocal
cd /d "%~dp0"
title Grabar la escritura en HeartGold
python tools_hgss_grabar_la_escritura.py
if errorlevel 1 pause
endlocal
