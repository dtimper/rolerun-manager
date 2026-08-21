RoleRun Manager v0.2.2-alpha.5

OBJETIVO DE ESTA BUILD
----------------------
Corregir el cambio de rol desde la barra flotante y abrir la tercera capa de paridad de Sol/Luna: movimientos PK7 en tiempo real.

QUÉ CAMBIA
-----------
1. Barra flotante -> roles
   - El drop de rol ya no modifica la Run dentro del propio ButtonRelease del Toplevel.
   - La acción se resuelve en el siguiente ciclo de Tk y entra por la misma ruta live verificada que el editor normal.
   - Los intercambios de dos roles se envían como un único lote y el writer valida ambos PK7 antes/después de escribir.

2. Movimientos -> juego
   - Sol/Luna admite ahora PendingChange del equipo en tiempo real: añadir/reemplazar/borrar movimientos.
   - PK7 usa IDs en 0x5A/0x5C/0x5E/0x60, PP en 0x62-0x65 y PP Ups en 0x66-0x69.
   - La tabla de PP base es específica de Gen 7 (`data/sm_move_pp.json`), derivada de PKHeX.Core MoveInfo7.
   - Además de tener PP conocido, el ID debe estar permitido por `valid_moves()` del guardado activo, que procede de `sav.MaxMoveID` de PKHeX. No se usa un máximo inventado.
   - Al borrar se compactan conjuntamente ID + PP + PP Ups.
   - Cada lote valida identidad fuerte, movimiento anterior, checksum, relectura y rollback.
   - Rol + movimiento sobre el mismo PK7 pueden aplicarse en un mismo lote.

3. Juego -> RoleRun
   - La lectura de movimientos ya existente en el PK7 vivo continúa siendo la fuente de verdad.
   - Después de una escritura confirmada, current_game se sustituye por la relectura real de Azahar.

AÚN BLOQUEADO
--------------
- enseñanza de MT (PendingTMTeach)
- PC / Equipo <-> PC
- roles del PC
- inventario / Caramelos / Repelentes / dinero
- progreso equivalente a medallas
- muertes / sustituciones

PRUEBA MANUAL
-------------
A. Barra flotante
1. Abre Sol/Luna en AzaharPlus, espera a que RoleRun indique tiempo real activo.
2. Abre BARRA FLOTANTE.
3. Arrastra un Pokémon desde una casilla de rol a otra ocupada.
4. Comprueba dentro del juego que ambos marcadores se intercambian.
5. Vuelve a moverlos desde la barra para confirmar que la operación es repetible.

B. Movimientos
1. En RoleRun, sobre un Pokémon del equipo, sustituye un movimiento por otro desde una acción normal de movimientos/drafteo (NO MT todavía).
2. Comprueba que el movimiento cambia inmediatamente en Pokémon Sol/Luna sin pulsar Guardar Cambios.
3. Borra un movimiento desde RoleRun y comprueba que el moveset se compacta correctamente.
4. Cambia un movimiento dentro del propio juego y vuelve al overworld: el monitor debe reflejarlo en RoleRun.

SEGURIDAD
---------
Si el Pokémon, el rol/movimiento anterior, el ID permitido, los PP, el checksum o la relectura no coinciden, RoleRun aborta. Si ya había escrito algún slot, restaura los 0xE8 bytes originales y verifica el rollback.

VALIDACIÓN INTERNA
------------------
259/259 tests automatizados pasan en el árbol de trabajo antes del empaquetado final.
