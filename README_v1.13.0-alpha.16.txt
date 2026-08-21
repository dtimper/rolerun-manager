RoleRun Manager 1.13.0-alpha.16

INTERCAMBIO AUTOMÁTICO DE ROLES
===============================

Cuando cambias el rol de un Pokémon por otro rol que ya está ocupado por un
miembro del equipo, RoleRun Manager intercambia ahora los dos roles.

Ejemplo:
- Pokémon A = Mago
- Pokémon B = Tanque
- Cambias Pokémon A a Tanque

Resultado:
- Pokémon A = Tanque
- Pokémon B = Mago

Ya no se deja al Pokémon B como SIN ROL ni aparece un séptimo bloque visual en
Equipo por este tipo de cambio.

El comportamiento es el mismo tanto conceptualmente como en la estructura de
las seis casillas fijas que ya utiliza el drag & drop. Los movimientos no se
borran al intercambiar roles; si alguno no es compatible con el nuevo rol, se
seguirá mostrando en rojo para que puedas revisarlo.

Todo el resto de 1.13.0-alpha.15 (Azahar, ORAS, F5, MT randomizadas, sustitución
Equipo ↔ PC y escritura viva) se mantiene sin cambios.
