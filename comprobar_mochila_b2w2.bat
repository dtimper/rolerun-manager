@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Comprobar la mochila (Negro 2)

echo ============================================================
echo   COMPROBAR LA MOCHILA - Pokemon Negro 2 / Blanco 2
echo ============================================================
echo.
echo   SOLO LECTURA. No escribe nada en tu partida.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con tu partida de Negro 2.
echo     2. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_b2w2_bag_read_check.py
) else (
    python tools_b2w2_bag_read_check.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
