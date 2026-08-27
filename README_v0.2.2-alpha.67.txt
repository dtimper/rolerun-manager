RoleRun Manager v0.2.2-alpha.67 — monitor BDSP tras guardar

CAUSA RAÍZ DEMOSTRADA

La prueba de alpha.66 no falló porque Ryujinx dejara de exponer la party ni
porque el KO estuviera mal mapeado. Una lectura independiente recuperó al
Pokémon debilitado a 0 HP desde el mismo proceso. RoleRun, en cambio, figuraba
conectado pero ya no tenía timer, snapshot ni baseline de salud.

Al detectar un cambio del archivo de guardado, RoleRun cancelaba correctamente
la lectura anterior para no mezclar estados, pero una condición histórica solo
volvía a arrancarla para ORAS. BDSP quedaba detenido después del primer guardado.

CORRECCIÓN

Alpha.67 rearma la lectura después de recargar el save para todos los backends
realtime registrados y mantiene excluidos los juegos sin lectura viva. También
guarda una traza automática y acotada de los snapshots BDSP y de las fronteras
de UI para que la prueba física sea concluyente.

No se han cambiado offsets, parsers, mapeo de filas, reglas de muerte ni rutas
de escritura. BDSP continúa estrictamente en modo de solo lectura.

VALIDACIÓN AUTOMATIZADA: 496 tests superados.

PRUEBA FÍSICA MÍNIMA

1. Deja desactivado el GDB Stub de Ryujinx y abre Perla Reluciente 1.3.0.
2. Cierra RoleRun alpha.66 y abre alpha.67 con tu Run BDSP.
3. Espera a que indique «Perla Reluciente en vivo».
4. Guarda una vez desde el menú del juego y espera tres segundos.
5. Inicia un combate salvaje simple y deja que se debilite un Pokémon que
   empezara con PS.
6. Comprueba, sin terminar el combate, si RoleRun resta exactamente una vida y
   retira ese Pokémon.
7. Elige al sustituto y termina o huye del combate. Comprueba que el selector de
   reemplazo aparece únicamente después de salir del combate.
