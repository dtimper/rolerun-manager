RoleRun Manager v0.2.2-alpha.3

OBJETIVO DE ESTA BUILD
----------------------
Reparar la primera conexión real de Pokémon Sol/Luna con AzaharPlus antes de habilitar escrituras Gen 7.

CORRECCIONES
------------
1. Sol/Luna ya usa la misma interfaz 3DS instantánea que ORAS/X/Y.
   - No aparecen GUARDAR CAMBIOS ni DESCARTAR.
   - REVISAR CAMBIOS se conserva.

2. Corregido el bloqueo de alpha.1 observado con 6 cambios pendientes.
   - Esos cambios ya no impiden que el autoconector SM intente leer RAM.
   - Tampoco bloquean F5.
   - Tampoco congelan el monitor de party una vez conectado.

3. Diagnóstico visible.
   - Si Sol/Luna no conecta, la cabecera muestra el error real recibido del backend SM.
   - RoleRun sigue reintentando automáticamente.

SEGURIDAD
---------
Esta build continúa SIN ESCRITURAS de Sol/Luna.
No se escriben roles, movimientos, PC, inventario ni progreso.
Esto es intencional: primero hay que demostrar la dirección viva de la party en la partida real del usuario.

PRUEBA MANUAL
-------------
1. AzaharPlus abierto con Pokémon Sol/Luna en el overworld.
2. Servidor RPC activado; GDB Stub desactivado.
3. Abre la Run asociada al main actual.
4. Comprueba que ya NO aparecen GUARDAR CAMBIOS/DESCARTAR.
5. Espera unos segundos. Si conecta, la cabecera indicará party validada / SOLO LECTURA.
6. Si no conecta, copia exactamente el error que aparece ahora en la cabecera.
7. Si conecta, cambia el orden de dos Pokémon desde el propio juego sin guardar y verifica que RoleRun lo refleja.

VALIDACIÓN INTERNA
------------------
244 tests pasan.


CORRECCIÓN ALPHA.3
- Corrige el layout RAM de la party de Sol/Luna: 0xE8 bytes PK7 + 0x16 bytes de stats a +0x158, stride 0x1E4.
- La dirección candidata 0x34195E10 sigue siendo solo de lectura y solo se acepta tras identidad completa contra el main.
- Los errores de sincronización ya no se muestran en verde en la cabecera.
- No se habilita ninguna escritura de Sol/Luna.
