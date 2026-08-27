RoleRun Manager v0.2.2-alpha.75 — MT BDSP en tiempo real

QUÉ CAMBIA

- En BDSP ya no aparecen DESCARTAR ni GUARDAR CAMBIOS.
- Al enseñar una MT desde RoleRun, el movimiento cambia inmediatamente dentro
  de Perla Reluciente y se consume una unidad de la mochila en la misma
  transacción.
- SUSTITUIR, ELIMINAR ATAQUE y los cambios de rol de la party usan el mismo
  modelo inmediato.

SEGURIDAD

- Solo cubre Perla Reluciente 1.3.0 en Ryujinx HostMappedUnsafe.
- Antes de escribir se verifican sesión, party, identidad, movimiento, cantidad,
  punteros y bytes actuales. No se escribe durante un combate.
- Tras escribir se releen Ryujinx y los readers semánticos. Si una parte falla,
  RoleRun restaura y verifica tanto el PB8 como el registro de mochila.
- Equipo↔PC, roles de caja, medallas y utilidades generales siguen bloqueados;
  nunca se envían al save como sustituto silencioso.
- Mantén desactivado el GDB Stub.

VALIDACIÓN AUTOMATIZADA: 533 tests superados.

VALIDACIÓN FÍSICA PENDIENTE

Fuera de combate, enseña una MT poseída desde RoleRun y comprueba dentro del
juego el movimiento, sus PP y que la cantidad de esa MT baja exactamente una
unidad. Esta capacidad no se considera cerrada hasta completar esa prueba.
