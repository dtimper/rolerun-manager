RoleRun Manager v0.2.2-alpha.43
=====================================

PRIMERA PRUEBA FÍSICA — POKÉMON ULTRASOL / ULTRALUNA

Objetivo de esta build:
Demostrar la cimentación realtime de USUM antes de validar writers.

Preparación:
1. Abre Pokémon UltraSol o UltraLuna en Azahar/AzaharPlus.
2. Asegúrate de que RPC está activado.
3. Carga una partida con al menos un Pokémon en el equipo.
4. Quédate en el overworld, fuera de combate.
5. Abre RoleRun Manager y selecciona Ultra Sol / Ultra Luna con su main/ROM configurados.

PRUEBA 1 — conexión + party
- RoleRun debe conectar al backend USUM.
- El equipo mostrado debe coincidir exactamente con el juego: especies, orden y número de miembros.
- Si coincide, prueba a reordenar dos Pokémon desde el propio juego y espera la sincronización.
- NO es necesario probar todavía PC, roles, movimientos ni muertes para considerar esta primera prueba superada.

Si no conecta o la party no coincide:
- No fuerces guardados ni cambies offsets manualmente.
- Cierra RoleRun después del fallo y comparte el mensaje exacto que aparece y, si existe, el diagnóstico USUM generado en Documentos\RoleRun Manager\Logs.

Seguridad de alpha.43:
- La referencia RAM de party se trata como candidata y debe demostrar identidades PK7 reales.
- El PC no usa 0x33015AB0 como BoxPokemon; esa dirección no está demostrada para ese propósito.
- Los writers de USUM se considerarán candidatos hasta que sus bases de lectura queden validadas físicamente.

Regresión interna: 387/387 tests.
