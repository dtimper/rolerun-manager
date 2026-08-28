@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Cual manda (HeartGold)

echo ============================================================
echo   QUE BLOQUE MANDA - Pokemon HeartGold
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Te va a ensenar los bloques del guardado que hay en memoria
echo   y despues te pedira que cambies algo dentro del juego: que
echo   te quiten PS en un combate, o usar una Pocion. Con eso se
echo   sabe cual de los bloques usa el juego de verdad.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con HeartGold cargado.
echo     2. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_hgss_bloque_capture.py
) else (
    python tools_hgss_bloque_capture.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
