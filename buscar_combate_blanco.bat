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
echo   El intento anterior encontro dos filas, pero una era del
echo   Pokemon rival. Esta busca TODAS las que describen al TUYO
echo   y luego mira cual baja la vida antes.
echo.
echo   QUE TIENES QUE HACER:
echo     1. Entra en un combate. Mejor si tu Pokemon ya ha
echo        recibido algun golpe: con la vida llena hay mas
echo        coincidencias por casualidad.
echo     2. Pulsa INTRO aqui. Buscara las filas y te las dira.
echo     3. Prepara un turno en el que TU Pokemon reciba dano,
echo        SIN ejecutarlo. Vuelve aqui y pulsa INTRO.
echo     4. Ejecuta el turno en el juego. Se para sola despues.
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
