RoleRun Manager v0.2.2-alpha.2

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
