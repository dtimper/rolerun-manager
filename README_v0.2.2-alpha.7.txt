RoleRun Manager v0.2.2-alpha.7

OBJETIVO DE ESTA BUILD
----------------------
Cerrar el fallo de los intercambios de rol desde la barra flotante de Sol/Luna y validar en juego la escritura viva de movimientos introducida en alpha.5.

QUÉ CAMBIA
-----------
1. Barra flotante / swaps de rol SM
   - Un intercambio entre dos roles ocupados ya no intenta escribir dos PK7 dentro del mismo lote.
   - RoleRun aplica cada marcador como una escritura individual verificada y recaptura la party entre pasos.
   - Si un paso posterior falla, compensa los pasos anteriores en orden inverso.
   - No se cambian la base RAM, el stride ni el formato PK7.

2. Movimientos SM
   - Se conserva la escritura PK7 de movimientos de alpha.5 para validación manual: reemplazar, borrar/compactar y juego -> RoleRun.
   - MT continúa bloqueado; esta prueba es solo para movimientos normales de la ficha del Pokémon.

3. ORAS
   - Se conserva el arreglo de alpha.6 para Azahar 2125.1.3 (detección principal por Title ID).

PRUEBAS MANUALES RECOMENDADAS
------------------------------
A. Barra flotante:
   1. Con seis roles ocupados, arrastra un Pokémon a la casilla de otro rol.
   2. Comprueba en el juego que ambos marcadores se intercambian.
   3. Repite el intercambio en sentido contrario.

B. Rol individual:
   1. Desde el Dashboard cambia un rol a una casilla libre/SIN ROL si tienes una disponible.
   2. Comprueba que el marcador cambia en el juego.

C. Movimientos:
   1. Sustituye un movimiento desde RoleRun usando el flujo normal, NO una MT.
   2. Comprueba que aparece inmediatamente en Pokémon Sol/Luna.
   3. Elimina un movimiento y comprueba que los posteriores se compactan.
   4. Cambia/aprende un movimiento desde el juego y comprueba que RoleRun lo refleja.

NO PROBAR TODAVÍA
------------------
PC, MT, Caramelos/Repelentes/Dinero, bajas/sustituciones ni progreso de Sol/Luna.
