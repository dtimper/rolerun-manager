RoleRun Manager v0.2.2-alpha.1
================================

Objetivo de esta build
----------------------
Abrir la rama de Pokémon Sol/Luna con la primera función de tiempo real: LECTURA DEL EQUIPO EN VIVO mediante AzaharPlus RPC.

Esta alpha es deliberadamente de SOLO LECTURA para Sol/Luna. No habilita ninguna escritura RAM de Gen 7.

Qué cambia
----------
- Se añade SMLiveReader para leer estructuras PK7 de party mediante AzaharPlus RPC.
- Se añade SMRealTimeAdapter y Sol/Luna entra en RealTimeRegistry como backend independiente.
- Se detectan específicamente las ediciones retail:
  * Pokémon Sol:  0004000000164800
  * Pokémon Luna: 0004000000175E00
- La referencia RAM pública usada como punto inicial NO se acepta por sí sola.
- Antes de considerar demostrada una base de party, RoleRun exige:
  1. PK7 con tamaño/estructura/checksum válidos.
  2. Coincidencia completa por slot con el main cargado usando especie + PID + TID + SID.
  3. Una única base válida; si hay ambigüedad, se aborta.
- Si la referencia exacta no coincide, se hace una búsqueda LOCAL y de SOLO LECTURA alrededor de ella, sin asumir alineación.
- Una vez demostrada la base para ese proceso de Azahar, el monitor puede seguir cambios posteriores del equipo sin exigir volver a guardar el main.
- La caché queda ligada también al Process ID: si el proceso de Azahar cambia, RoleRun vuelve a calibrar en vez de reciclar a ciegas la dirección anterior.
- Cada snapshot usa doble lectura estable y vuelve a validar los PK7 antes de publicarlos.
- F5 funciona como resincronización de lectura para Sol/Luna.
- La conexión automática al abrir la Run y la reconexión del monitor incluyen Sol/Luna.
- El estado de Sol/Luna se muestra explícitamente como SOLO LECTURA.

Bloqueado expresamente en alpha.1
--------------------------------
- Escritura de roles/marcadores.
- Escritura de movimientos.
- MT en vivo.
- PC/cajas en vivo.
- Detección/flujo de muertes.
- Progreso equivalente a medallas.
- Caramelos Raros / Repelentes Máximos / dinero.
- Cualquier otra escritura RAM de Sol/Luna.

Estas funciones NO reutilizan offsets de X/Y u ORAS y no se programarán hasta tener datos reales que permitan validarlas.

Prueba manual principal
-----------------------
PRECONDICIÓN IMPORTANTE:
Para la primera calibración, el equipo del main configurado en RoleRun debe coincidir con el equipo que está actualmente dentro del juego.
Si no coincide, guarda UNA VEZ dentro de Pokémon Sol/Luna con el equipo actual antes de abrir/probar RoleRun.

1. Abre Pokémon Sol o Pokémon Luna en AzaharPlus.
2. En AzaharPlus deja GDB Stub DESACTIVADO.
3. Activa: Emulación > Configurar > Depuración > Activar servidor RPC.
4. Entra completamente en la partida y quédate en el overworld.
5. Abre RoleRun Manager v0.2.2-alpha.1 y entra en la Run de Sol/Luna asociada a ese main.
6. Espera la sincronización automática. Si no se produce, pulsa F5 una vez.
7. Resultado esperado:
   - aparece un estado tipo "Sol/Luna en vivo ... SOLO LECTURA";
   - RoleRun muestra el mismo número de Pokémon y el mismo orden que el juego;
   - especies, niveles y movimientos deben corresponder al equipo real.
8. SIN cerrar RoleRun y SIN guardar de nuevo, cambia únicamente el ORDEN de dos Pokémon desde el menú del propio juego.
9. Vuelve al overworld y espera unos segundos.
10. Resultado esperado: RoleRun refleja el nuevo orden automáticamente.
11. Pulsa F5.
12. Resultado esperado: sigue mostrando el equipo real y no aparece ninguna petición de "Guardar cambios" propia del modo vivo.

Si la primera calibración falla
------------------------------
NO pruebes escrituras ni avances a otra función.

Copia exactamente el mensaje de error que muestre RoleRun. Si indica que no pudo demostrar la dirección viva, eso es un aborto de seguridad correcto: no se escribió ningún byte.

En ese caso, primero comprueba que el main configurado tiene exactamente el mismo equipo/orden que el juego. Si lo tiene y sigue fallando, el siguiente paso será obtener un diagnóstico de RAM de esa ejecución concreta para localizar la estructura real sin suponer offsets.

Qué necesito que me cuentes tras la prueba
------------------------------------------
- Si usaste Pokémon Sol o Pokémon Luna.
- Si conectó automáticamente o necesitaste F5.
- Qué Pokémon mostraba el juego y en qué orden.
- Qué mostró RoleRun.
- Si al intercambiar dos slots el cambio apareció en RoleRun.
- Cualquier mensaje exacto de error, si lo hubo.

Regresiones automatizadas
-------------------------
241/241 tests pasan.

Las pruebas nuevas cubren, entre otras cosas:
- parsing PK7 de identidad/movimientos/nivel/PS;
- aceptación de la referencia solo con testigo completo del main;
- búsqueda cercana sin asumir alineación;
- rechazo de una party válida pero perteneciente a otro estado/equipo;
- rechazo de un proceso con Title ID incorrecto;
- contrato del adaptador sin escritura;
- seguimiento de cambios de party después de calibrar, sin volver a guardar;
- recalibración al cambiar el Process ID de Azahar.
