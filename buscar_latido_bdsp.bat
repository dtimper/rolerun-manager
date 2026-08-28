@echo off
setlocal
cd /d "%~dp0"
title RoleRun - Buscar un latido (Perla Reluciente)
echo.
echo   ============================================================
echo     BUSCAR UN LATIDO - Pokemon Perla Reluciente
echo   ============================================================
echo.
echo   SOLO LECTURA. No escribe ni un byte en tu partida.
echo.
echo   Necesita Ryujinx abierto con tu partida cargada.
echo.
echo   IMPORTANTE: ponte QUIETO en el mapa, sin menus abiertos,
echo   y no toques nada mientras corre.
echo.
pause
echo.
where py >/dev/null 2>nul
if not errorlevel 1 (
    py -3 "tools/buscar_latido_bdsp.py"
) else (
    python "tools/buscar_latido_bdsp.py"
)
echo.
pause
