RoleRun Manager v0.2.2-alpha.71 — depósitos BDSP inmediatos

QUÉ CORRIGE

Alpha.70 leía correctamente que el Pokémon había salido del equipo y entrado
en una caja, pero no enlazaba ambos cambios en el momento de la transición. La
caja solo se refrescaba al volver a abrir la pestaña y, para entonces, RoleRun
ya no conservaba el nivel del miembro depositado; por seguridad mostraba Nv. 0.

Alpha.71 programa la lectura de cajas en cuanto cambia la composición del
equipo y conserva la identidad anterior hasta terminar la conciliación. El
Pokémon debe aparecer sin cambiar de pestaña y con su nivel, icono y rol.

SEGURIDAD

- BDSP continúa estrictamente en modo de solo lectura.
- No se han cambiado direcciones, parsers ni estructuras RAM.
- RoleRun no escribe ni mueve Pokémon en Ryujinx.
- Un cruce incoherente entre equipo y PC sigue descartándose y releyéndose.
- El GDB Stub debe permanecer desactivado.

VALIDACIÓN AUTOMATIZADA: 508 tests superados.

VALIDACIÓN FÍSICA

Completada el 22/08/2026 en Perla Reluciente 1.3.0 sobre Ryujinx 1.3.3 con GDB
desactivado: varios depósitos y recuperaciones se reflejaron inmediatamente en
CAJAS PC y Equipo, conservando los datos mostrados. Las escrituras desde
RoleRun y los movimientos solo entre cajas no forman parte de esta validación.

PRUEBA FÍSICA MÍNIMA

1. Reinicia RoleRun y confirma que muestra alpha.71.
2. Abre CAJAS PC en RoleRun y deja visible la caja 1.
3. En el PC del juego, deposita un Pokémon vivo del equipo en un hueco visible
   de esa caja.
4. Sin cambiar de pestaña en RoleRun, espera tres segundos.
5. Comprueba que aparece automáticamente con el mismo nivel, icono y rol.
6. Recupéralo desde el juego y espera otros tres segundos; debe desaparecer de
   la caja y volver al equipo conservando esos datos.

No uses los botones de RoleRun para moverlo: esta prueba valida solo el flujo
juego→RoleRun de lectura.
