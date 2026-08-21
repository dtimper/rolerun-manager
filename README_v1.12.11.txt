RoleRun Manager 1.12.11
========================

- Drafteos: ELEGIR y ↻ aparecen en la misma fila y con el mismo tamaño.
- BDSP: los huecos vacíos de movimientos muestran un botón +.
- El + lee las MTs que hay realmente en la mochila del guardado.
- RoleRun Manager localiza y analiza personal_masterdatas de Imposter's Ordeal para respetar:
  * la relación MT -> movimiento randomizada;
  * la compatibilidad MT/Pokémon randomizada;
  * la categoría física/especial/estado usada por la randomización.
- Si no encuentra personal_masterdatas automáticamente, permite seleccionarlo manualmente y recuerda la ruta.
- Las MTs ofrecidas se filtran por compatibilidad del Pokémon y por el rol actual; SIN ROL no aplica el filtro RoleRun.
- Enseñar una MT queda como cambio pendiente y consume exactamente una unidad al pulsar GUARDAR CAMBIOS.
- El movimiento y el consumo de la MT se escriben y validan de forma atómica.

Alcance actual
---------------
La interfaz y el modelo de cambios son comunes, pero la resolución de MTs randomizadas está conectada en esta versión a BDSP/Imposter's Ordeal. Los demás juegos se incorporarán por adaptadores propios sin rehacer la interfaz.

Motor
-----
Esta versión amplía el motor nativo con read-inventory y teach-tm. Ejecuta preparar_motor.bat una vez (los lanzadores también detectan el motor anterior y lo reconstruyen automáticamente).
