RoleRun Manager v0.2.2-alpha.62 — final de combate USUM sin falso selector

Alpha.61 ya ha quedado validada físicamente para la detección inmediata de dos
muertes: Porygon y Eevee restaron vida y desaparecieron de RoleRun durante el
combate. La misma prueba reveló un fallo posterior: al terminar, no apareció el
selector del PC.

La causa era el estado 0x00040005/6. El juego lo usa tanto en una sustitución
forzada como después del combate. Alpha.61 esperaba otro par de flags como final
obligatorio; si no lo muestreaba, mantenía la batalla suspendida para siempre.

Alpha.62 no adivina el significado del estado ambiguo. Durante el combate guarda
solo KO visibles >0→0 de filas con identidad PK7 validada. Al entrar en
0x00040005/6 mantiene cerrado el selector hasta que la PartyData validada publica
esos mismos Pokémon a 0 HP. Esa convergencia distingue el final real del estado
transitorio usando dos fuentes ya demostradas y sin añadir direcciones RAM.

No se han modificado la UI, LivePartyWatch, RunService, PC, writers, Sol/Luna ni
otros backends.

PRUEBA FÍSICA MÍNIMA

1. Cierra RoleRun y abre esta versión fuera de combate.
2. Entra en un combate y deja que se debiliten dos Pokémon, sustituyendo al
   primero desde la pantalla normal del juego.
3. Comprueba que RoleRun descuenta ambas vidas inmediatamente.
4. Comprueba que RoleRun no abre su selector mientras el juego pide el reemplazo.
5. Termina el combate.
6. Comprueba que entonces aparece «ELIGE AL SUSTITUTO DE».

La traza se guarda automáticamente en:

Documentos\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl
