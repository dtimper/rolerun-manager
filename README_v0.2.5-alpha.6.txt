RoleRun Manager v0.2.5-alpha.6

Entrega de MT para ORAS.

- El selector solo usa la mochila leída y validada desde la RAM viva.
- Un fallo de lectura no se sustituye por el inventario potencialmente obsoleto
  del último guardado.
- Las MT de sexta generación siguen siendo reutilizables: enseñarlas no reduce
  su cantidad.
- La escritura conserva precondiciones, readback y rollback.

Validación automatizada focalizada: 14 tests superados.
Pendiente: validación física de una enseñanza de MT en ORAS/Azahar.
