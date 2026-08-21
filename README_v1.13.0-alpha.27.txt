RoleRun Manager 1.13.0-alpha.27
================================

Corrección de sincronización ORAS + mejoras del monitor vivo.

CAMBIOS
- Corregida la sustitución por debilitado: `replace-fainted` entra ahora en la cola de autoaplicación ORAS y sí se envía al escritor vivo de Azahar.
- RoleRun ya no proyecta visualmente al sustituto antes de que Azahar confirme party + PC + cementerio.
- Las sustituciones por baja incorporan una segunda verificación diferida para detectar si ORAS acepta la escritura y después recompone el equipo antiguo.
- Si una sustitución falla, se retira únicamente la operación técnica, se conserva la vida perdida y RoleRun vuelve a mostrar la última party confirmada sin reabrir el selector.
- El selector `ELIGE AL SUSTITUTO DE...` es una notificación persistente de una sola aparición. Cerrar/reabrir RoleRun no la vuelve a mostrar.
- Las bajas pendientes heredadas de alpha.25/26 se migran como ya notificadas para evitar ventanas antiguas al actualizar.
- Si el Pokémon debilitado deja de estar en el equipo desde el propio juego, RoleRun cierra cualquier selector asociado y resuelve la baja externa automáticamente.
- La barra flotante ya no queda bloqueada por el selector: el modal se suspende/restaura como cualquier otra ventana secundaria.
- La creación de la barra tiene un cerrojo singleton para impedir dos Toplevel simultáneos por carreras entre botón, FocusOut y monitor.
- Los cambios de nivel se detectan en el monitor y se publican en Dashboard/Equipo sin F5.
- El nivel se toma directamente del byte de nivel del bloque de party vivo de ORAS; no se recalcula desde EXP ni mediante PKHeX.
- Nuevo monitor automático de medallas de ORAS: sincroniza el contador de RoleRun con el valor vivo del juego, tanto al entrar como al conseguir una nueva.
- La detección automática de Boss/Important Trainers queda pendiente de calibrar un identificador fiable de entrenador rival en RAM; no se suma ninguna curación por heurísticas.

PRUEBAS RECOMENDADAS
1. Cambia un Pokémon por otro desde el PC del juego con la Barra Flotante activa y comprueba que RoleRun no desaparece y actualiza el equipo.
2. Con una baja pendiente, cierra su selector, cambia el debilitado desde el PC del juego y comprueba que no reaparece la ventana.
3. Provoca una baja nueva, elige sustituto y comprueba que RoleRun solo muestra al nuevo Pokémon después de que Azahar lo confirme.
4. Sube un nivel dentro del juego y comprueba que Dashboard/Equipo lo reflejan automáticamente.
5. Comprueba que el contador de medallas coincide con las medallas actuales de la partida.

VALIDACIÓN
- 80 pruebas automatizadas superadas.
