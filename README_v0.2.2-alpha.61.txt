RoleRun Manager v0.2.2-alpha.61 — identidad real de filas de batalla USUM

Esta versión sustituye la inferencia incompleta de alpha.60 por la identidad PK7
que el propio juego mantiene alineada con cada fila de PS.

La reproducción física preservada demostró:

- party: Registeel, Eevee, Kangaskhan, Porygon, Tsareena, Carnivine;
- filas de batalla: Porygon, Eevee, Kangaskhan, Registeel, Tsareena, Carnivine;
- Eevee y Porygon empezaban ambos a 19/19, por lo que Max/Displayed/Actual no
  podían distinguirlos;
- la tabla PK7 de batalla sí identifica sin ambigüedad que la fila 1 es Porygon.

Alpha.61 usa especie+PID+TID+SID y checksum PK7 para enlazar cada fila con su
slot real. El resolvedor dinámico de la base HP valida el conjunto completo de
Max HP sin volver a imponer el orden de party. Una identidad ausente o ambigua
continúa cerrada; no se inventa ningún KO.

Se conserva el ciclo alpha.60: la selección forzada del juego suspende la lane,
pero no termina la batalla ni abre antes de tiempo el selector de RoleRun.

No se han modificado Sol/Luna, UI, LivePartyWatch, RunService, PC, writers,
movimientos ni progresión. La corrección realtime queda pendiente de una
validación física breve en UltraSol.

PRUEBA FÍSICA MÍNIMA

1. Cierra RoleRun y vuelve a abrir esta versión fuera de combate.
2. Entra en un combate y cambia a Porygon como primer Pokémon activo.
3. Deja que Porygon se debilite.
4. Comprueba que RoleRun descuenta una vida y retira a Porygon inmediatamente.
5. Mientras el juego muestra la elección del siguiente Pokémon, comprueba que
   RoleRun todavía no abre «ELIGE AL SUSTITUTO DE».
6. Termina el combate y comprueba que el selector de RoleRun aparece entonces.

RoleRun conserva automáticamente la traza en:

Documentos\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl

y una copia inmutable dentro de `Logs\USUM-Battle-Traces`.
