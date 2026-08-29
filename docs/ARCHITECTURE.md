# RoleRun Manager — Arquitectura desde v0.4

> Documento histórico centrado en la migración a IDs de movimientos y el motor
> de saves. Para la arquitectura realtime y el estado funcional actual, consultar
> `REALTIME_CORE.md` y `CURRENT_STATE.md`.

## Identificadores estables

Los movimientos se almacenan y se aplican mediante su ID numérico oficial. Los nombres visibles se obtienen de los recursos localizados de PKHeX.Core.

## Flujo de datos

1. `preparar_motor.bat` genera `move_catalog.json` con nombres oficiales ingleses y españoles.
2. `moves.json` agrupa los IDs por conjunto de rol y es la **fuente de verdad**: se edita a mano y no se regenera desde nada.
3. La interfaz muestra el nombre español, pero entrega el ID al motor.
4. El motor escribe el ID en el guardado y valida el resultado.

> Hasta la 0.3.1 existían `moves_legacy.json` y `tools_migrate_moves.py`, la
> migración de nombres ingleses a IDs de la v0.4.2. Se retiraron porque el script
> **reescribía `moves.json`** desde el legacy, y `moves.json` había crecido mucho
> desde entonces (dos conjuntos enteros, `defensa_ataque_fisico` y
> `support_ataque_estado`, no existen en el legacy). Ejecutarlo por error habría
> vaciado reglas de rol sin avisar. Están en el historial de git si hacen falta.

## Seguridad

La aplicación continúa creando un backup y un archivo de salida independiente antes de validar cualquier modificación.
