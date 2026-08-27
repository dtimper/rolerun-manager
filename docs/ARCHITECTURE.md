# RoleRun Manager — Arquitectura desde v0.4

> Documento histórico centrado en la migración a IDs de movimientos y el motor
> de saves. Para la arquitectura realtime y el estado funcional actual, consultar
> `REALTIME_CORE.md` y `CURRENT_STATE.md`.

## Identificadores estables

Los movimientos se almacenan y se aplican mediante su ID numérico oficial. Los nombres visibles se obtienen de los recursos localizados de PKHeX.Core.

## Flujo de datos

1. `moves_legacy.json` conserva las listas originales en inglés como fuente de migración.
2. `preparar_motor.bat` genera `move_catalog.json` con nombres oficiales ingleses y españoles.
3. `tools_migrate_moves.py` convierte cada lista a IDs y genera `moves.json`.
4. La interfaz muestra el nombre español, pero entrega el ID al motor.
5. El motor escribe el ID en el guardado y valida el resultado.

## Seguridad

La aplicación continúa creando un backup y un archivo de salida independiente antes de validar cualquier modificación.
