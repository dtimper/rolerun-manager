RoleRun Manager v0.2.2-alpha.4

OBJETIVO DE ESTA BUILD
----------------------
Cerrar la segunda capa de Sol/Luna: marcadores/roles en tiempo real, en ambas direcciones.

QUÉ CAMBIA
-----------
1. Juego -> RoleRun
   - RoleRun ya NO conserva el rol del main por identidad.
   - Lee MarkingValue directamente del PK7 vivo.
   - Gen 7 guarda 2 bits por símbolo en 0x16; cualquier color distinto de None cuenta como marcado.
   - Si cambias el marcador dentro de Pokémon Sol/Luna, RoleRun debe reflejar el rol.

2. RoleRun -> juego
   - Los cambios de rol ya se escriben inmediatamente en la RAM de AzaharPlus.
   - Solo se modifica MarkingValue del PK7 objetivo y su checksum.
   - Se escribe únicamente el bloque almacenado 0xE8; no se toca la región separada de stats.
   - Tras escribir, RoleRun relee el PK7 y exige identidad + rol esperados.
   - Si falla, restaura los bytes originales y verifica el rollback.

3. Autoasignación
   - Igual que ORAS/X/Y, un miembro activo SIN ROL recibe el primer rol libre.
   - Por tanto, si abres una party sin marcadores, RoleRun debe escribir los seis marcadores de rol cuando haya seis huecos libres.

AÚN BLOQUEADO
--------------
- escritura de movimientos
- MT
- PC
- inventario
- progreso equivalente a medallas
- muertes/sustituciones

PRUEBA MANUAL
-------------
1. Abre Sol/Luna en AzaharPlus con RPC activo y entra al overworld.
2. Abre la Run. Espera a que indique Sol/Luna en vivo / roles PK7 activos.
3. Comprueba dentro del juego que los Pokémon tienen los marcadores correspondientes.
4. Cambia manualmente el marcador de un Pokémon dentro del juego y vuelve al overworld: RoleRun debe reflejar el nuevo rol.
5. Cambia el rol de un Pokémon desde RoleRun: el marcador debe cambiar dentro del juego sin pulsar Guardar Cambios.
6. Guarda normalmente dentro de Pokémon y reinicia el juego para comprobar que el marcador persiste.

VALIDACIÓN INTERNA
------------------
250 tests pasan.
