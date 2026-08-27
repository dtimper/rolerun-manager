@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Cual es cual en combate (Blanco)

echo ============================================================
echo   CUAL DE LAS DOS FILAS MANDA - Pokemon Blanco / Negro
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Ya sabemos DONDE estan las dos copias de combate. Falta
echo   saber cual manda en pantalla, y eso solo se ve mirando
echo   cual de las dos baja la vida un pelin mas tarde.
echo.
echo   QUE TIENES QUE HACER:
echo     1. Entra en un combate con melonDS.
echo     2. Prepara un turno en el que TU Pokemon vaya a recibir
echo        un golpe. No lo ejecutes todavia.
echo     3. Vuelve aqui, pulsa INTRO, y ejecuta el turno.
echo     4. La herramienta se para sola unos segundos despues.
echo.
echo   Antes de continuar:
echo     - melonDS abierto con tu partida de BLANCO.
echo     - RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_b2w2_battle_timing_capture.py bw
) else (
    python tools_b2w2_battle_timing_capture.py bw
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
