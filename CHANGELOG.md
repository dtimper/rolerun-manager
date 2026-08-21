# v0.2.2-alpha.58 — USUM: traza diagnóstica del primer KO

## Objetivo
- No cambia el criterio de muerte de alpha.57.
- Registra una traza acotada por tick para demostrar por qué el primer Pokémon activo puede no publicar su KO mientras un sustituto posterior sí.

## Traza
- Archivo: `Logs/usum_battle_health_trace_latest.jsonl`.
- Cada muestra contiene las seis filas de batalla `Max HP / Displayed HP / Actual HP`.
- Incluye la party PK7 testigo, los slots validados/rechazados y los slots candidatos por coincidencia de Max HP.
- Permite distinguir entre: mapeo battle-row↔party-slot incorrecto, `Displayed HP` retrasado frente a `Actual HP`, o fallo de validación de un slot concreto.
- No añade escaneos FCRAM ni escrituras RAM.

## Evidencia externa
- USUMCheatMenu usa `0x30000158` como flag de combate y `0x30002776 / 0x30002778 / 0x30009760` con stride `0x330` para Max/Displayed/Actual HP del equipo del jugador.
- Su cheat de 1-Hit KO distingue explícitamente `Actual HP == 0` de `Displayed HP`, por lo que ambos campos pueden divergir durante una baja.

## Tests
- Nueva regresión: registra por separado `Actual HP=0` y `Displayed HP>0`, y conserva el vínculo de Max HP al slot de party.
- 414/414 tests.

# v0.2.2-alpha.56 — USUM: PS intra-combate validados por slot

## Causa raíz
- La sonda de batalla USUM era todo-o-nada: si un único slot no coincidía en Max HP con su PartyData live, se descartaban los PS de los seis Pokémon.
- Tras operaciones PC→Equipo o sustituciones, un slot runtime puede tardar en converger aunque los demás sigan siendo demostrables; eso hacía que VIDAS y barra solo se actualizaran al terminar el combate mediante el fallback postcombate.

## Corregido
- La validación de Max/Displayed/Actual HP se hace ahora por slot.
- Un slot solo publica HP de batalla si su Max HP coincide exactamente con la PartyData live de ese mismo slot y sus HP están dentro de rango.
- Los slots no demostrados conservan la lectura segura de party y no invalidan a los demás.
- Si ningún slot queda demostrado, se mantiene el rechazo total y el fallback postcombate.
- No se modifican Cementerio, sustituciones, PC, roles ni movimientos.

## Evidencia técnica
- USUMCheatMenu usa 0x30000158 como flag de batalla y 0x30002776 / 0x30002778 / 0x30009760 con stride 0x330 para Max/Displayed/Actual HP del equipo del jugador.

## Tests
- Regresión nueva: slot 1 validado cae a 0 mientras slot 2 tiene Max HP deliberadamente incoherente; el KO del slot 1 sigue publicándose en tiempo real.
- Regresión de seguridad: si ningún slot coincide, la sonda sigue rechazándose.
- 410/410 tests.

# v0.2.2-alpha.55 — Gen 7: sustitución por muerte sin Huevo fantasma

## Causa raíz
- El writer especial `replace-fainted` de Sol/Luna y UltraSol/UltraLuna vaciaba el hueco PC del sustituto escribiendo `0xE8` bytes a cero.
- El flujo normal `PC -> Equipo` ya usaba un `BoxPokemon` vacío cifrado válido, pero esta ruta antigua había quedado sin portar.
- En UltraSol el juego puede materializar ese falso vacío como un Huevo en la caja de origen del sustituto.

## Corregido
- `replace-fainted` usa ahora `encrypt_pk6_stored(bytes(0xE8))` para dejar el hueco origen como PK7 stored vacío válido.
- La verificación tardía exige no solo que el parser vea el hueco vacío, sino que los `0xE8` bytes guest coincidan exactamente con el vacío cifrado esperado.
- La corrección se aplica a `sm` y `usum`; no se ha modificado ORAS/X/Y.

## Tests
- Regresión nueva USUM: muerte -> sustituto desde Caja 1 -> origen queda vacío cifrado, Cementerio conserva al debilitado y rol heredado correcto.
- Regresión equivalente SM reforzada con comprobación byte a byte del vacío cifrado.
- 408/408 tests.

# v0.2.2-alpha.54 — USUM: refresco de objeto equipado + mochila MT por ItemsOffset real

## Corregido
- Juego → RoleRun: `held_item` ya no se preserva desde la captura anterior. El objeto equipado se publica desde el PK7 live, por lo que quitar/equipar un objeto dentro del juego se refleja automáticamente.
- MT USUM: eliminado el supuesto `PC -> Items` derivado de offsets del SAV.
- La mochila para MT usa como candidata RAM la referencia pública específica de USUM `ItemsOffset = 0x33011934` (`ItemsSize = 0x1000`) y solo se acepta tras doble lectura estable + prueba estructural distribuida contra el `main`.
- El selector de MT ya no cae a un escaneo FCRAM/host si la referencia publicada falla: aborta rápido y deja diagnóstico preciso.

## Seguridad
- Enseñar una MT sigue sin modificar la mochila; revalida la MT poseída justo antes de escribir el movimiento.
- Las utilidades que sí escriben inventario mantienen su prueba host+guest independiente.

## Tests
- 407/407 tests.

## v0.2.2-alpha.58

- Gen 7 (SM/USUM): la sincronización inicial lee ya el flag/HP de batalla en vez de dejar el estado en `unknown` hasta el primer monitor.
- Corrige una carrera donde la primera muerte tras abrir RoleRun podía convertirse en baseline si ocurría antes del primer tick (~950 ms), mientras las siguientes sí funcionaban.
- Arranque fuera de combate: baseline `none` inmediato. Arranque dentro de combate: baseline de HP sin cobrar muertes retrospectivas.
- Si la sonda inicial es desconocida o se conecta dentro de combate, el primer monitor se programa a 250 ms.
