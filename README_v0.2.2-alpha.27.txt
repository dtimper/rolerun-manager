RoleRun Manager v0.2.2-alpha.27
=====================================

OBJETIVO
--------
Corregir la pérdida de sincronización Sol/Luna observada al mover un Pokémon entre Equipo y PC desde el propio juego.

PROBLEMAS DEMOSTRADOS EN ALPHA.26
---------------------------------
1. La calibración inicial de la party exigía coincidencia completa por slot con el último estado conocido. Si el jugador depositaba un Pokémon sin guardar y RoleRun tenía que recalibrar, la dirección correcta podía rechazarse aunque todos los miembros restantes coincidieran por identidad fuerte.
2. El monitor específico de Sol/Luna no llamaba a la reconciliación live del PC cuando cambiaba la party. ORAS/X/Y sí tenían ese hook en su carril genérico.
3. Una autoasignación de rol podía encontrar varias copias host idénticas de la party. Si el PC ya había quedado demostrado host↔guest, alpha.26 no reutilizaba esa prueba independiente para distinguir la copia viva.

CORRECCIONES
------------
- La calibración de party sigue prefiriendo coincidencia exacta por slot.
- Si el estado conocido está desfasado, solo se aceptan transiciones demostrables mediante especie+PID+TID+SID:
  * mismos miembros reordenados;
  * party que crece conservando íntegramente la anterior;
  * party que se reduce conservando únicamente miembros ya conocidos y su orden relativo;
  * sustitución 1-a-1 con todos los demás miembros conocidos.
- La party candidata debe ocupar un prefijo compacto de slots 1..N. Esto descarta falsas bases desplazadas un stride.
- En la búsqueda local, si varias candidatas sobreviven, solo puede ganar una con mayor cantidad de identidades fuertes conocidas; un empate sigue abortando.
- Cuando Sol/Luna detecta party_changed, lanza la reconciliación live del PC ANTES de cualquier autoasignación de rol.
- Una matriz PC ya demostrada host==guest conserva también la party host que condujo a esa prueba. Si Azahar mantiene buffers duplicados, esa ancla puede reutilizarse para roles/movimientos únicamente tras releer stored+stats de todos los miembros y confirmar que siguen idénticos a la party guest.

LO QUE SIGUE BLOQUEADO
----------------------
Las escrituras Equipo ↔ PC iniciadas DESDE RoleRun continúan en SOLO LECTURA. Alpha.27 corrige sincronización juego → RoleRun y la estabilidad de la party; todavía no mueve PK7 de caja desde la aplicación.

PRUEBA MANUAL RECOMENDADA
-------------------------
1. NO guardes para actualizar el main después del cambio anterior.
2. Abre alpha.27 con Pokémon Sol en el overworld.
3. Comprueba que ya no aparece el aviso rojo de que no puede demostrar la dirección viva de la party.
4. Desde el juego, deposita un Pokémon del equipo en el PC.
5. Comprueba que la barra flotante pasa a mostrar el equipo real reducido.
6. Si CAJAS PC está abierta, comprueba que aparece el Pokémon depositado sin F5 manual.
7. Saca un Pokémon del PC al equipo desde el juego. Comprueba que Equipo/barra/PC se actualizan y que la autoasignación de rol no queda en bucle de reintento.
8. Cierra RoleRun SIN guardar la partida, vuelve a abrirlo y confirma que puede recalibrar la party aunque el main siga desfasado.

VALIDACIÓN AUTOMÁTICA
---------------------
322/322 tests pasan.
Todos los módulos Python compilan correctamente.
