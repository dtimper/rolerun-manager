@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Buscar la tabla de MT (Blanco)

echo ============================================================
echo   BUSCAR LA TABLA DE MT - Pokemon Blanco / Negro
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   No tienes que hacer nada en el juego: solo no lo cierres.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con tu partida de BLANCO.
echo     2. RoleRun Manager CERRADO.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_b2w2_tm_table_capture.py bw
) else (
    python tools_b2w2_tm_table_capture.py bw
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
