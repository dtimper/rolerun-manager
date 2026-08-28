@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Se colgo el juego?
echo.
echo   ============================================================
echo     SE COLGO EL JUEGO? - Pokemon Perla Reluciente
echo   ============================================================
echo.
echo   Lee lo que RoleRun apunto. No toca nada.
echo.
echo   Usalo despues de una sesion en la que el juego se haya
echo   quedado congelado, y pegale la salida a Claude.
echo.
where py >/dev/null 2>nul
if not errorlevel 1 (
    py -3 "tools/ver_congelados_bdsp.py"
) else (
    python "tools/ver_congelados_bdsp.py"
)
echo.
pause
