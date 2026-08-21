RoleRun Manager v0.2.2-alpha.46
=====================================

USUM — CAJAS PC SIN ESCANEO FCRAM

Problema reproducido físicamente en alpha.45:
- ENVIAR AL PC ya abortaba rápido si no tenía una matriz PC demostrada.
- Al abrir CAJAS PC, el antiguo descubrimiento estructural de BoxPokemon seguía
  recorriendo una región FCRAM enorme y la aplicación quedaba congelada.

Causa raíz corregida:
- PKMN-NTR LookupTable declara explícitamente para Ultra Sun / Ultra Moon:
    BoxOffset        = 0x33015AB0
    CurrentboxOffset = 0x33015AA7
    PartyOffset      = 0x33F7FA44
- Alpha.43 ya validó físicamente PartyOffset 0x33F7FA44 en esta ejecución.
- Alpha.46 elimina el descubrimiento FCRAM de CAJAS PC y usa BoxOffset únicamente
  como candidata que debe superar prueba runtime completa.

Prueba de lectura exigida por RoleRun:
1. dos lecturas RPC completas de 0x36600 bytes;
2. ambas lecturas deben ser idénticas;
3. se parsean los 960 slots como PK7 reales, incluidos huecos cifrados vacíos;
4. se rechaza cualquier identidad que aparezca simultáneamente en party y PC;
5. si algo falla, se aborta sin escanear FCRAM.

IMPORTANTE:
- Haber demostrado la LECTURA guest del PC no autoriza escrituras.
- ENVIAR AL PC / PC→Equipo siguen exigiendo una copia host exacta antes de usar
  WriteProcessMemory.
- Alpha.46 no vuelve a introducir brute-force desde CAJAS PC ni desde el botón.

PRUEBA FÍSICA PRIORITARIA:
1. Abre UltraSol/UltraLuna y RoleRun.
2. Entra directamente en CAJAS PC.
3. La pantalla debe cargar sin congelarse.
4. Comprueba que las cajas/slots coinciden con el juego.
5. Si carga correctamente, vuelve a EQUIPO y prueba ENVIAR AL PC una vez.

Si CAJAS PC da error, comparte el mensaje exacto. RoleRun habrá guardado además
usum_pc_diagnostic_latest.json sin lanzar un escaneo FCRAM.

Regresión interna: 393/393 tests.
