RoleRun Manager 1.13.0-alpha.17

CORRECCIÓN DE MOVIMIENTOS DESDE LA TARJETA
==========================================

1. Cajas PC
------------
La ficha de cada Pokémon del PC muestra ahora:

  ÚLTIMO ROL UTILIZADO · <rol>

en lugar de:

  ROL · <rol>

Así queda claro que el rol mostrado es el último contexto RoleRun conservado
para ese Pokémon mientras permanece en el PC.

2. Movimientos incompatibles
-----------------------------
Cada movimiento incompatible que aparece en rojo dentro de la tarjeta de un
Pokémon del equipo tiene ahora dos acciones propias:

- SUSTITUIR
  Abre las MT que el jugador tiene en la mochila y filtra únicamente las que:
  * existen realmente en la ROM/juego activo,
  * el Pokémon puede aprender,
  * son compatibles con su rol actual,
  * y no duplican un movimiento que ya conoce.

- ELIMINAR ATAQUE
  Elimina únicamente ese movimiento incompatible.

Si no existe ninguna MT válida para ese ataque, SUSTITUIR aparece desactivado
y ELIMINAR ATAQUE permanece disponible.

El selector de MT puede ahora sustituir directamente un movimiento ocupado;
no necesita borrar primero el ataque y dejar un hueco vacío. En ORAS/Azahar se
reutiliza la escritura viva verificada ya existente y las MT siguen siendo
reutilizables.

Todo el comportamiento validado de 1.13.0-alpha.16 se conserva.
