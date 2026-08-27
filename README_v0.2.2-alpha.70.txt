RoleRun Manager v0.2.2-alpha.70 — PC BDSP de solo lectura

QUÉ AÑADE

RoleRun puede leer las 40 cajas de Perla Reluciente desde Ryujinx y reflejar
los movimientos realizados dentro del propio juego. La lectura conserva la
identidad, los datos almacenados y las marcas que representan el rol.

No se ha añadido ninguna dirección nueva: se usa la cadena de cajas ya
demostrada para Perla Reluciente 1.3.0. Toda la matriz se valida mediante doble
lectura, tamaño y checksum antes de publicarse.

SEGURIDAD

- BDSP continúa estrictamente en modo de solo lectura.
- RoleRun no escribe ni mueve Pokémon en Ryujinx.
- Una captura incoherente entre equipo y PC se descarta y se repite.
- Un fallo conserva la última vista; nunca se muestra como PC vacío.
- El GDB Stub debe permanecer desactivado.

VALIDACIÓN AUTOMATIZADA: 507 tests superados.

PRUEBA FÍSICA MÍNIMA

1. Cierra RoleRun y vuelve a abrirlo; debe mostrar alpha.70.
2. Mantén desactivado el GDB Stub y espera a «Perla Reluciente en vivo».
3. Abre una vez la pestaña CAJAS PC de RoleRun y espera unos tres segundos.
4. Dentro del juego, usa el PC y deposita un Pokémon vivo que no sea el último
   del equipo en un hueco vacío que puedas reconocer.
5. Comprueba que desaparece del equipo de RoleRun y aparece en esa caja con el
   mismo icono y rol.
6. Recupera el mismo Pokémon desde el juego y comprueba que vuelve al equipo
   de RoleRun conservando icono y rol.

No uses los botones de RoleRun para moverlo: esta prueba valida exclusivamente
el flujo juego→RoleRun de solo lectura.
