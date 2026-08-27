RoleRun Manager v0.2.4-alpha.10

Esta versión corrige el punto que impedía que los cambios Equipo↔PC de X/Y
llegaran al writer vivo. La interfaz ya no puede mostrar como confirmado un
depósito que nunca se envió a Azahar, y un fallo de readback elimina la
proyección en lugar de dejar un origen ficticio para el siguiente movimiento.

No se han relajado las protecciones RAM: identidad, testigos, contador,
readback y rollback continúan siendo obligatorios. ORAS y los demás backends no
han cambiado. Prisma con movimientos de problemas de estado queda validado en
Pokémon X.
