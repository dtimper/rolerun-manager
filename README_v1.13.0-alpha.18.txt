RoleRun Manager 1.13.0-alpha.18

CAMBIOS PRINCIPALES

- ORAS adopta el flujo de guardado en vivo definitivo:
  * RoleRun Manager aplica y verifica los cambios compatibles directamente en Azahar.
  * El archivo main no se escribe desde RoleRun Manager.
  * El jugador consolida definitivamente los cambios usando Guardar dentro del propio juego.
- En ORAS, la cabecera muestra únicamente REVISAR CAMBIOS y BARRA FLOTANTE.
  DESCARTAR y GUARDAR CAMBIOS se conservan solo para motores que aún dependen del archivo de guardado.
- REVISAR CAMBIOS conserva las acciones reversibles de Pokémon aplicadas en vivo (roles, movimientos,
  MT reutilizables, roles del PC e intercambios Equipo↔PC uno a uno).
  * DESHACER genera la operación inversa sobre el estado actual de Azahar.
  * No restaura un PK6 antiguo completo, por lo que conserva EXP, PS, amistad y otros cambios posteriores.
  * Las acciones se deshacen de la más reciente a la más antigua para evitar estados inconsistentes.
  * Cuando el juego guarda y main cambia, la revisión se limpia: ese guardado pasa a ser la nueva base.
- Las utilidades de mochila no se revierten automáticamente para no restaurar cantidades antiguas después
  de compras/usos realizados dentro del juego; pueden volver a ajustarse desde Utilidades.
- La barra flotante recuerda la última pestaña principal utilizada. Al regresar a RoleRun Manager vuelve
  a esa pestaña en vez de forzar siempre Dashboard.

NOTA
Las operaciones ORAS que todavía cambian el tamaño del equipo siguen fuera de la escritura viva segura.
Los demás juegos mantienen temporalmente su flujo clásico de guardado hasta disponer de sincronización viva.
