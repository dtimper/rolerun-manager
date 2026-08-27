# Arquitectura de motores de juego

> Este documento conserva el origen del contrato de motores. La matriz actual de
> juegos, proveedores ROM y backends realtime está en `CURRENT_STATE.md`.

La interfaz no llama directamente a PKHeX.Core. Toda operación sobre un guardado
pasa por el contrato `GameEngine`, y las funciones que necesitan datos externos
del juego se resuelven mediante un adaptador de datos específico.

## B2/W2

`B2W2Engine` continúa siendo la autoridad del guardado. Desde v0.2.6-alpha.1,
`B2W2RealTimeAdapter` puede superponer una party PK5 validada desde melonDS 1.1
para Pokémon Negro 2 (España). El backend es estrictamente de solo lectura y no
declara PC, curación, roles, MT, batalla, bajas ni progreso.

## Contrato común

Los motores exponen, entre otras operaciones:

- `read(save_path)` / `read_boxes(save_path)`
- `valid_moves(save_path)`
- `replace_move(...)`
- `set_role(...)` / `set_box_role(...)`
- `party_to_box(...)`, `box_to_party(...)`, `swap_party_box(...)`
- `read_inventory(save_path)`
- `teach_tm(...)`

La UI, las Runs, OBS, los drafteos, los cambios pendientes y el historial no
dependen del formato concreto del juego.

## MTs

Desde 1.12.11 la interfaz común puede tratar un hueco de movimiento vacío como
una acción `+`. La lectura de mochila y la escritura/consumo del objeto se apoyan
en el motor común de PKHeX.Core. Lo que sí cambia por juego es cómo se resuelven:

1. número de MT -> objeto de la mochila;
2. número de MT -> movimiento que enseña;
3. compatibilidad MT/Pokémon.

### BDSP / Imposter's Ordeal

El primer adaptador implementado es BDSP. `app/bdsp_tm_service.py` localiza o
permite seleccionar `personal_masterdatas` y lee de él las tablas `ItemTable`,
`PersonalTable` y `WazaTable`. De este modo la interfaz respeta la relación
MT->movimiento y la compatibilidad randomizadas por Imposter's Ordeal, en vez de
usar los datos vanilla.

Después de BDSP se añadieron proveedores ROM específicos para ORAS, X/Y, SM y
USUM, manteniendo la misma separación entre UI, reglas, motor de save y datos del
juego. El párrafo anterior describe el primer adaptador histórico; no implica que
BDSP siga siendo el único proveedor implementado.

El soporte realtime Switch usa una frontera distinta del motor de save.
`RyujinxBridge` traduce memoria invitada mediante las vistas
`HostMappedUnsafe`; su cliente normal mantiene permisos Windows exclusivamente
de consulta/lectura. El GDB Stub se conserva solo como diagnóstico porque su
degradación de rendimiento está demostrada. Para Perla Reluciente 1.3.0,
`BDSPRealTimeAdapter` publica party, PC, inventario/MT, HP de batalla y el
contador de medallas desde los SystemFlags vivos demostrados.
`BDSPLiveWriter` abre un handle RW independiente solo durante una transacción
ya validada y cubre roles/movimientos de party, consumo atómico de MT,
operaciones PC demostradas y las tres utilidades alpha.85/86. Estas últimas usan
los `SaveItem` 50/77 y el `MYSTATUS.gold` validado. Alpha.86 corrige la identidad
física de Repelente Máximo y crea su registro ausente con el siguiente orden
demostrado del bolsillo General; los roles manuales de un
Pokémon que permanece en caja quedan fuera de alcance. El inventario procede del array
`PlayerWork.SaveData.saveItem` validado; el motor de save es solo un testigo y
nunca sustituye una cantidad RAM distinta.
La baseline y las barreras de activación están en `BDSP_REALTIME_BASELINE.md`.
Desde alpha.101, BDSP reutiliza además los seis stats base de la misma fila de
`PersonalTable` para verificar y recalcular una transacción de EV por rol. El
writer no acepta el cálculo si no reproduce primero el bloque calc vivo del
PB8 objetivo; core y calc comparten readback y rollback.
