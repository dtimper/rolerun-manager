@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Buscar el ancla (HeartGold)

echo ============================================================
echo   BUSCAR EL EQUIPO EN MEMORIA - Pokemon HeartGold
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   No te va a preguntar nada: se saca los datos de tu propia
echo   partida guardada y busca en memoria ESOS Pokemon.
echo.
echo   Antes de continuar:
echo     1. GUARDA DENTRO DEL JUEGO (importante).
echo     2. Deja melonDS abierto con HeartGold cargado.
echo     3. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_hgss_anchor_capture.py
) else (
    python tools_hgss_anchor_capture.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
