@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Buscar el ancla (Blanco)

echo ============================================================
echo   BUSCAR EL EQUIPO EN MEMORIA - Pokemon Blanco / Negro
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Te preguntara tres cosas: cuantos Pokemon llevas, cuanto
echo   dinero tienes y cuantas medallas. Miralas en el juego
echo   antes de seguir; con ellas se comprueba el resultado.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con tu partida de Blanco.
echo     2. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_bw_anchor_capture.py
) else (
    python tools_bw_anchor_capture.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
