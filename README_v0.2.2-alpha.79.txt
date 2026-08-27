RoleRun Manager v0.2.2-alpha.79 — selector PC BDSP desde RAM viva

- CAMBIAR CON PC espera una lectura completa de las 40×30 posiciones vivas.
- El save solo aporta nombres y niveles si coincide la identidad exacta.
- Nunca presenta la ocupación antigua del archivo como si fuera el PC actual.
- Si Ryujinx no entrega una matriz estable, el selector no se abre y no escribe.
- Conserva el writer transaccional 1↔1 de alpha.78 sin ampliar su alcance.

Causa física de alpha.78: RAM tenía Slowpoke en party y Pidgeotto en Caja 1:1;
el save todavía tenía el estado contrario y el modal lo mostraba antes de leer RAM.

Pendiente de validación física del primer intercambio RoleRun → Ryujinx.

Verificación: 62 pruebas BDSP dirigidas y 557 pruebas completas superadas.
