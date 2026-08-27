RoleRun Manager v0.2.2-alpha.60 — cambio de activo y selección forzada USUM

Esta versión corrige dos causas demostradas en una captura física de UltraSol:

- la tabla de HP puede reordenar sus filas cuando se elige otro Pokémon activo;
  RoleRun vincula ahora cada fila con la party mediante una correspondencia
  demostrable y rechaza cualquier identidad ambigua;
- la pantalla forzada para elegir el siguiente Pokémon suspende el carril de HP,
  pero no termina la batalla; RoleRun mantiene cerrado su selector hasta observar
  el terminal real.

No se han añadido direcciones RAM ni escrituras. No se han modificado Sol/Luna,
UI, LivePartyWatch, RunService, PC, movimientos ni progresión.

PRUEBA FÍSICA MÍNIMA

1. Cierra la ventana de sustitución antigua si continúa abierta y abre alpha.60
   fuera de combate.
2. Entra en un combate con varios Pokémon vivos.
3. Cambia al Pokémon que quieras usar como activo y deja que se debilite.
4. Comprueba que RoleRun descuenta una vida y retira su icono en ese momento.
5. En la pantalla del juego para elegir el siguiente Pokémon, comprueba que
   RoleRun NO abre todavía «ELIGE AL SUSTITUTO DE».
6. Termina el combate y comprueba que el selector de RoleRun aparece después.

RoleRun conserva automáticamente la traza en:

Documentos\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl

y una copia inmutable dentro de `Logs\USUM-Battle-Traces`.
