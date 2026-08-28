@echo off
setlocal
cd /d "%~dp0"
title RoleRun Manager - DONDE SE VAN LOS SEGUNDOS
echo.
echo   Resume la ultima medicion hecha con medir_lentitud.bat.
echo   Copia TODO lo que salga aqui y pegaselo a Claude.
echo.
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "tools/ver_lentitud.py"
) else (
    python "tools/ver_lentitud.py"
)
echo.
pause
