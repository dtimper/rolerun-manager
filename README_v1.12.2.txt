RoleRun Manager 1.12.2
=======================

Actualización de flujo de Equipo y PC centrada en preparar Pokémon sin restricciones innecesarias.

Cambios principales:
- ENVIAR AL PC ya no deja el hueco bloqueado: el + / ELEGIR SUSTITUTO abre el PC y convierte el envío pendiente en un intercambio directo.
- CONSULTAR PC permite gestionar el equipo directamente: añadir si hay hueco o elegir qué miembro sustituir.
- Los cambios Equipo ↔ PC pendientes se muestran dentro de la ventana del PC para que ningún Pokémon parezca desaparecer antes de guardar.
- Todo Pokémon que entre desde el PC entra SIN ROL y conserva sus cuatro movimientos. No se eliminan ataques durante la incorporación.
- SIN ROL es un estado de preparación permitido incluso con reglas activas. Puede guardarse, recibir Caramelos Raros, aprender movimientos y prepararse; no debe usarse en combate RoleRun hasta asignarle un rol.
- Al asignar un rol ocupado, RoleRun Manager avisa y, si se confirma, el anterior propietario queda SIN ROL con su moveset intacto.
- La validación estricta sigue aplicándose cuando un Pokémon ya tiene un rol: duplicidades y movimientos incompatibles deben resolverse.

Motor de guardados:
- Esta versión NO modifica RoleRun.SaveEngine respecto a 1.12.1. Si el motor de 1.12.x ya funciona en tu instalación, NO necesitas ejecutar preparar_motor.bat.
