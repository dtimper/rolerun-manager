RoleRun Manager v0.2.2-alpha.59 — HP de batalla USUM resuelto en runtime

Esta versión elimina la dependencia funcional de una base de HP estática. Si la
dirección conocida no describe la party actual, RoleRun solo acepta otra base
después de demostrarla mediante la party PK7 exacta, la estructura completa de
seis filas, unicidad y doble lectura por Azahar RPC.

No se ha cambiado Sol/Luna, la UI, LivePartyWatch, el compromiso de muertes, PC,
movimientos ni progresión.

PRUEBA FÍSICA MÍNIMA

1. Reinicia el juego en Azahar y abre RoleRun fuera de combate.
2. Entra en un combate con al menos dos Pokémon vivos.
3. Deja que se debilite el primer Pokémon y comprueba que RoleRun descuenta una
   vida y retira su icono antes de terminar el combate.
4. Termina el combate normalmente.

RoleRun conserva automáticamente el journal completo en:

Documentos\RoleRun Manager\Logs\usum_battle_health_trace_latest.jsonl

y una copia inmutable dentro de `Logs\USUM-Battle-Traces`.
