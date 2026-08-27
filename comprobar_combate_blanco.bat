@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Que ve en el combate (Blanco)

echo ============================================================
echo   QUE VE ROLERUN EN EL COMBATE - Pokemon Blanco / Negro
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Ejecutala CON EL COMBATE EN PANTALLA, y mejor si tienes
echo   algun Pokemon debilitado: es el caso que esta fallando.
echo.
echo   No tienes que hacer nada mas: lee las seis filas y te dice
echo   cual acepta y cual rechaza, y por que.
echo.
echo   Antes de continuar:
echo     - melonDS abierto y EN COMBATE, con tu partida de BLANCO.
echo     - RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_bw_battle_check.py
) else (
    python tools_bw_battle_check.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
