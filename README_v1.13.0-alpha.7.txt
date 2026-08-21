RoleRun Manager 1.13.0-alpha.7
================================

PC, MTs E INVENTARIO EN VIVO PARA ORAS
--------------------------------------
Después de un F5 válido con Azahar y Zafiro Alfa / Rubí Omega abiertos, RoleRun
aplica automáticamente en RAM, sin tocar `main`:

- Cambios de rol del equipo.
- Movimientos normales y drafteos.
- Roles de Pokémon que ya están en una caja del PC.
- Caramelo Raro ×999, Repelente Máximo ×999 y dinero máximo.
- MT estándar de ORAS en un hueco vacío, sin consumirla: en ORAS las MT son
  reutilizables.

La primera vez que abras el selector de MT de ORAS, RoleRun te pedirá confirmar
que tu ROM conserva la tabla original de MT y compatibilidades. Si las has
randomizado, responde NO: esta alpha no inventará una compatibilidad que no
puede leer desde la RAM.

SEGURIDAD
---------
Cada operación viva hace lo siguiente antes de confirmar nada:

1. Lee dos veces party, caja y/o mochila hasta obtener una instantánea idéntica.
2. Comprueba identidad PK6, checksum, movimiento previo, rol y disponibilidad
   de la MT cuando corresponda.
3. Escribe únicamente el PK6 almacenado, un registro de objeto o los cuatro
   bytes de dinero necesarios.
4. Relee y verifica todos los bytes modificados.
5. Si una comprobación falla, restaura en RAM los bytes originales de todos los
   bloques que ya hubieran sido modificados.

La barra flotante mantiene el mismo flujo anti-flicker: solo recibe la
publicación final ya confirmada.

RESET Y ESTADOS
--------------
Los cambios siguen viviendo solo en la RAM de Azahar. Guarda dentro del juego
cuando quieras conservarlos. Si haces Reset o cargas un estado anterior sin
guardar, RoleRun vigila el equipo y los pequeños bloques auxiliares que él mismo
modificó; al detectar una vuelta atrás, corrige la vista y el rol visible del PC
sin escribir nada de vuelta al juego.

LÍMITE QUE SIGUE PROTEGIDO
--------------------------
Los traslados físicos Equipo ↔ PC todavía usan el flujo normal con Azahar
cerrado. Un Pokémon de caja no contiene las estadísticas de combate que necesita
la estructura viva del equipo, y crear esas estadísticas fuera del juego sería
arriesgado, especialmente con una ROM randomizada. Esta alpha no copia un PK6
incompleto al equipo ni mueve slots de party a ciegas.

PRUEBA RECOMENDADA
-----------------
1. Haz un guardado normal dentro de ORAS como punto de recuperación.
2. Pulsa F5 en RoleRun.
3. Cambia el rol de un Pokémon de una caja y revisa que aparece el aviso de
   confirmación; vuelve a abrir la caja dentro del juego para comprobar la marca.
4. Prueba una utilidad de inventario y abre la mochila en ORAS.
5. Si tus MTs son originales, abre un hueco vacío de un Pokémon, confirma la
   tabla estándar y enseña una MT disponible. Comprueba que la MT sigue en la
   mochila.
6. Haz Reset sin guardar: RoleRun debe volver al estado real de Azahar al poco
   tiempo o al pulsar F5.
