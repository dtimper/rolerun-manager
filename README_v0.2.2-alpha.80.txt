RoleRun Manager v0.2.2-alpha.80 — CAMBIAR CON PC usa la matriz viva

- Corrige el modal exacto abierto por el botón CAMBIAR CON PC de Equipo.
- Espera la lectura RAM completa antes de construir sus tarjetas.
- No fuerza SaveData.bin para decidir qué Pokémon ocupa cada posición.
- Registra automáticamente inicio, éxito o error de la lectura del selector.
- Conserva sin cambios el writer transaccional 1↔1 de alpha.78.

Alpha.79 corrigió un selector PC distinto; por eso la segunda prueba siguió
mostrando Slowpoke y nunca alcanzó el reader live ni el writer.

Pendiente de validación física del primer intercambio RoleRun → Ryujinx.

Verificación: 63 pruebas BDSP dirigidas y 558 pruebas completas superadas.
