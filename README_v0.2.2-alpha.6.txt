RoleRun Manager v0.2.2-alpha.6

OBJETIVO DE ESTA BUILD
----------------------
Compatibilidad de detección de Pokémon Omega Rubí / Zafiro Alfa con Azahar oficial 2125.1.3 sin alterar las funciones live ya validadas.

QUÉ CAMBIA
-----------
1. Detección ORAS por RPC
   - RoleRun usa ahora como identidad principal el Title ID que Azahar expone en ProcessList.
   - Omega Rubí: 000400000011C400.
   - Zafiro Alfa: 000400000011C500.
   - `sango-1` / `sango-2` quedan como fallback, no como requisito obligatorio.

2. Diagnóstico
   - Si Azahar responde pero ORAS no aparece, RoleRun enseña los procesos visibles con nombre y Title ID.
   - El autoconector de ORAS ya no oculta la causa real bajo “Esperando entrada”.

3. Compatibilidad de Azahar
   - Azahar 2125.1.3 conserva el RPC v1 requerido por RoleRun y el puerto UDP 45987.
   - No se exige AzaharPlus para ORAS cuando el RPC del Azahar oficial está disponible.

NO CAMBIA
---------
- Direcciones RAM de ORAS.
- Lectura/escritura de equipo, roles, movimientos, PC, MT, inventario, medallas o muertes.
- X/Y ni Sol/Luna, salvo actualizar el número de versión visible.

PRUEBA MANUAL
-------------
1. Abre ORAS en Azahar 2125.1.3 en el mismo PC que RoleRun.
2. Comprueba que el servidor RPC está activo y que GDB no es necesario.
3. Abre la Run ORAS en RoleRun y espera unos segundos.
4. Debe entrar en vivo automáticamente.
5. Si no entra, copia exactamente el mensaje de la cabecera: ahora incluirá la lista nombre[TitleID] que Azahar está exponiendo.
