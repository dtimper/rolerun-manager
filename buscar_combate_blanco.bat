@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Las dos copias de combate (Blanco)

echo ============================================================
echo   LAS DOS COPIAS DE COMBATE - Pokemon Blanco / Negro
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Va en tres pasos y necesita DOS golpes recibidos.
echo   Usa el Pokemon que tengas en el campo, sea cual sea.
echo.
echo     1. En combate, te preguntara cuantos PS le quedan.
echo     2. Recibes un golpe y le dices cuantos le quedan ahora.
echo        Espera a que la barra se pare del todo.
echo     3. Recibes OTRO golpe mientras ella mira. Con eso ve
echo        cual de las copias baja la vida antes.
echo.
echo   Si el Pokemon se debilita, sirve igual: 0 es un numero
echo   valido. Lo unico que no vale es que los PS no cambien.
echo.
echo   Antes de continuar:
echo     - melonDS abierto con tu partida de BLANCO.
echo     - RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_bw_battle_lanes_capture.py
) else (
    python tools_bw_battle_lanes_capture.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
