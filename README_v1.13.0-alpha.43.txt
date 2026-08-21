RoleRun Manager 1.13.0-alpha.43
================================

Objetivo de esta build
----------------------
Hacer que el orden de los seis roles coincida también con los seis marcadores
físicos del Pokémon. Alpha.42 reordenaba la interfaz, pero conservaba el layout
histórico de las marcas para compatibilidad; eso hacía que, por ejemplo, Support
siguiera usando la 5ª marca aunque apareciera en la 6ª casilla.

Orden canónico desde alpha.43
-----------------------------
1. Líbero  -> círculo   ●
2. Asesino -> triángulo ▲
3. Mago    -> cuadrado  ■
4. Tanque  -> corazón   ♥
5. Prisma  -> estrella  ★
6. Support -> rombo     ◆

Este mismo orden se utiliza en:
- Dashboard y Equipo.
- Barra Flotante.
- Atajos Alt+1 ... Alt+6.
- Asignación automática de primer rol libre.
- Drafteos.
- Lectura de marcas desde ORAS.
- Escritura de marcas por RPC de Azahar.
- Escritura mediante SaveEngine.

Migración de Runs existentes
-----------------------------
Las Runs creadas antes de alpha.43 se consideran layout histórico. Al conectar
ORAS en Azahar, RoleRun lee los mismos seis bits con ambos layouts y remapea la
party una sola vez para conservar el rol SEMÁNTICO de cada Pokémon.

Ejemplo:
- antes: Support estaba físicamente en la 5ª marca;
- alpha.43 reconoce que ese Pokémon era Support;
- escribe Support en la 6ª marca;
- el Pokémon sigue siendo Support, pero ya ocupa el marcador correcto.

La migración es automática, no consume drafteos, no se registra como una acción
del usuario y no entra en REVISAR CAMBIOS. Para que la nueva marca sobreviva al
cierre de Azahar, guarda normalmente dentro del juego cuando quieras.

Motor .NET
----------
No es necesario ejecutar preparar_motor.bat para usar alpha.43 con el motor que
venía en alpha.42: la app traduce los nombres al bit físico correcto.
Si se ejecuta preparar_motor.bat, el motor se recompila ya con el nuevo layout y
la app detecta automáticamente ese contrato.

Medallas
--------
No se ha modificado la detección de medallas de alpha.41/42.

Pruebas recomendadas
--------------------
1. Abre una Run que ya tuviera roles asignados y conecta ORAS/Azahar.
2. Espera a que termine la sincronización inicial.
3. Comprueba que ningún Pokémon haya cambiado de rol semántico.
4. Abre la pantalla de marcadores del Pokémon dentro del juego:
   Líbero=1, Asesino=2, Mago=3, Tanque=4, Prisma=5, Support=6.
5. Cambia un Pokémon a cada rol desde RoleRun y confirma que se enciende
   exactamente la marca correspondiente.
6. Reinicia RoleRun y comprueba que conserva la misma interpretación.
7. Comprueba que las 8 medallas siguen detectándose como antes.
