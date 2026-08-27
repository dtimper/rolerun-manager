RoleRun Manager v0.2.2-alpha.93 — densidad final y navegación sin reentrada

Cambios principales:
- Los cuatro movimientos de cada tarjeta de Equipo aparecen en una sola fila.
- El nombre del rol se muestra exactamente encima de su icono.
- Cada stat de la ficha integra debajo sus valores IV y EV.
- La capa oscura del menú conserva el tamaño de la página a cualquier escala y
  el lateral se desliza sin reconstruir el contenido.
- El cambio de pestaña espera al cierre real del menú y ya no reentra en el
  bucle de eventos durante el render.
- Drafteos no muestra una X inerte en la primera pantalla; la flecha posterior
  vuelve a elegir Pokémon.

No se añade ninguna dirección RAM, reader, writer ni regla funcional.

Verificación automatizada: 635 tests superados.
