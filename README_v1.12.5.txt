RoleRun Manager 1.12.5

Correcciones principales
------------------------
- La barra flotante usa ahora el equipo proyectado completo: los cambios Equipo ↔ PC se reflejan antes de guardar.
- Cambiar roles ya no se bloquea durante una reorganización del equipo. Los cambios de rol siguen al Pokémon por identidad estable, no por slot.
- El orden de GUARDAR CAMBIOS respeta exactamente el orden en que el usuario preparó las operaciones.
- También se pueden cambiar roles desde el PC mientras hay movimientos Equipo ↔ PC pendientes.
- Los metadatos de roles del PC se consolidan en el mismo orden que los cambios para evitar pérdidas de rol al combinar mover + cambiar rol.
- Corregido el recorte lateral de textos en ¿Qué es RoleRun? y en el diálogo POKÉMON SIN ROL.
- El bloqueo durante una reorganización queda limitado al flujo de drafteo legado, que todavía sustituye movimientos por slot.

Motor de guardados
------------------
No cambia respecto a 1.12.4. No es necesario ejecutar preparar_motor.bat si ya se preparó para 1.12.4.
