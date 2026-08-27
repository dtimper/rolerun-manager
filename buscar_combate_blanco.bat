@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Buscar el carril de combate (Blanco)

echo ============================================================
echo   BUSCAR EL CARRIL DE COMBATE - Pokemon Blanco / Negro
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Te pedira que entres en un combate y que le digas cuantos
echo   PS le quedan a tu Pokemon EN PANTALLA. Cuanto mas raro sea
echo   ese numero, mejor: con la vida llena es mas dificil.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con tu partida de BLANCO.
echo     2. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_bw_battle_capture.py
) else (
    python tools_bw_battle_capture.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
