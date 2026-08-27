@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Buscar la mochila (Negro 2)

echo ============================================================
echo   BUSCAR LA MOCHILA Y EL DINERO - Pokemon Negro 2 / Blanco 2
echo ============================================================
echo.
echo   Esta herramienta SOLO LEE la memoria de melonDS.
echo   No escribe nada en tu partida y no activa ninguna funcion.
echo.
echo   Antes de continuar:
echo     1. melonDS abierto con tu partida de Negro 2.
echo     2. RoleRun Manager CERRADO.
echo     3. Ten a mano la MOCHILA para mirar cantidades exactas.
echo     4. A mitad te pedira GASTAR o COMPRAR algo, asi que quedate
echo        cerca de una tienda o con objetos que puedas usar.
echo.
pause
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_b2w2_bag_capture.py
) else (
    python tools_b2w2_bag_capture.py
)

if errorlevel 1 (
    echo.
    echo Algo ha fallado. Copia el mensaje de arriba y enviamelo.
    pause
)
