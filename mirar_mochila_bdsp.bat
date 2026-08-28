@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Mirar la mochila (Perla Reluciente)
echo.
echo   ============================================================
echo     MIRAR LA MOCHILA - Pokemon Perla Reluciente
echo   ============================================================
echo.
echo   SOLO LECTURA. No escribe ni un byte en tu partida.
echo.
echo   Necesita Ryujinx abierto con tu partida cargada.
echo.
pause
echo.
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "tools/mirar_mochila_bdsp.py"
) else (
    python "tools/mirar_mochila_bdsp.py"
)
echo.
pause
