@echo off
setlocal
cd /d "%~dp0"
title RoleRun Manager


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
 echo [1/2] Compilando el motor con PKHeX.Core...
dotnet publish "engine\RoleRun.SaveEngine\RoleRun.SaveEngine.csproj" -c Release -r win-x64 --self-contained false -o "engine\publish"
if errorlevel 1 goto :build_error
> "engine\publish\rolerun_engine_version.txt" echo oras-inventory-live-v2+role-markers-v3

 echo.
 echo [2/2] Generando catalogo oficial EN/ES desde PKHeX.Core...
"engine\publish\RoleRun.SaveEngine.exe" export-moves --output "data\move_catalog.json"
if errorlevel 1 goto :catalog_error

 echo.
 echo =====================================================
 echo Motor y base localizada preparados correctamente.
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
pause
exit /b 1

:catalog_error
 echo.
 echo No se ha podido generar data\move_catalog.json.
pause
exit /b 1


