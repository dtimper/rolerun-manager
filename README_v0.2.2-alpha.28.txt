RoleRun Manager v0.2.2-alpha.28
================================

OBJETIVO
--------
Corregir una incoherencia visual/semántica de Sol/Luna detectada al mover Pokémon entre Equipo y PC desde el propio juego.

CAUSA DEMOSTRADA EN ALPHA.27
----------------------------
- El monitor obtenía una party nueva y válida.
- Antes de publicarla arrancaba la reconciliación del PC y la autoasignación de rol.
- Si la escritura automática de marcador fallaba o quedaba reintentando, la rama hacía return sin publicar la party nueva.
- El worker de PC sí podía terminar y publicar las cajas nuevas.
- Resultado: RoleRun podía mostrar la party antigua y el PC nuevo a la vez, duplicando visualmente una identidad que el juego no tenía duplicada.

CAMBIOS
-------
1. La captura de party validada por RPC se publica SIEMPRE antes de cualquier autoasignación de rol.
2. La reconciliación PC conserva before/after como testigos, pero ya no bloquea la verdad visual de la party.
3. La autoasignación de rol pasa a ser una escritura secundaria: si falla, RoleRun sigue mostrando la party real.
4. Nueva barrera de coherencia al terminar una lectura PC asíncrona:
   - si una identidad fuerte aparece simultáneamente en la party actualmente publicada y en la matriz PC recién leída,
   - esa captura PC no se publica,
   - se conserva la última vista de cajas coherente,
   - y se programa una relectura completa contra la party actual.
5. Las escrituras Equipo <-> PC desde RoleRun continúan bloqueadas en Sol/Luna.

PRUEBAS MANUALES
----------------
1. Abre Pokémon Sol y RoleRun alpha.28.
2. Sin guardar para actualizar el main, mueve un Pokémon del Equipo al PC desde el juego.
3. Comprueba que Dashboard/barra pierden inmediatamente ese Pokémon y CAJAS PC lo gana.
4. No debe aparecer la misma identidad simultáneamente en ambos lugares.
5. Saca después un Pokémon del PC al Equipo y comprueba ambos lados.
6. Si necesita autoasignar rol, puede aparecer brevemente la normalización, pero la composición del Equipo debe seguir siendo la real aunque la escritura del marcador se reintente.
