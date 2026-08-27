@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Captura de baja en combate (Negro 2)

echo ============================================================
echo   CAPTURA DE BAJA EN COMBATE - Pokemon Negro 2 / Blanco 2
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con tu partida de Negro 2, en el mapa.
echo     2. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_b2w2_battle_faint_capture.py
) else (
    python tools_b2w2_battle_faint_capture.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
