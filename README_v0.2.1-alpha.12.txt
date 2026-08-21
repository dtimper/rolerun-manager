RoleRun Manager 0.2.1-alpha.12
================================

Esta build corrige los dos problemas observados durante la primera prueba real de
CAJAS PC X/Y en alpha.11. El bug de Citra/GDB al usar Emulación -> Reiniciar
continúa aparcado y no se modifica en esta versión.

1) X/Y · PRIMER DEPÓSITO DEL JUEGO YA NO DEPENDE DEL ÚLTIMO MAIN
- Alpha.11 necesitaba al menos un Pokémon de PC conocido en el último main para
  usarlo como testigo y localizar la matriz viva. Si el main tenía las cajas
  vacías, dejar el primer Pokémon desde X/Y cambiaba la party pero RoleRun no
  podía demostrar dónde empezaban las cajas y conservaba la vista “0 Pokémon”.
- Alpha.12 incorpora la dirección conocida de Caja 1 / Slot 1 de X/Y,
  0x08C861C8, como ancla de lectura. Esa dirección aparece tanto en la
  implementación original como en el overhaul actual del Gen6 CTRPluginFramework.
- Cuando existen anchors guardados, se siguen comparando identidades PK6 antes
  de aceptar la base. La matriz completa también sigue descifrando/validando
  cada casilla antes de publicarla.

2) X/Y · “ENVIAR AL PC” YA NO MIENTE EN LA BARRA FLOTANTE
- Alpha.11 permitía crear desde la UI un cambio party-to-box aunque el escritor
  vivo de X/Y lo tenía explícitamente protegido. El resultado era únicamente
  visual: RoleRun/barra flotante quitaban al Pokémon, pero Citra no recibía el
  traslado.
- En alpha.12 una sesión Gen 6 viva no crea ni proyecta ese cambio si la escritura
  estructural no está validada. RoleRun informa de ello y no cambia nada.
- Para reducir el equipo, haz por ahora el traslado desde el PC del propio juego.
  La lectura/reconciliación viva debe reflejarlo de vuelta en RoleRun.

3) LO QUE SÍ SIGUE DISPONIBLE DESDE ROLERUN
- Cambio de rol de Pokémon almacenados, cuando la escritura PC está validada.
- Intercambio Equipo <-> PC 1↔1.
- Sustitución por muerte/cementerio en la ruta ya soportada.
- Party, roles, movimientos/MT, medallas y resto de funciones X/Y heredadas.

4) FUERA DE ALCANCE DE ALPHA.12
- Emulación -> Reiniciar con Citra/GDB activo sigue aparcado.
- party-to-box / box-to-party iniciados desde RoleRun siguen protegidos hasta
  validar de forma independiente cómo redimensionar la party viva de Gen 6.
- No se habilita ninguna escritura de inventario X/Y que siga sin calibrar.

PRUEBAS MANUALES RECOMENDADAS · X/Y / CITRA
--------------------------------------------
Usa el flujo que ya sabemos que arranca: X/Y completamente cargado y después
RoleRun. No uses Emulación -> Reiniciar durante estas pruebas.

A. DEJAR POKÉMON DESDE X/Y
   1. Con 5-6 Pokémon, abre el PC del propio juego.
   2. Deja un Pokémon en una casilla concreta.
   3. Espera a que RoleRun actualice el equipo.
   4. Abre CAJAS PC.
   ESPERADO: el Pokémon aparece exactamente en la caja/hueco elegido, incluso si
   el último main de RoleRun tenía el PC vacío.

B. SACARLO OTRA VEZ DESDE X/Y
   1. Saca ese mismo Pokémon del PC del juego.
   ESPERADO: vuelve al equipo de RoleRun y la casilla queda libre.

C. ENVIAR AL PC DESDE ROLERUN
   1. En Equipo pulsa ENVIAR AL PC durante la sesión X/Y viva.
   ESPERADO: RoleRun muestra un aviso y NO elimina al Pokémon ni del equipo ni de
   la barra flotante; tampoco se crea una falsa operación pendiente.

D. INTERCAMBIO 1↔1 DESDE ROLERUN
   1. Intercambia un Pokémon del equipo por uno del PC usando la operación 1↔1.
   ESPERADO: ambos Pokémon cambian realmente de sitio en X/Y y RoleRun.

E. ROL EN PC
   1. Cambia desde RoleRun el rol de un Pokémon almacenado.
   ESPERADO: la marca correspondiente cambia en el PK6 vivo y el rol permanece al
   volver a entrar en CAJAS PC.

VALIDACIÓN INTERNA
------------------
- 206/206 tests superados con stub gráfico.
- compileall: correcto.
- app/citra_broker.py: idéntico byte a byte a alpha.11.
- app/citra_gdb.py: idéntico byte a byte a alpha.11.
