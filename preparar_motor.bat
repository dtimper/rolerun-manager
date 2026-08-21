@echo off
setlocal
cd /d "%~dp0"
title RoleRun Manager

set "REPORT=%CD%\logs\migration_moves_v042.txt"

 echo =====================================================
 echo   ROLERUN MANAGER - MOTOR, PC Y COMPATIBILIDAD
 echo =====================================================
 echo.

where dotnet >nul 2>nul
if errorlevel 1 goto :nodotnet

for /f "tokens=*" %%v in ('dotnet --version') do set DOTNET_VERSION=%%v
for /f "tokens=1 delims=." %%m in ("%DOTNET_VERSION%") do set DOTNET_MAJOR=%%m
if %DOTNET_MAJOR% LSS 10 goto :old_dotnet

 echo SDK detectado: %DOTNET_VERSION%
 echo.
 echo [1/3] Compilando el motor con PKHeX.Core...
dotnet publish "engine\RoleRun.SaveEngine\RoleRun.SaveEngine.csproj" -c Release -r win-x64 --self-contained false -o "engine\publish"
if errorlevel 1 goto :build_error
> "engine\publish\rolerun_engine_version.txt" echo oras-inventory-live-v2+role-markers-v3

 echo.
 echo [2/3] Generando catalogo oficial EN/ES desde PKHeX.Core...
"engine\publish\RoleRun.SaveEngine.exe" export-moves --output "data\move_catalog.json"
if errorlevel 1 goto :catalog_error

 echo.
 echo [3/3] Migrando las listas antiguas a IDs oficiales...
where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools_migrate_moves.py
) else (
    where python >nul 2>nul
    if errorlevel 1 goto :python_error
    python tools_migrate_moves.py
)
set MIGRATION_EXIT=%ERRORLEVEL%
if not "%MIGRATION_EXIT%"=="0" goto :migration_error

 echo.
 echo =====================================================
 echo Motor y base localizada preparados correctamente.
 echo Informe: %REPORT%
 echo =====================================================
pause
exit /b 0

:nodotnet
 echo No se ha encontrado .NET.
goto :install_help

:old_dotnet
 echo Tu SDK actual es %DOTNET_VERSION%, pero el motor necesita .NET 10.

:install_help
 echo.
 echo Instala el SDK x64 de .NET 10 desde la web oficial de Microsoft.
 echo.
start "" "https://dotnet.microsoft.com/download/dotnet/10.0"
pause
exit /b 1

:build_error
 echo.
 echo La compilacion del motor ha fallado.
 echo Este fallo ocurre antes de la migracion, por lo que no existe informe de movimientos.
pause
exit /b 1

:catalog_error
 echo.
 echo No se ha podido generar data\move_catalog.json.
 echo Este fallo ocurre antes de la migracion, por lo que no existe informe de movimientos.
pause
exit /b 1

:python_error
 echo.
 echo No se ha encontrado Python ni el lanzador "py".
 echo Instala Python y marca la opcion de anadirlo al PATH.
pause
exit /b 1

:migration_error
 echo.
 echo =====================================================
 echo La migracion se ha detenido. Codigo: %MIGRATION_EXIT%
 echo Informe detallado:
 echo %REPORT%
 echo =====================================================
if exist "%REPORT%" (
    echo.
    echo Abriendo el informe automaticamente...
    start "" notepad.exe "%REPORT%"
) else (
    echo.
    echo AVISO: no se encontro el informe esperado.
    echo Envia una captura completa de esta ventana.
)
pause
exit /b %MIGRATION_EXIT%
