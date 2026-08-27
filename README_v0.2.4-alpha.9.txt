RoleRun Manager v0.2.4-alpha.9

Esta versión corrige la composición de las operaciones PC de X/Y: conserva la
caja y casilla exactas al depositar, usa testigos de la caja correcta al mover
entre slots y permite retirar un Pokémon a una casilla libre del equipo. Todas
las escrituras siguen pasando por las precondiciones, readback y rollback del
writer X/Y. ORAS no hereda estas operaciones.

También cambia la cuarta categoría de Prisma: deja de ser Protección y pasa a
Problemas de Estado. Solo se ofrecen movimientos existentes en el catálogo del
juego activo. La validación física solicitada para esta alpha debe realizarse
en Pokémon X/Azahar.
