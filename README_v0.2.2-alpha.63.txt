RoleRun Manager v0.2.2-alpha.63 — varios selectores de baja consecutivos

La prueba física de alpha.62 confirmó que UltraSol detectó dos muertes durante
el combate y reconoció correctamente el final real. También demostró un fallo
posterior e independiente: al cerrar el primer selector, RoleRun no revisaba la
segunda baja hasta que la ventana principal se minimizaba y restauraba.

Alpha.63 hace avanzar esa cola automáticamente. Si el primer sustituto todavía
se está aplicando, espera y vuelve a intentarlo sin solapar ventanas ni
escrituras. No cambia direcciones RAM, lectores de juego, detección de muertes,
PC ni writers.

PRUEBA FÍSICA MÍNIMA

1. Abre RoleRun fuera de combate con dos Pokémon vivos disponibles.
2. Entra en un combate y deja que se debiliten esos dos Pokémon.
3. Termina el combate y espera al primer selector de RoleRun.
4. Cierra el primer selector con la X.
5. Sin minimizar ni restaurar RoleRun, comprueba que el selector del segundo
   Pokémon aparece automáticamente en aproximadamente un segundo.

La traza se guarda automáticamente en:

Documentos\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl
