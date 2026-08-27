RoleRun Manager v0.2.2-alpha.66 — party y KO BDSP en Ryujinx

La prueba física demostró dos fuentes distintas: PlayerWork contiene la party
completa, pero sus HP quedan atrasados durante el combate; BTL_PARTY publica el
HP inmediato. También demostró que sus filas cambian de orden al elegir otro
Pokémon, mientras PokeID conserva el índice real de la party.

Alpha.66 registra el adaptador BDSP sobre Ryujinx HostMappedUnsafe y publica
party, roles, movimientos y HP de batalla en el Real-Time Core. Cada fila de
batalla se acepta solo si PokeID, especie, nivel y HP máximo coinciden con
PlayerWork. Un fallo de batalla no borra el equipo ni usa HP antiguos como si
fueran actuales.

BDSP SIGUE EN MODO DE SOLO LECTURA. Esta versión no escribe RAM y no habilita
todavía PC, MT, inventario, medallas ni sustituciones realtime.

VALIDACIÓN AUTOMATIZADA: 489 tests superados.

PRUEBA FÍSICA MÍNIMA

1. Deja desactivado el GDB Stub de Ryujinx y abre Perla Reluciente 1.3.0.
2. Cierra la instancia anterior de RoleRun y abre alpha.66 con tu Run BDSP.
3. Espera a que indique «Perla Reluciente en vivo».
4. Inicia un combate salvaje simple con un Pokémon que tenga PS y deja que se
   debilite.
5. Sin terminar aún el combate, comprueba si RoleRun resta exactamente una vida
   y retira ese Pokémon inmediatamente.
6. Elige al segundo Pokémon, termina o huye del combate y comprueba si el
   selector de sustituto aparece solo después de salir del combate.
