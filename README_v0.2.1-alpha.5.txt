RoleRun Manager 0.2.1-alpha.5
================================

OBJETIVO
--------
Corregir la integración real de X/Y con el GDB Stub clásico de Citra. Alpha.4
podía detectar la configuración pero no completaba el arranque del target y,
además, trataba GDB como una conexión descartable.

QUÉ CAMBIA EN CITRA
-------------------
1. Con GDB Stub activo, RoleRun se conecta y envía `continue` automáticamente.
   Pokémon X/Y ya no debería quedarse bloqueado en `Iniciando...`.
2. La conexión GDB se mantiene abierta y se comparte entre snapshots/lecturas/
   escrituras. No se cierra al terminar cada ciclo del Real-Time Core.
3. Si Citra se reinicia, RoleRun invalida la sesión y vuelve a conectar.
4. Las escrituras siguen yendo al mismo transporte que produjo el último
   snapshot válido.

ORDEN DE ARRANQUE
-----------------
No debería importar. Puedes:
- abrir RoleRun/Run de X/Y y después lanzar X/Y en Citra, o
- dejar Citra detenido en `Iniciando...` y abrir RoleRun después.

En ambos casos, con GDB Stub activo en el puerto configurado (24689 por defecto),
RoleRun debe adjuntarse, enviar continue y permitir que el juego termine de
arrancar.

PRUEBA RECOMENDADA
------------------
1. Activa GDB Stub en Citra y reinicia Citra.
2. Abre Pokémon X/Y. Si queda en `Iniciando...`, abre RoleRun alpha.5 y entra en
   la Run. El juego debe continuar sin que hagas nada más.
3. Espera a que la cabecera muestre X/Y en vivo mediante Citra.
4. Cambia un marcador de rol dentro del juego SIN guardar. RoleRun debe verlo.
5. Cambia el rol desde RoleRun. El marcador debe cambiar inmediatamente en Citra.
6. Pulsa F5: debe resincronizar en vez de devolver el error de alpha.4.

X/Y -> AZAHAR
-------------
Se conserva. El adaptador multi-emulador sigue probando Azahar/RPC y Citra/GDB;
no se ha eliminado ninguna compatibilidad de alpha.3/alpha.4.

PENDIENTE EN X/Y
----------------
PC, mochila MT/MO, inventario, sonda de batalla, bajas/sustituciones y medallas
100% live en Citra siguen pendientes de las siguientes alphas.
