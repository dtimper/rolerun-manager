RoleRun Manager 1.12.9
======================

Cambios principales
-------------------
- Nueva pestaña CAJAS PC integrada en la ventana principal.
- El selector emergente de PC se conserva para acciones contextuales iniciadas desde Equipo.
- ENVIAR AL PC conserva el scroll sin mostrar el salto intermedio a la parte superior.
- Botón de confirmación de Support: estado deshabilitado apagado pero legible.
- La caja actual se conserva al encadenar movimientos Equipo ↔ PC desde la nueva pestaña.

Compatibilidad
--------------
La UI y las operaciones de PC usan el contrato común GameEngine y el SaveEngine genérico de PKHeX.Core. El código se aplica a DP, Platino, HGSS, BW, B2W2, XY, ORAS, SM, USUM y BDSP. La validación práctica más intensiva de esta rama se ha realizado con BDSP; conviene probar cada familia de guardado antes de darla por cerrada.

Motor
-----
Esta versión no modifica Program.cs ni el protocolo del motor respecto a 1.12.8. No es necesario ejecutar preparar_motor.bat si ya se preparó el motor de 1.12.4 o posterior.
