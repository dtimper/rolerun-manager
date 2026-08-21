RoleRun Manager 0.2.1-alpha.6
================================

OBJETIVO
--------
Completar la siguiente superficie de Pokémon X/Y sobre el Real-Time Core:
PC vivo y MTs vivas, conservando tanto X/Y -> Azahar como X/Y -> Citra.

X/Y · PC VIVO
-------------
- RoleRun puede localizar y cachear la matriz viva de 31 cajas x 30 huecos.
- La base no se adivina por un offset fijo: se valida con identidades PK6 del
  último guardado y se rechaza si hay varias copias indistinguibles.
- Los cambios Equipo <-> PC hechos desde el juego pueden reconciliar las cajas
  sin esperar a guardar.
- Los roles de Pokémon del PC se pueden escribir en vivo.
- Una sustitución 1 a 1 Equipo <-> PC se aplica y verifica en RAM.
- Añadir/quitar miembros (cambiar el tamaño de la party) sigue protegido y no
  se envía en vivo todavía.

X/Y · MTs VIVAS
---------------
- El bolsillo MT/MO se localiza en la RAM del emulador con testigos del main y
  LiveBlockResolver; la dirección se cachea solo tras validación.
- El selector de MT usa la mochila viva, no una copia vieja del guardado.
- RoleRun lee la tabla MT->movimiento y compatibilidad directamente desde la
  ROM X/Y asociada a la Run. Esto evita asumir las MT originales y mantiene
  compatibilidad con ROMs randomizadas.
- Enseñar/sustituir un movimiento mediante MT escribe el PK6 de la party al
  instante. Las MT de sexta generación son reutilizables y no se consumen.

MULTI-EMULADOR
--------------
Todo lo anterior usa el transporte que ya produjo el snapshot vivo:
- X/Y -> Azahar RPC
- X/Y -> Citra GDB persistente

La sesión GDB persistente de alpha.5 no se ha sustituido. Citra sigue recibiendo
`continue` al conectar y RoleRun conserva la misma conexión entre snapshots.

TODAVÍA PENDIENTE EN X/Y
------------------------
- Medallas 100% live en Citra (Azahar mantiene el resolver Misc existente).
- Sonda específica de batalla.
- Muertes, cementerio y sustitución automática.
- Escritura de utilidades generales de mochila.
- Operaciones PC que cambian el tamaño de la party.

PRUEBA RECOMENDADA
------------------
1. Abre X/Y en Citra con GDB Stub activo o en Azahar y espera a que RoleRun
   indique X/Y en vivo.
2. Desde el juego, cambia un Pokémon del equipo por uno del PC sin guardar.
   Comprueba que RoleRun actualiza equipo y PC.
3. Abre CAJAS PC y cambia el rol de un Pokémon del PC. Debe escribirse al
   instante en el juego.
4. Con el equipo completo, sustituye 1 a 1 un Pokémon desde CAJAS PC y comprueba
   que el intercambio aparece inmediatamente en el emulador.
5. En Equipo, usa + / SUSTITUIR POR MT. El selector debe mostrar las MT que
   realmente tienes y que el Pokémon puede aprender según tu ROM X/Y.
6. Enseña una MT y comprueba que el movimiento aparece sin guardar ni reiniciar.
7. Si algo falla, graba 5-15 segundos desde Diagnóstico y genera el replay ZIP.

VERIFICACIÓN DE ESTA BUILD
--------------------------
- 186/186 pruebas superadas con stub gráfico de CI.
- compileall completo correcto.
