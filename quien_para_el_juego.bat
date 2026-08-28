@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Quien para el juego?
echo.
echo   ============================================================
echo     QUIEN PARA EL JUEGO?
echo   ============================================================
echo.
echo   SOLO LECTURA. No escribe nada en tu partida.
echo.
echo   Necesita Ryujinx con la partida cargada y RoleRun abierto.
echo.
echo   Durante 30 segundos: pon RoleRun delante, pincha en otra
echo   ventana, vuelve. Lo interesante son los cambios.
echo.
echo   Al terminar, copia la tabla y pegasela a Claude.
echo.
pause
echo.
where py >/dev/null 2>nul
if not errorlevel 1 (
    py -3 "tools/quien_para_el_juego.py"
) else (
    python "tools/quien_para_el_juego.py"
)
echo.
pause
