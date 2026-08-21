@echo off
setlocal
cd /d "%~dp0"
title RoleRun Manager

set "ENGINE_MARKER=engine\publish\rolerun_engine_version.txt"
set "ENGINE_READY=0"
if exist "%ENGINE_MARKER%" (
    findstr /b /c:"oras-inventory-live-v2" "%ENGINE_MARKER%" >nul 2>nul
    if not errorlevel 1 set "ENGINE_READY=1"
)

if "%ENGINE_READY%"=="0" (
    echo ==========================================================
 echo El motor de guardados necesita actualizarse para admitir la
 echo calibracion de mochila viva de ORAS.
    echo ==========================================================
    echo.
    call preparar_motor.bat
    if errorlevel 1 goto :engine_error
)

if not exist "data\moves.json" (
    echo La base de movimientos localizada no esta preparada.
    echo Ejecuta preparar_motor.bat.
    pause
    exit /b 1
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 goto :error
    py -3 main.py
    if errorlevel 1 goto :error
) else (
    python -m pip install -r requirements.txt
    if errorlevel 1 goto :error
    python main.py
    if errorlevel 1 goto :error
)
exit /b 0

:engine_error
echo.
echo No se pudo actualizar el motor. Haz una captura completa de la ventana.
pause
exit /b 1

:error
echo.
echo ==========================================================
echo RoleRun Manager no pudo iniciarse.
echo Haz una captura de TODO el error que aparece encima.
echo ==========================================================
pause
exit /b 1
