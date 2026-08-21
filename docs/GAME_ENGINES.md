# Arquitectura de motores de juego

La interfaz no llama directamente a PKHeX.Core. Toda operación sobre un guardado
pasa por el contrato `GameEngine`, y las funciones que necesitan datos externos
del juego se resuelven mediante un adaptador de datos específico.

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

Los demás juegos reutilizarán la misma interfaz y las mismas operaciones
pendientes, añadiendo únicamente su proveedor específico de datos de MTs.
