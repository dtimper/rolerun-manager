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
    echo El motor necesita actualizarse para la calibracion viva de mochila de ORAS.
    echo Se ejecutara preparar_motor.bat automaticamente.
    echo.
    call preparar_motor.bat
    if errorlevel 1 exit /b 1
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 main.py
) else (
    python main.py
)
if errorlevel 1 pause
