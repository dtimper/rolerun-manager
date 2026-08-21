RoleRun Manager v0.7.1
======================

Cambios principales
-------------------
- Los cambios de rol pasan a la misma cola de cambios pendientes que los drafteos.
- Al seleccionar un rol, GUARDAR CAMBIOS se activa inmediatamente.
- DESCARTAR y REVISAR CAMBIOS incluyen también los cambios de rol.
- Al guardar, el programa escribe el marcador correspondiente dentro del Pokémon:
  círculo=Líbero, triángulo=Tanque, cuadrado=Asesino, corazón=Mago,
  estrella=Support y rombo=Paladín.
- SIN ROL limpia los seis marcadores.
- Las asignaciones creadas con v0.7.0 se migran automáticamente a cambios pendientes.

IMPORTANTE
----------
Esta versión modifica el motor C#. Ejecuta preparar_motor.bat antes de abrir el programa.
El programa sigue creando un backup y valida el guardado final antes de activarlo.
