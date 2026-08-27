@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Comprobar HeartGold

echo ============================================================
echo   COMPROBAR LA LECTURA - Pokemon HeartGold
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Te va a ensenar el equipo, el dinero, las medallas y las
echo   cajas del PC tal y como los va a leer RoleRun. Comparalo
echo   con lo que ves en el juego.
echo.
echo   NO hace falta guardar: esto lee el estado actual.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con HeartGold cargado.
echo     2. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_hgss_read_check.py
) else (
    python tools_hgss_read_check.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
